from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from datetime import datetime
import time

import httpx

from app.core.config import get_settings
from app.services.retry import with_retries
from app.services.runtime_config import get_runtime_overrides

logger = logging.getLogger(__name__)


@dataclass
class MinifluxEntry:
    id: int
    feed_id: int
    feed_title: str
    title: str
    url: str
    content: str
    summary: str
    author: str | None
    published_at: datetime


@dataclass
class MinifluxFeed:
    id: int
    title: str
    feed_url: str
    site_url: str | None
    category_title: str | None
    disabled: bool


class MinifluxClient:
    def __init__(self, api_key: str | None = None) -> None:
        settings = get_settings()
        overrides = get_runtime_overrides()
        self.base_url = (overrides.get("miniflux_base_url") or settings.miniflux_base_url).rstrip("/")
        self.timeout = settings.miniflux_timeout_seconds
        self.api_key = api_key or settings.miniflux_api_key or None
        self.admin_username = overrides.get("miniflux_admin_username") or settings.miniflux_admin_username
        self.admin_password = overrides.get("miniflux_admin_password") or settings.miniflux_admin_password
        self.app_api_key_name = settings.miniflux_app_api_key_name

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-Auth-Token"] = self.api_key
            return headers

        token = base64.b64encode(f"{self.admin_username}:{self.admin_password}".encode("utf-8")).decode("utf-8")
        headers["Authorization"] = f"Basic {token}"
        return headers

    def health(self) -> bool:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                res = client.get(f"{self.base_url}/v1/me", headers=self._headers())
                return res.status_code == 200
        except Exception as exc:
            logger.warning("Miniflux health check failed: %s", exc)
            return False

    def authenticate(self) -> bool:
        with httpx.Client(timeout=self.timeout) as client:
            res = client.get(f"{self.base_url}/v1/me", headers=self._headers())
            return res.status_code == 200

    def ensure_api_key(self) -> str | None:
        if self.api_key:
            return self.api_key

        # best-effort API key creation while authenticated with Basic auth.
        with httpx.Client(timeout=self.timeout) as client:
            try:
                create = client.post(
                    f"{self.base_url}/v1/api_keys",
                    headers=self._headers(),
                    json={"description": self.app_api_key_name},
                )
                if create.status_code in (200, 201):
                    key_payload = create.json()
                    token = key_payload.get("api_key") or key_payload.get("key")
                    if token:
                        self.api_key = token
                        logger.info("Created Miniflux API key for app bootstrap.")
                        return token
            except Exception as exc:
                logger.info("Miniflux API-key creation endpoint unavailable; continuing with Basic auth (%s)", exc)
        return None

    def get_entries(self, *, status: str = "all", limit: int = 200, after_entry_id: int | None = None, feed_id: int | None = None) -> list[MinifluxEntry]:
        params = {"status": status, "direction": "asc", "limit": limit, "order": "id"}
        if after_entry_id:
            params["after_entry_id"] = after_entry_id
        if feed_id:
            params["feed_id"] = feed_id

        def _fetch():
            with httpx.Client(timeout=self.timeout) as client:
                res = client.get(
                    f"{self.base_url}/v1/entries",
                    headers=self._headers(),
                    params=params,
                )
                res.raise_for_status()
                return res.json()

        payload = with_retries(_fetch, attempts=3, base_delay_seconds=0.5, logger=logger, operation="miniflux get_entries")

        entries: list[MinifluxEntry] = []
        for item in payload.get("entries", []):
            entries.append(
                MinifluxEntry(
                    id=item["id"],
                    feed_id=item.get("feed", {}).get("id", 0),
                    feed_title=item.get("feed", {}).get("title", "Unknown Source"),
                    title=item.get("title") or "Untitled",
                    url=item.get("url") or "",
                    content=item.get("content") or "",
                    summary=item.get("summary") or "",
                    author=item.get("author"),
                    published_at=datetime.fromisoformat(item["published_at"].replace("Z", "+00:00")),
                )
            )
        return entries

    def get_entries_with_latency(self, **kwargs) -> tuple[list[MinifluxEntry], float]:
        start = time.perf_counter()
        entries = self.get_entries(**kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return entries, elapsed_ms

    def mark_entries_read(self, entry_ids: list[int]) -> None:
        if not entry_ids:
            return

        def _mark():
            with httpx.Client(timeout=self.timeout) as client:
                res = client.put(
                    f"{self.base_url}/v1/entries",
                    headers=self._headers(),
                    json={"entry_ids": entry_ids, "status": "read"},
                )
                res.raise_for_status()
            return None

        with_retries(_mark, attempts=3, base_delay_seconds=0.5, logger=logger, operation="miniflux mark_entries_read")

    def bootstrap_feeds(self, feeds: list[dict[str, str]]) -> dict:
        with httpx.Client(timeout=self.timeout) as client:
            categories_res = client.get(f"{self.base_url}/v1/categories", headers=self._headers())
            categories_res.raise_for_status()
            categories = categories_res.json()

            category_title = "Yesterday's Scoop"
            category_id = None
            for category in categories:
                if category.get("title") == category_title:
                    category_id = category["id"]
                    break

            if category_id is None:
                create_cat = client.post(
                    f"{self.base_url}/v1/categories",
                    headers=self._headers(),
                    json={"title": category_title},
                )
                create_cat.raise_for_status()
                category_id = create_cat.json()["id"]

            created = 0
            skipped = 0
            for feed in feeds:
                try:
                    add = client.post(
                        f"{self.base_url}/v1/feeds",
                        headers=self._headers(),
                        json={"feed_url": feed["feed_url"], "category_id": category_id, "title": feed["name"]},
                    )
                    if add.status_code == 201:
                        created += 1
                    elif add.status_code == 409:
                        skipped += 1
                except Exception as exc:
                    logger.warning("Unable to bootstrap Miniflux feed %s: %s", feed["feed_url"], exc)
            return {"category_id": category_id, "created": created, "skipped": skipped}

    def bootstrap(self, default_feeds: list[dict[str, str]]) -> dict:
        if not self.health():
            return {"ok": False, "error": "miniflux_unreachable"}
        if not self.authenticate():
            return {"ok": False, "error": "miniflux_auth_failed"}

        token = self.ensure_api_key()
        feed_result = self.bootstrap_feeds(default_feeds)
        return {
            "ok": True,
            "token": token,
            "feed_result": feed_result,
        }

    def list_feeds(self) -> list[MinifluxFeed]:
        with httpx.Client(timeout=self.timeout) as client:
            res = client.get(f"{self.base_url}/v1/feeds", headers=self._headers())
            res.raise_for_status()
            payload = res.json()

        feeds: list[MinifluxFeed] = []
        for item in payload:
            feeds.append(
                MinifluxFeed(
                    id=item.get("id"),
                    title=item.get("title") or "Untitled",
                    feed_url=item.get("feed_url") or "",
                    site_url=item.get("site_url"),
                    category_title=(item.get("category") or {}).get("title"),
                    disabled=bool(item.get("disabled", False)),
                )
            )
        return feeds

    def add_feed(self, *, feed_url: str, category_title: str = "Yesterday's Scoop") -> dict:
        with httpx.Client(timeout=self.timeout) as client:
            categories_res = client.get(f"{self.base_url}/v1/categories", headers=self._headers())
            categories_res.raise_for_status()
            categories = categories_res.json()
            category_id = None
            for category in categories:
                if category.get("title") == category_title:
                    category_id = category["id"]
                    break
            if category_id is None:
                create_cat = client.post(
                    f"{self.base_url}/v1/categories",
                    headers=self._headers(),
                    json={"title": category_title},
                )
                create_cat.raise_for_status()
                category_id = create_cat.json()["id"]

            add = client.post(
                f"{self.base_url}/v1/feeds",
                headers=self._headers(),
                json={"feed_url": feed_url, "category_id": category_id},
            )
            if add.status_code not in (201, 409):
                add.raise_for_status()
            return {"created": add.status_code == 201, "status_code": add.status_code}

    def delete_feed(self, feed_id: int) -> None:
        with httpx.Client(timeout=self.timeout) as client:
            res = client.delete(f"{self.base_url}/v1/feeds/{feed_id}", headers=self._headers())
            if res.status_code not in (204, 404):
                res.raise_for_status()

    def set_feed_disabled(self, feed_id: int, disabled: bool) -> None:
        with httpx.Client(timeout=self.timeout) as client:
            res = client.put(
                f"{self.base_url}/v1/feeds/{feed_id}",
                headers=self._headers(),
                json={"disabled": disabled},
            )
            res.raise_for_status()

    def import_opml(self, opml_text: str) -> None:
        with httpx.Client(timeout=self.timeout) as client:
            res = client.post(
                f"{self.base_url}/v1/feeds/import",
                headers=self._headers(),
                files={"file": ("sources.opml", opml_text, "text/xml")},
            )
            if res.status_code not in (200, 201):
                res.raise_for_status()

    def export_opml(self) -> str:
        with httpx.Client(timeout=self.timeout) as client:
            res = client.get(f"{self.base_url}/v1/export", headers=self._headers())
            res.raise_for_status()
            return res.text

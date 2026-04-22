"""Seed high-quality default source catalog and bootstrap Miniflux feeds."""

from app.db.session import SessionLocal
from app.services.miniflux_client import MinifluxClient
from app.services.source_catalog import DEFAULT_SOURCE_CATALOG, seed_source_registry


def main() -> None:
    with SessionLocal() as db:
        created = seed_source_registry(db)
        print(f"Seeded {created} sources in local registry")

    payload = [{"name": s["name"], "feed_url": s["feed_url"]} for s in DEFAULT_SOURCE_CATALOG]
    created_remote = MinifluxClient().bootstrap_feeds(payload)
    print(f"Bootstrapped feeds in Miniflux: {created_remote}")


if __name__ == "__main__":
    main()

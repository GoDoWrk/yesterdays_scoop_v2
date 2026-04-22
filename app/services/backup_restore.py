from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import AppSetting, Article, Cluster, ClusterEvent, FeedFetchState, ServiceState, SocialItem, Source

BACKUP_SCHEMA_VERSION = 1


class BackupValidationError(ValueError):
    pass


@dataclass
class BackupPayload:
    schema_version: int
    created_at: str
    includes_articles: bool
    data: dict[str, list[dict[str, Any]]]


def export_backup(db: Session, *, include_articles: bool = False) -> dict[str, Any]:
    data: dict[str, list[dict[str, Any]]] = {
        "app_settings": [_model_to_dict(row) for row in db.scalars(select(AppSetting)).all()],
        "sources": [_model_to_dict(row) for row in db.scalars(select(Source)).all()],
        "feed_fetch_states": [_model_to_dict(row) for row in db.scalars(select(FeedFetchState)).all()],
        "clusters": [_model_to_dict(row) for row in db.scalars(select(Cluster)).all()],
        "cluster_events": [_model_to_dict(row) for row in db.scalars(select(ClusterEvent)).all()],
        "social_items": [_model_to_dict(row) for row in db.scalars(select(SocialItem)).all()],
    }
    data["articles"] = [_model_to_dict(row) for row in db.scalars(select(Article)).all()] if include_articles else []

    payload = BackupPayload(
        schema_version=BACKUP_SCHEMA_VERSION,
        created_at=datetime.now(timezone.utc).isoformat(),
        includes_articles=include_articles,
        data=data,
    )
    return asdict(payload)


def backup_bytes(db: Session, *, include_articles: bool = False) -> bytes:
    payload = export_backup(db, include_articles=include_articles)
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def restore_backup(db: Session, payload: dict[str, Any], *, confirm_overwrite: bool) -> dict[str, int]:
    if not confirm_overwrite:
        raise BackupValidationError("Restore aborted: overwrite confirmation is required.")

    parsed = _validate_payload(payload)

    with db.begin_nested():
        _clear_restorable_tables(db)

        _bulk_insert(db, AppSetting, parsed.data["app_settings"])
        _bulk_insert(db, Source, parsed.data["sources"])
        _bulk_insert(db, FeedFetchState, parsed.data["feed_fetch_states"])
        _bulk_insert(db, Cluster, parsed.data["clusters"])
        _bulk_insert(db, Article, parsed.data["articles"])
        _bulk_insert(db, ClusterEvent, parsed.data["cluster_events"])
        _bulk_insert(db, SocialItem, parsed.data["social_items"])

    db.commit()
    return {
        "app_settings": len(parsed.data["app_settings"]),
        "sources": len(parsed.data["sources"]),
        "feed_fetch_states": len(parsed.data["feed_fetch_states"]),
        "clusters": len(parsed.data["clusters"]),
        "articles": len(parsed.data["articles"]),
        "cluster_events": len(parsed.data["cluster_events"]),
        "social_items": len(parsed.data["social_items"]),
    }


def _validate_payload(payload: dict[str, Any]) -> BackupPayload:
    if not isinstance(payload, dict):
        raise BackupValidationError("Invalid backup: expected JSON object.")

    version = payload.get("schema_version")
    if version != BACKUP_SCHEMA_VERSION:
        raise BackupValidationError(
            f"Unsupported backup schema_version={version}. Expected {BACKUP_SCHEMA_VERSION}."
        )

    data = payload.get("data")
    if not isinstance(data, dict):
        raise BackupValidationError("Invalid backup: missing data object.")

    required_keys = {"app_settings", "sources", "feed_fetch_states", "clusters", "cluster_events", "articles"}
    optional_keys = {"social_items"}
    missing = [k for k in required_keys if k not in data]
    if missing:
        raise BackupValidationError(f"Invalid backup: missing sections {', '.join(missing)}")

    for key in required_keys | optional_keys:
        if key not in data:
            data[key] = []
        if not isinstance(data[key], list):
            raise BackupValidationError(f"Invalid backup: section '{key}' must be a list.")

    _backfill_legacy_source_metadata(data["sources"])

    return BackupPayload(
        schema_version=version,
        created_at=str(payload.get("created_at") or ""),
        includes_articles=bool(payload.get("includes_articles", True)),
        data=data,
    )


def _backfill_legacy_source_metadata(source_rows: list[dict[str, Any]]) -> None:
    if not source_rows:
        return
    from app.services.source_catalog import infer_source_metadata

    for row in source_rows:
        if not isinstance(row, dict):
            continue
        if row.get("source_type") and row.get("topic") and row.get("geography"):
            continue
        inferred = infer_source_metadata(str(row.get("name") or ""), str(row.get("feed_url") or ""))
        row.setdefault("source_type", str(inferred["source_type"]))
        row.setdefault("topic", str(inferred["topic"]))
        row.setdefault("geography", str(inferred["geography"]))


def _clear_restorable_tables(db: Session) -> None:
    db.execute(delete(ClusterEvent))
    db.execute(delete(SocialItem))
    db.execute(delete(Article))
    db.execute(delete(Cluster))
    db.execute(delete(FeedFetchState))
    db.execute(delete(Source))
    db.execute(delete(AppSetting))
    db.execute(delete(ServiceState))


def _bulk_insert(db: Session, model, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        converted = {}
        for col in model.__table__.columns:
            value = row.get(col.name)
            if isinstance(value, str) and _is_datetime_col(col):
                try:
                    converted[col.name] = datetime.fromisoformat(value)
                except Exception:
                    converted[col.name] = value
            else:
                converted[col.name] = value
        db.add(model(**converted))


def _model_to_dict(model) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in model.__table__.columns:
        value = getattr(model, col.name)
        if isinstance(value, datetime):
            out[col.name] = value.isoformat()
        else:
            out[col.name] = value
    return out


def _is_datetime_col(column) -> bool:
    try:
        return column.type.python_type is datetime
    except Exception:
        return False

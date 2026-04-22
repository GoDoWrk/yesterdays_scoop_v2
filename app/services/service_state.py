from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ServiceState


def get_or_create_service_state(db: Session) -> ServiceState:
    state = db.scalar(select(ServiceState).where(ServiceState.id == 1))
    if state:
        return state
    state = ServiceState(id=1)
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def mark_scheduler_tick(db: Session) -> None:
    state = get_or_create_service_state(db)
    state.scheduler_last_tick_at = datetime.now(timezone.utc)
    db.commit()


def mark_worker_heartbeat(db: Session) -> None:
    state = get_or_create_service_state(db)
    state.worker_last_heartbeat_at = datetime.now(timezone.utc)
    db.commit()

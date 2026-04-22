from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

T = TypeVar("T")


def with_retries(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay_seconds: float = 0.5,
    logger: logging.Logger | None = None,
    operation: str = "operation",
) -> T:
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # intentionally broad for external I/O wrappers
            last_exc = exc
            if logger:
                logger.warning("%s failed (attempt %s/%s): %s", operation, attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(base_delay_seconds * attempt)
    assert last_exc is not None
    raise last_exc

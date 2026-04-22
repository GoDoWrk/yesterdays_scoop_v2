import app.services.retry as retry


def test_with_retries_succeeds_after_transient_error():
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RuntimeError("transient")
        return "ok"

    assert retry.with_retries(flaky, attempts=3, base_delay_seconds=0.0, operation="test") == "ok"


def test_with_retries_raises_when_exhausted():
    def always_fail():
        raise RuntimeError("nope")

    try:
        retry.with_retries(always_fail, attempts=2, base_delay_seconds=0.0, operation="test")
    except RuntimeError as exc:
        assert "nope" in str(exc)

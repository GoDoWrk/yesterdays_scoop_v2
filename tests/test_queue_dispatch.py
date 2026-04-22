from types import SimpleNamespace

import app.main as main


class DummyInspect:
    def __init__(self, ok: bool):
        self.ok = ok

    def ping(self):
        return {"worker@local": {"ok": "pong"}} if self.ok else {}


class DummyControl:
    def __init__(self, ok: bool):
        self.ok = ok

    def inspect(self, timeout=1.0):
        return DummyInspect(self.ok)


def test_dispatch_task_rejects_when_worker_unreachable(monkeypatch):
    monkeypatch.setattr(main, "celery_app", SimpleNamespace(control=DummyControl(False)))

    task = SimpleNamespace(delay=lambda: SimpleNamespace(id="abc"))
    ok, token = main._dispatch_task(task, task_name="pipeline")

    assert ok is False
    assert "worker_unreachable" in token


def test_dispatch_task_returns_task_id_on_success(monkeypatch):
    monkeypatch.setattr(main, "celery_app", SimpleNamespace(control=DummyControl(True)))

    task = SimpleNamespace(delay=lambda: SimpleNamespace(id="abc"))
    ok, token = main._dispatch_task(task, task_name="pipeline")

    assert ok is True
    assert token == "abc"

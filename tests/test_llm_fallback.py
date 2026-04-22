from app.services.llm import LLMService


class FailingProvider:
    def summarize_cluster(self, payload):
        raise RuntimeError("boom")

    def embed(self, text):
        raise RuntimeError("boom")


def test_embed_falls_back_to_hash(monkeypatch):
    monkeypatch.setattr(LLMService, "_build_provider", lambda self, _: FailingProvider())
    monkeypatch.setattr(LLMService, "_build_fallback_provider", lambda self: None)

    service = LLMService()
    vec = service.embed("hello world")

    assert len(vec) == 64

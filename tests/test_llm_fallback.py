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


def test_openai_provider_selection_uses_runtime_api_key(monkeypatch):
    monkeypatch.setattr("app.services.llm.get_settings", lambda: type("Settings", (), {
        "llm_provider": "openai",
        "openai_api_key": "",
    })())
    monkeypatch.setattr("app.services.llm.get_runtime_overrides", lambda: {
        "llm_provider": "openai",
        "openai_api_key": "runtime-key",
    })

    monkeypatch.setattr("app.services.llm.OpenAIProvider", lambda: "openai-provider")
    monkeypatch.setattr("app.services.llm.OllamaProvider", lambda: "ollama-provider")
    monkeypatch.setattr(LLMService, "_build_fallback_provider", lambda self: None)

    service = LLMService()

    assert service.primary == "openai-provider"

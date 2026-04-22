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


def test_ollama_health_uses_runtime_base_url(monkeypatch):
    monkeypatch.setattr(
        "app.services.llm.get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "llm_provider": "ollama",
                "openai_api_key": "",
                "ollama_base_url": "http://env-ollama:11434",
            },
        )(),
    )
    monkeypatch.setattr(
        "app.services.llm.get_runtime_overrides",
        lambda: {"ollama_base_url": "http://runtime-ollama:11434"},
    )

    urls = []

    class DummyResponse:
        status_code = 200

    class DummyClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url):
            urls.append(url)
            return DummyResponse()

    monkeypatch.setattr("app.services.llm.httpx.Client", DummyClient)

    service = LLMService()

    assert service.ollama_health() is True
    assert urls == ["http://runtime-ollama:11434/api/tags"]

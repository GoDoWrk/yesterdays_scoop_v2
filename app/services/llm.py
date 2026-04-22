from __future__ import annotations

import hashlib
import json
import logging
from abc import ABC, abstractmethod

import httpx
from openai import OpenAI

from app.core.config import get_settings
from app.services.retry import with_retries
from app.services.runtime_config import get_runtime_overrides

logger = logging.getLogger(__name__)

PROMPT = """You are summarizing one evolving news cluster.
Return strict JSON with keys:
cluster_title, summary, why_it_matters, what_changed (array), key_entities (array), representative_url, source_urls (array).
Keep it factual, concise, and family-safe.
"""


class LLMProvider(ABC):
    @abstractmethod
    def summarize_cluster(self, payload: list[dict]) -> dict | None:
        raise NotImplementedError

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class OllamaProvider(LLMProvider):
    def __init__(self) -> None:
        self.settings = get_settings()
        overrides = get_runtime_overrides()
        self.base_url = (overrides.get("ollama_base_url") or self.settings.ollama_base_url).rstrip("/")
        self.chat_model = overrides.get("ollama_chat_model") or self.settings.ollama_chat_model
        self.embed_model = overrides.get("ollama_embed_model") or self.settings.ollama_embed_model

    def summarize_cluster(self, payload: list[dict]) -> dict | None:
        def _call() -> dict | None:
            with httpx.Client(timeout=90.0) as client:
                res = client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.chat_model,
                        "format": "json",
                        "messages": [
                            {"role": "system", "content": PROMPT},
                            {"role": "user", "content": json.dumps(payload)},
                        ],
                        "stream": False,
                    },
                )
                res.raise_for_status()
                raw = res.json().get("message", {}).get("content", "")
                if not raw:
                    return None
                return json.loads(raw)

        return with_retries(_call, attempts=2, base_delay_seconds=0.6, logger=logger, operation="ollama summarize")

    def embed(self, text: str) -> list[float]:
        def _call() -> list[float]:
            with httpx.Client(timeout=45.0) as client:
                res = client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.embed_model, "prompt": text[:6000]},
                )
                res.raise_for_status()
                return res.json().get("embedding", [])

        return with_retries(_call, attempts=2, base_delay_seconds=0.5, logger=logger, operation="ollama embed")


class OpenAIProvider(LLMProvider):
    def __init__(self) -> None:
        self.settings = get_settings()
        overrides = get_runtime_overrides()
        self.api_key = overrides.get("openai_api_key") or self.settings.openai_api_key
        self.model = overrides.get("openai_model") or self.settings.openai_model
        self.client = OpenAI(api_key=self.api_key)

    def summarize_cluster(self, payload: list[dict]) -> dict | None:
        completion = self.client.responses.create(
            model=self.model,
            temperature=0.2,
            max_output_tokens=650,
            input=[{"role": "system", "content": PROMPT}, {"role": "user", "content": json.dumps(payload)}],
        )
        raw = completion.output_text
        if not raw:
            return None
        return json.loads(raw)

    def embed(self, text: str) -> list[float]:
        emb = self.client.embeddings.create(model="text-embedding-3-small", input=text[:6000])
        return emb.data[0].embedding


class LLMService:
    """Provider abstraction with graceful fallback.

    Default path: Ollama
    Optional fallback: OpenAI when configured and selected.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        overrides = get_runtime_overrides()
        self.provider_name = overrides.get("llm_provider") or self.settings.llm_provider
        self.fallback_enabled = bool(overrides.get("openai_fallback_enabled", True))
        self.primary = self._build_provider(self.provider_name)
        self.fallback = self._build_fallback_provider()

    def summarize_cluster(self, payload: list[dict]) -> dict | None:
        if not payload:
            return None
        return self._run_with_fallback("summarize", payload)

    def embed(self, text: str) -> list[float]:
        if not text.strip():
            return []
        out = self._run_with_fallback("embed", text)
        if out:
            return out
        logger.warning("Embedding provider unavailable; using deterministic lightweight local fallback embedding.")
        return _hash_embedding(text)

    def _run_with_fallback(self, operation: str, payload):
        try:
            if operation == "summarize":
                return self.primary.summarize_cluster(payload)
            return self.primary.embed(payload)
        except Exception as exc:
            logger.warning("Primary LLM provider '%s' failed for %s: %s", self.provider_name, operation, exc)

        if not self.fallback:
            return None

        try:
            logger.info("Trying fallback LLM provider 'openai' for %s", operation)
            if operation == "summarize":
                return self.fallback.summarize_cluster(payload)
            return self.fallback.embed(payload)
        except Exception as exc:
            logger.warning("Fallback OpenAI provider failed for %s: %s", operation, exc)
            return None

    def _build_provider(self, provider_name: str) -> LLMProvider:
        if provider_name == "openai":
            if not self.settings.openai_api_key:
                logger.warning("LLM_PROVIDER=openai but OPENAI_API_KEY is missing; falling back to Ollama.")
                return OllamaProvider()
            return OpenAIProvider()
        return OllamaProvider()

    def _build_fallback_provider(self) -> LLMProvider | None:
        if self.provider_name == "openai":
            return None
        if not self.fallback_enabled:
            return None
        if not self.settings.openai_api_key:
            return None
        try:
            return OpenAIProvider()
        except Exception:
            return None

    def ollama_health(self) -> bool:
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(f"{self.settings.ollama_base_url.rstrip('/')}/api/tags")
                return res.status_code == 200
        except Exception:
            return False

    def list_ollama_models(self) -> list[str]:
        base_url = (get_runtime_overrides().get("ollama_base_url") or self.settings.ollama_base_url).rstrip("/")
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(f"{base_url}/api/tags")
                res.raise_for_status()
                payload = res.json()
                return [m.get("name") for m in payload.get("models", []) if m.get("name")]
        except Exception:
            return []

    def pull_ollama_model(self, model: str) -> None:
        base_url = (get_runtime_overrides().get("ollama_base_url") or self.settings.ollama_base_url).rstrip("/")
        with httpx.Client(timeout=120.0) as client:
            res = client.post(
                f"{base_url}/api/pull",
                json={"name": model, "stream": False},
            )
            res.raise_for_status()


def _hash_embedding(text: str, dim: int = 64) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    vec = []
    for i in range(dim):
        b = digest[i % len(digest)]
        vec.append((b / 255.0) * 2 - 1)
    return vec

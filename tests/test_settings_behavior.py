import inspect

from app.main import update_settings


def test_settings_route_only_exposes_db_backed_fields():
    params = inspect.signature(update_settings).parameters
    assert "llm_provider" not in params
    assert "openai_api_key" not in params
    assert "enable_ai_summarization" in params
    assert "poll_interval_minutes" in params

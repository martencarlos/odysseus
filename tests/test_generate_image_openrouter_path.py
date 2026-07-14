"""do_generate_image must call OpenRouter's actual image-generation endpoint
(POST /api/v1/images) rather than the OpenAI-shaped /images/generations path.
Using the wrong path 404s for every OpenRouter image model — this was the
root cause of most OpenRouter models appearing to "return an error" in the
gallery Generate tab.
"""

import base64

import pytest

from src import ai_interaction


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


class _FakeAsyncClient:
    """Captures the URL/payload of the single POST made by do_generate_image."""

    calls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        _FakeAsyncClient.calls.append({"url": url, "json": json, "headers": headers})
        tiny_png = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
        return _FakeResponse(200, {"data": [{"b64_json": tiny_png}]})


@pytest.fixture(autouse=True)
def _reset_calls():
    _FakeAsyncClient.calls = []
    yield
    _FakeAsyncClient.calls = []


def test_openrouter_image_generation_uses_images_path(monkeypatch, tmp_path):
    monkeypatch.setattr(ai_interaction, "GENERATED_IMAGES_DIR", str(tmp_path))

    def fake_resolve_model(spec, owner=None):
        return (
            "https://openrouter.ai/api/v1/chat/completions",
            "google/gemini-2.5-flash-image",
            {"Authorization": "Bearer test-key"},
        )

    monkeypatch.setattr(ai_interaction, "_resolve_model", fake_resolve_model)
    monkeypatch.setattr("httpx.AsyncClient", _FakeAsyncClient)
    # Avoid touching the real gallery DB.
    monkeypatch.setattr(
        ai_interaction, "_resolve_model", fake_resolve_model,
    )

    import asyncio

    async def _run():
        return await ai_interaction.do_generate_image(
            "a cat\ngoogle/gemini-2.5-flash-image\nsquare\nauto",
            session_id=None,
            owner=None,
        )

    result = asyncio.run(_run())

    assert "error" not in result, result
    assert len(_FakeAsyncClient.calls) == 1
    called_url = _FakeAsyncClient.calls[0]["url"]
    assert called_url.endswith("/images"), called_url
    assert not called_url.endswith("/images/generations"), called_url


def test_openai_image_generation_still_uses_generations_path(monkeypatch, tmp_path):
    monkeypatch.setattr(ai_interaction, "GENERATED_IMAGES_DIR", str(tmp_path))

    def fake_resolve_model(spec, owner=None):
        return (
            "https://api.openai.com/v1/chat/completions",
            "gpt-image-1",
            {"Authorization": "Bearer test-key"},
        )

    monkeypatch.setattr(ai_interaction, "_resolve_model", fake_resolve_model)
    monkeypatch.setattr("httpx.AsyncClient", _FakeAsyncClient)

    import asyncio

    async def _run():
        return await ai_interaction.do_generate_image(
            "a cat\ngpt-image-1\nsquare\nauto",
            session_id=None,
            owner=None,
        )

    result = asyncio.run(_run())

    assert "error" not in result, result
    called_url = _FakeAsyncClient.calls[0]["url"]
    assert called_url.endswith("/images/generations"), called_url

import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from app.api import admin
from app.db import RuntimeSetting
from app.services.errors import ServiceError
from test_api import backend, enroll
from test_languages import advertise


def test_checked_connection_persists_secrets_and_languages(backend, monkeypatch):
    client, app, gpu = backend
    class Probe:
        def __init__(self, settings):
            assert settings.colab_url == "https://new.trycloudflare.com"
            assert settings.colab_api_key.get_secret_value() == "new-private-key"
        async def health(self):
            return {"ok": True, "lang": "ar", "languages": ["ar", "en", "hi"]}
        async def close(self):
            pass
    monkeypatch.setattr(admin, "GPUClient", Probe)
    response = client.post("/api/admin/connect", json={"colab_url": "https://new.trycloudflare.com",
        "colab_api_key": "new-private-key", "groq_api_key": "groq-private-key"})
    assert response.status_code == 200 and response.json()["connected"]
    assert "private-key" not in response.text
    assert gpu.url == "https://new.trycloudflare.com" and gpu.key == "new-private-key"
    assert app.state.settings.llm_translit_enabled and not app.state.settings.local_only
    with app.state.db.session() as session:
        for name in ("colab", "groq"):
            assert b"private-key" not in session.get(RuntimeSetting, name).value


@pytest.mark.parametrize("failure,code", [(ServiceError(502, "Colab rejected the API key"), "colab_key_rejected"),
    (ServiceError(503, "unreachable"), "colab_unreachable"), (None, "notebook_update_required")])
def test_failed_connection_preserves_existing_settings(backend, monkeypatch, failure, code):
    client, app, gpu = backend
    before = gpu.url, gpu.key
    class Probe:
        def __init__(self, settings):
            pass
        async def health(self):
            if failure:
                raise failure
            return {"ok": True, "lang": "ar"}
        async def close(self):
            pass
    monkeypatch.setattr(admin, "GPUClient", Probe)
    response = client.post("/api/admin/connect", json={"colab_url": "https://bad.trycloudflare.com", "colab_api_key": "wrong"})
    assert response.status_code in {400, 409} and response.json()["code"] == code
    assert (gpu.url, gpu.key) == before
    with app.state.db.session() as session:
        assert session.get(RuntimeSetting, "colab") is None


def test_all_language_conversion_matches_preview_speech_and_cache(backend):
    client, app, gpu = backend
    advertise(gpu)
    enroll(client)
    settings = app.state.settings
    settings.groq_api_key = SecretStr("test-key")
    settings.llm_translit_enabled, settings.local_only = True, False
    calls = []
    def handle(request):
        body = json.loads(request.content)
        prompt = body["messages"][0]["content"]
        calls.append(prompt)
        result = "नमस्ते 123" if "Hindi" in prompt else "Hello 123"
        return httpx.Response(200, json={"choices": [{"message": {"content": result}}]})
    old = app.state.transliterator.client
    asyncio.run(old.aclose())
    app.state.transliterator.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    preview = client.post("/api/transliterate", json={"text": "namaste 123", "language": "hi"})
    assert preview.status_code == 200 and preview.json()["text"] == "नमस्ते 123"
    response = client.post("/api/tts", json={"text": "namaste 123", "language": "hi"})
    assert response.status_code == 200 and gpu.calls[-1][0] == "नमस्ते 123"
    assert len(calls) == 1  # Speaking reuses the exact preview conversion.
    other = client.post("/api/transliterate", json={"text": "namaste 123", "language": "en"})
    assert other.json()["text"] == "Hello 123" and len(calls) == 2
    native = client.post("/api/transliterate", json={"text": "नमस्ते 123", "language": "hi", "input_mode": "native"})
    assert native.json()["text"] == "नमस्ते 123" and len(calls) == 2


def test_conversion_failure_does_not_silently_speak_romanized_input(backend, monkeypatch):
    client, app, gpu = backend
    advertise(gpu)
    enroll(client)
    app.state.settings.groq_api_key = SecretStr("test-key")
    app.state.settings.llm_translit_enabled, app.state.settings.local_only = True, False
    async def unavailable(*args):
        return None
    monkeypatch.setattr(app.state.transliterator, "llm", unavailable)
    response = client.post("/api/tts", json={"text": "namaste", "language": "hi"})
    assert response.status_code == 503 and not gpu.calls


def test_preview_converts_without_colab_but_speech_still_requires_model(backend, monkeypatch):
    client, app, gpu = backend
    enroll(client)
    gpu.offline = True
    app.state.settings.groq_api_key = SecretStr("test-key")
    app.state.settings.llm_translit_enabled, app.state.settings.local_only = True, False
    calls = []
    async def llm(text, language="ur"):
        calls.append((text, language))
        return "नमस्ते"
    monkeypatch.setattr(app.state.transliterator, "llm", llm)
    response = client.post("/api/transliterate", json={"text": "namaste", "language": "hi"})
    assert response.status_code == 200 and response.json()["text"] == "नमस्ते"
    assert calls == [("namaste", "hi")]
    assert client.post("/api/tts", json={"text": "namaste", "language": "hi"}).status_code == 503
    assert not gpu.calls
    assert client.post("/api/transliterate", json={"text": "test", "language": "zz"}).status_code == 422
    health = client.get("/api/health").json()
    assert not health["colab"]["reachable"]
    assert "hi" in {item["code"] for item in health["preview_languages"]}

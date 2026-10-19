from urllib.parse import unquote

import pytest

from app.services.languages import Languages
from app.services.chunker import chunk_text
from test_api import backend, enroll


def advertise(gpu):
    async def health():
        return {"ok": True, "gpu": "fake", "lang": "ar", "languages": ["ar", "en", "hi", "ja"]}
    gpu.health = health


def test_catalog_persistence_offline_and_model_change(backend):
    client, app, gpu = backend
    assert client.get("/api/languages").json()["discovered"] is False
    advertise(gpu)
    catalog = client.get("/api/languages").json()
    assert {x["code"]: x["model_tag"] for x in catalog["items"]} == {"ur": "ar", "en": "en", "hi": "hi", "ja": "ja"}
    state = app.state
    restored = Languages(state.settings, state.db, state.cipher)
    assert restored.catalog() == catalog
    state.settings.model_version = "another-checkpoint"
    assert Languages(state.settings, state.db, state.cipher).catalog()["discovered"] is False
    restored.update({"lang": "ar"})
    assert restored.catalog()["items"] == [{"code": "ur", "model_tag": "ar", "name": "Urdu"}]


def test_languages_bypass_transliteration_and_cache_separately(backend, monkeypatch):
    client, app, gpu = backend
    enroll(client)
    advertise(gpu)
    received = []
    original = gpu.synthesize
    async def synthesize(text, latents, speed, language=None, temperature=None):
        received.append((text, language))
        return await original(text, latents, speed, language=language)
    gpu.synthesize = synthesize
    async def forbidden(*args, **kwargs):
        pytest.fail("Non-Urdu speech reached transliteration")
    monkeypatch.setattr(app.state.transliterator, "convert", forbidden)
    for language, text in [("en", "Hello, 123!"), ("hi", "नमस्ते 123!"), ("en", "123"), ("hi", "123")]:
        response = client.post("/api/tts", json={"text": text, "language": language})
        assert response.status_code == 200, response.text
        assert unquote(response.headers["x-spoken-text"]) == text
        assert response.headers["x-model-language"] == language
        assert received[-1] == (text, language)
    assert len(received) == 4
    gpu.offline = True
    assert client.post("/api/tts", json={"text": "123", "language": "hi"}).status_code == 200
    assert len(received) == 4
    assert client.post("/api/tts", json={"text": "Hello", "language": "zz"}).status_code == 422
    assert len(received) == 4


def test_cjk_long_text_chunks_preserve_characters():
    text = "こんにちは" * 90
    chunks = chunk_text(text, 180, language="ja")
    assert all(len(chunk) <= 180 for chunk in chunks)
    assert "".join(chunks) == text

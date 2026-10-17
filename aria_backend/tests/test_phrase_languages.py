import asyncio
import json
from urllib.parse import unquote

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.db import TextCache
from test_phase4 import bank, enroll
from test_languages import advertise


def enable(app, gpu):
    advertise(gpu)
    app.state.settings.groq_api_key = SecretStr("test-key")
    app.state.settings.llm_translit_enabled, app.state.settings.local_only = True, False


def test_phrase_cards_speech_and_audio_cache_use_selected_language(bank, monkeypatch):
    client, app, gpu = bank
    enable(app, gpu)
    enroll(client)
    batches = []
    async def translate(sources, language):
        batches.append((len(sources), language))
        return ["I need water." if language == "en" else "मुझे पानी चाहिए।" for source in sources]
    monkeypatch.setattr(app.state.phrase_translator, "batch", translate)
    cards = client.get("/api/phrases", params={"language": "en"})
    assert cards.status_code == 200, cards.text
    assert len(batches) == 2 and max(size for size, _ in batches) <= 30
    assert all(p["display_text"] == "I need water." and p["language"] == "en" for p in cards.json()["items"])
    assert not any(p["cached"] for p in cards.json()["items"])
    seen = []
    original = gpu.synthesize
    async def synthesize(text, latents, speed, language=None):
        seen.append((text, language))
        return await original(text, latents, speed, language=language)
    gpu.synthesize = synthesize
    for lang, expected in [("en", "I need water."), ("hi", "मुझे पानी चाहिए।"), ("ur", "مجھے پانی چاہیے۔")]:
        response = client.post("/api/phrases/needs-1/speak", json={"language": lang})
        assert response.status_code == 200, response.text
        assert response.headers["x-language"] == lang
        assert seen[-1][1] == ("ar" if lang == "ur" else lang)
        if lang != "ur":
            assert unquote(response.headers["x-spoken-text"]) == expected
    gpu.offline = True
    app.state.settings.local_only = True
    response = client.post("/api/phrases/needs-1/speak", json={"language": "en"})
    assert response.status_code == 200 and response.headers["x-audio-cache"] == "hit"
    assert len(seen) == 3
    assert next(p for p in client.get("/api/phrases", params={"language": "en"}).json()["items"] if p["id"] == "needs-1")["cached"]
    with app.state.db.session() as session:
        assert all(b"I need water" not in row.result for row in session.scalars(select(TextCache)))


def test_phrase_translation_failure_never_plays_source_language(bank, monkeypatch):
    client, app, gpu = bank
    enable(app, gpu)
    enroll(client)
    app.state.settings.local_only = True
    response = client.post("/api/phrases/needs-1/speak", json={"language": "en"})
    assert response.status_code == 503 and not gpu.calls
    assert client.get("/api/phrases", params={"language": "zz"}).status_code == 422


def test_batch_contract_rejects_truncated_or_wrong_count(bank):
    client, app, gpu = bank
    enable(app, gpu)
    async def run():
        service = app.state.phrase_translator
        previous = service.translator.client
        for choice in [{"message": {"content": '{"translations":[]}'}, "finish_reason": "stop"},
                       {"message": {"content": '{"translations":["Water"]}'}, "finish_reason": "length"}]:
            service.translator.client = httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"choices": [choice]})))
            try:
                with pytest.raises(Exception) as error:
                    await service.batch(["پانی"], "en")
                assert error.value.status == 503
            finally:
                await service.translator.client.aclose()
        service.translator.client = previous
    asyncio.run(run())


def test_inflight_translation_cannot_restore_deleted_private_text(bank, monkeypatch):
    client, app, gpu = bank
    enable(app, gpu)
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def batch(sources, language):
            entered.set()
            await release.wait()
            return ["Private phrase"]
        service = app.state.phrase_translator
        monkeypatch.setattr(service, "batch", batch)
        work = asyncio.create_task(service.translate([{"urdu": "ذاتی بات"}], "en"))
        await entered.wait()
        service.invalidate()
        app.state.voices.delete_all()
        release.set()
        with pytest.raises(Exception) as error:
            await work
        assert error.value.status == 409
        with app.state.db.session() as session:
            assert session.scalar(select(TextCache)) is None
    asyncio.run(run())

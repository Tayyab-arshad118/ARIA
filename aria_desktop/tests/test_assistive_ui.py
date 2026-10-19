import asyncio
import json

import flet_audio as fta
import httpx
import pytest

from test_desktop import app, ui, wav


@pytest.mark.parametrize("headers", [{}, {"X-ARIA-Watermark": "unavailable"},
    {"X-ARIA-Watermark": "research_unprotected", "X-ARIA-Watermark-Policy": "research_unprotected"}])
def test_client_rejects_unprotected_audio_even_when_wav_is_valid(headers):
    async def run():
        client = app.BackendClient(app.AppSettings(), httpx.MockTransport(lambda request: httpx.Response(200,
            content=wav(), headers={"content-type": "audio/wav", **headers})))
        try:
            with pytest.raises(app.AppError, match="protection"):
                await client.speak("hello", "aria_builtin", 1, "native", "en")
            with pytest.raises(app.AppError, match="protection"):
                await client.speak_phrase("needs-1", "aria_builtin", 1, "en")
        finally:
            await client.close()
    asyncio.run(run())


def test_builtin_entry_does_not_request_enrollment_and_emotion_is_forwarded(monkeypatch):
    monkeypatch.setattr(fta.Audio, "pause", lambda self: None)
    monkeypatch.setattr(fta.Audio, "release", lambda self: None)
    async def run():
        instance, page, backend = ui()
        backend.available = [{"id": "aria_builtin", "name": "ARIA Default Voice", "kind": "builtin", "available": True, "needs_reenrollment": False}]
        await instance.refresh()
        await instance.use_aria_voice()
        assert instance.screen == "compose" and instance.voice.value == "aria_builtin"
        assert not backend.enrolled and not instance.verify_button.visible
        instance.expression.value = "sad"
        instance.input.value = "Hello"
        await instance.speak_clicked()
        assert backend.spoken[-1][-1] == "sad"
        await instance.shutdown()
    asyncio.run(run())


def test_account_token_is_memory_only_and_sent_to_local_backend():
    async def handler(request):
        if request.url.path.endswith("login"):
            assert json.loads(request.content)["pin"] == "123456"
            return httpx.Response(200, json={"account_token": "session-secret", "actor_id": "patient"})
        assert request.headers["x-aria-account"] == "session-secret"
        return httpx.Response(200, json={"locked": True})
    async def run():
        client = app.BackendClient(app.AppSettings(), httpx.MockTransport(handler))
        await client.account("login", actor_id="patient", pin="123456")
        await client.account("logout")
        assert "x-aria-account" not in client.http.headers
        await client.close()
    asyncio.run(run())

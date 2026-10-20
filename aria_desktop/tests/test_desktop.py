import asyncio
import base64
from dataclasses import replace
import importlib.metadata
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.parse import quote
import wave

import flet as ft
import flet_audio as fta
import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import aria_app as app


def wav():
    output = io.BytesIO()
    with wave.open(output, "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(2)
        sound.setframerate(24000)
        sound.writeframes(b"\x00\x00" * 240)
    return output.getvalue()


class Page:
    """Use real pinned Flet controls, with only the native window/transport replaced."""
    def __init__(self):
        self.window = SimpleNamespace()
        self.platform = ft.PagePlatform.WINDOWS
        self.overlay, self.controls = [], []
        self.updates = 0

    def add(self, *controls):
        self.controls.extend(controls)

    def update(self):
        self.updates += 1

    def open(self, control):
        control.open = True
        self.overlay.append(control)

    def close(self, control):
        control.open = False


class Backend:
    def __init__(self):
        self.previews, self.spoken, self.enrolled = [], [], []
        self.closed = False
        self.available = [{"id": "voice-1", "name": "My voice", "needs_reenrollment": False}]
        self.fail = False
        self.bank = [{"id": "phrase-1", "roman": "mujhe pani chahiye", "urdu": "مجھے پانی چاہیے",
                      "category": "needs", "favorite": False, "last_used": None, "cached": False}]
        self.warmed, self.phrase_calls = [], []

    async def voices(self):
        return self.available

    async def health(self):
        return {"ok": True, "colab": {"reachable": True},
                "languages": {"default": "ur", "discovered": True,
                              "items": [{"code": "ur", "name": "Urdu"}, {"code": "en", "name": "English"}]}}

    async def preview(self, text):
        self.previews.append(text)
        return "مجھے پانی چاہیے"

    async def speak(self, *args):
        self.spoken.append(args)
        if self.fail:
            raise app.AppError("Test connection failure")
        return wav(), "مجھے پانی چاہیے"

    async def enroll(self, path, name, authorization_id=None):
        self.enrolled.append((path, name))
        self.available.append({"id": "new-voice", "name": name, "needs_reenrollment": False})
        return "new-voice"

    async def authorize_recording(self, path, source_type, basis, reference):
        return "patient-grant"

    async def close(self):
        self.closed = True

    async def predict(self, prefix):
        return ["pani", "madad"]

    async def phrases(self, voice_id, speed, language="ur", emotion="neutral"):
        return {"items": [dict(item) for item in self.bank], "warm_status": "ready"}

    async def warm_phrases(self, voice_id):
        self.warmed.append(voice_id)

    async def speak_phrase(self, identifier, voice_id, speed, language="ur", emotion="neutral"):
        self.phrase_calls.append((identifier, voice_id, speed, language, emotion))
        self.bank[0]["last_used"] = "2026-10-13"
        self.bank[0]["cached"] = True
        return wav(), self.bank[0]["urdu"]

    async def save_phrase(self, identifier, values):
        if identifier:
            next(p for p in self.bank if p["id"] == identifier).update(values)
        else:
            self.bank.append({"id": "new-phrase", **values, "favorite": False, "last_used": None, "cached": False})

    async def delete_phrase(self, identifier):
        self.bank = [p for p in self.bank if p["id"] != identifier]


def ui():
    page, backend = Page(), Backend()
    instance = app.AriaApp(page, app.AppSettings(preview_delay_ms=10), backend)
    return instance, page, backend


def test_pinned_dependencies_and_bundled_font():
    assert importlib.metadata.version("flet") == "0.28.3"
    assert importlib.metadata.version("flet-audio") == "0.1.0"
    assert (app.ASSETS / "fonts" / "NotoNastaliqUrdu.ttf").read_bytes()[:4] == b"\x00\x01\x00\x00"
    assert "SIL OPEN FONT LICENSE" in (app.ASSETS / "fonts" / "OFL.txt").read_text()


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://u:p@localhost", "https://example.com/path", "https://example.com?key=secret", "http://localhost:bad", "http://local host"])
def test_bad_backend_urls(url):
    with pytest.raises(ValueError):
        app.backend_origin(url)


def test_env_settings_do_not_expose_secrets(monkeypatch):
    monkeypatch.setenv("ARIA_BACKEND_URL", "http://192.168.1.4:8001/")
    monkeypatch.setenv("ARIA_KEY", "private-key")
    settings = app.AppSettings.from_env()
    assert settings.backend_url == "http://192.168.1.4:8001"
    assert "private-key" not in repr(settings)


def test_client_contracts_and_key_only_to_backend(tmp_path):
    calls = []
    async def handler(request):
        calls.append(request)
        assert request.url.host == "local.test"
        assert request.headers["authorization"] == "Bearer private-key"
        if request.url.path.endswith("transliterate"):
            return httpx.Response(200, json={"urdu": "مجھے پانی چاہیے"})
        if request.url.path.endswith("tts"):
            assert json.loads(request.content) == {"text": "mujhe pani chahiye", "voice_id": "voice-1", "speed": 1.2, "input_mode": "auto", "language": "ur", "emotion": "neutral"}
            return httpx.Response(200, content=wav(), headers={"content-type": "audio/wav", "X-Urdu-Text": quote("مجھے پانی چاہیے"), "X-ARIA-Watermark": "verified", "X-ARIA-Watermark-Policy": "required"})
        assert b'name="name"' in request.content and b'name="file"' in request.content
        return httpx.Response(201, json={"id": "new"})
    async def run():
        client = app.BackendClient(app.AppSettings(backend_url="https://local.test", api_key="private-key"), httpx.MockTransport(handler))
        assert await client.preview("hello") == "مجھے پانی چاہیے"
        raw, text = await client.speak("mujhe pani chahiye", "voice-1", 1.2, "auto")
        assert app.valid_wav(raw) and text == "مجھے پانی چاہیے"
        path = tmp_path / "voice.wav"
        path.write_bytes(wav())
        assert await client.enroll(path, "Test") == "new"
        await client.close()
    asyncio.run(run())
    assert len(calls) == 3


@pytest.mark.parametrize("status", [401, 404, 409, 413, 422, 429, 500, 502, 503, 307])
def test_errors_never_show_upstream_body(status):
    async def run():
        client = app.BackendClient(app.AppSettings(), httpx.MockTransport(
            lambda request: httpx.Response(status, text="private user text and credentials")))
        with pytest.raises(app.AppError) as error:
            await client.preview("hello")
        assert "private" not in str(error.value)
        await client.close()
    asyncio.run(run())


def test_bad_audio_and_response_size():
    async def run():
        client = app.BackendClient(app.AppSettings(max_audio_bytes=32), httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"x" * 33, headers={"content-type": "audio/wav"})))
        with pytest.raises(app.AppError, match="too large"):
            await client.speak("x", "voice", 1.0, "auto")
        await client.close()
        assert not app.valid_wav(wav()[:-2])
        assert not app.valid_wav(b"not a WAV")
    asyncio.run(run())


def test_controls_font_fallback_and_voice_reenrollment(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "ASSETS", tmp_path)
    async def run():
        instance, page, backend = ui()
        assert instance.font is None and page.fonts == {}
        assert instance.speak_button.disabled
        assert instance.preview.text_align == ft.TextAlign.RIGHT and instance.preview.rtl
        backend.available[0]["needs_reenrollment"] = True
        await instance.refresh()
        instance.input.value = "hello"
        instance.voice.value = "voice-1"
        instance.update_controls()
        assert instance.speak_button.disabled
        assert "new recording" in instance.voice_note.value
        await instance.shutdown()
    asyncio.run(run())


def test_debounce_and_blur_make_only_latest_preview():
    async def run():
        instance, page, backend = ui()
        instance.input.value = "m"
        await instance.text_changed()
        instance.input.value = "mujhe"
        await instance.text_changed()
        await asyncio.sleep(0.04)
        assert backend.previews == ["mujhe"]
        instance.input.value = "mujhe pani"
        await instance.text_blurred()
        await asyncio.sleep(0.01)
        assert backend.previews[-1] == "mujhe pani"
        instance.input.value = ""
        await instance.text_changed()
        assert instance.preview.value == "" and instance.preview.hint_text
        await instance.shutdown()
    asyncio.run(run())


def test_stale_preview_cannot_overwrite_new_input():
    async def run():
        instance, page, backend = ui()
        first_started, release = asyncio.Event(), asyncio.Event()
        async def slow_preview(text):
            if text == "old":
                first_started.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    # Simulate a server/client finishing even after cancellation.
                    await release.wait()
            return text
        backend.preview = slow_preview
        instance.input.value = "old"
        await instance.text_blurred()
        await first_started.wait()
        instance.input.value = "new"
        await instance.text_blurred()
        await asyncio.sleep(0.01)
        release.set()
        await asyncio.sleep(0.01)
        assert instance.preview.value == "new"
        await instance.shutdown()
    asyncio.run(run())


def test_urdu_mode_is_local_and_input_is_right_aligned():
    async def run():
        instance, page, backend = ui()
        instance.mode.value = "urdu"
        instance.input.value = "مجھے پانی چاہیے"
        await instance.mode_changed()
        await asyncio.sleep(0.01)
        assert not backend.previews and instance.preview.value == instance.input.value
        assert instance.input.rtl
        await instance.shutdown()
    asyncio.run(run())


def test_playback_gets_new_control_and_stop_releases_it(monkeypatch):
    released = []
    monkeypatch.setattr(fta.Audio, "pause", lambda self: None)
    monkeypatch.setattr(fta.Audio, "release", lambda self: released.append(self))
    async def run():
        instance, page, backend = ui()
        await instance.refresh()
        instance.input.value = "mujhe pani chahiye"
        await instance.speak_clicked()
        first = instance.audio
        assert isinstance(first, fta.Audio) and first.autoplay and base64.b64decode(first.src_base64) == wav()
        await instance.speak_clicked()
        second = instance.audio
        assert second is not first and first not in page.overlay and first in released
        assert len([control for control in page.overlay if isinstance(control, fta.Audio)]) == 1
        await instance.stop_clicked()
        assert instance.audio is None and second in released and instance.stop_button.disabled
        await instance.shutdown()
    asyncio.run(run())


def test_synthesis_error_restores_controls():
    async def run():
        instance, page, backend = ui()
        await instance.refresh()
        instance.input.value = "hello"
        backend.fail = True
        await instance.speak_clicked()
        assert not instance.busy and not instance.speak_button.disabled
        assert instance.audio is None and "failure" in instance.status.value
        await instance.shutdown()
    asyncio.run(run())


def test_enrollment_file_cancel_and_success(tmp_path):
    async def run():
        instance, page, backend = ui()
        await instance.open_enrollment()
        await instance.file_selected(SimpleNamespace(files=None))
        assert instance.selected_file is None
        path = tmp_path / "voice.wav"
        path.write_bytes(wav())
        await instance.file_selected(SimpleNamespace(files=[SimpleNamespace(path=str(path), name="voice.wav", size=path.stat().st_size)]))
        assert instance.enroll_name.value == "voice"
        instance.enroll_confirm.value = True
        instance.enroll_reference.value = "Patient test authorization"
        await instance.save_voice()
        assert backend.enrolled == [(path, "voice")]
        assert instance.voice.value == "new-voice" and not instance.dialog.open
        await instance.shutdown()
    asyncio.run(run())


def test_settings_replace_client_and_remove_key_from_control(monkeypatch):
    async def run():
        instance, page, old_client = ui()
        new_client = Backend()
        settings_received = []
        def factory(settings):
            settings_received.append(settings)
            return new_client
        monkeypatch.setattr(app, "BackendClient", factory)
        await instance.open_settings()
        instance.url_field.value = "http://192.168.1.5:8001"
        instance.key_field.value = "new-key"
        await instance.save_settings()
        assert old_client.closed
        assert settings_received[0].backend_url == "http://192.168.1.5:8001"
        assert settings_received[0].api_key == "new-key"
        assert instance.key_field.value == "" and not instance.dialog.open
        await instance.shutdown()
    asyncio.run(run())


def test_invalid_replacement_clears_previous_file(tmp_path):
    async def run():
        instance, page, backend = ui()
        await instance.open_enrollment()
        instance.selected_file = tmp_path / "old.wav"
        await instance.file_selected(SimpleNamespace(files=[SimpleNamespace(path="content://cloud/recording", name="new.wav", size=100)]))
        assert instance.selected_file is None
        assert "Downloads" in instance.enroll_error.value
        await instance.shutdown()
    asyncio.run(run())


def test_edit_during_synthesis_keeps_new_preview(monkeypatch):
    monkeypatch.setattr(fta.Audio, "pause", lambda self: None)
    monkeypatch.setattr(fta.Audio, "release", lambda self: None)
    async def run():
        instance, page, backend = ui()
        await instance.refresh()
        started, release = asyncio.Event(), asyncio.Event()
        async def slow_speech(*args):
            started.set()
            await release.wait()
            return wav(), "پرانا متن"
        backend.speak = slow_speech
        instance.input.value = "old input"
        speaking = asyncio.create_task(instance.speak_clicked())
        await started.wait()
        instance.input.value = "new input"
        await instance.text_blurred()
        await asyncio.sleep(0.01)
        release.set()
        await speaking
        assert instance.preview.value == "مجھے پانی چاہیے"
        assert instance.input.value == "new input"
        await instance.shutdown()
    asyncio.run(run())


def test_audio_load_failure_restores_stop_state(monkeypatch):
    monkeypatch.setattr(fta.Audio, "pause", lambda self: None)
    monkeypatch.setattr(fta.Audio, "release", lambda self: None)
    async def run():
        instance, page, backend = ui()
        instance.settings = replace(instance.settings, audio_load_timeout=0.01)
        instance.play_audio(wav())
        await asyncio.sleep(0.04)
        assert instance.audio is None and instance.stop_button.disabled
        assert "did not start" in instance.status.value
        await instance.shutdown()
    asyncio.run(run())


def test_build_config_excludes_secrets_and_uses_single_entrypoint():
    import toml
    config = toml.loads((app.ROOT / "pyproject.toml").read_text())
    assert config["tool"]["flet"]["app"]["path"] == "."
    assert config["tool"]["flet"]["app"]["module"] == "aria_app"
    assert {".env", ".env.*", ".venv", "tests"} <= set(config["tool"]["flet"]["app"]["exclude"])
    assert "flet==0.28.3" in config["project"]["dependencies"]
    assert "flet-audio==0.1.0" in config["project"]["dependencies"]


@pytest.mark.parametrize("prefix,word,expected", [("mujhe pa", "pani", "mujhe pani "),
    ("mujhe ", "pani", "mujhe pani "), ("", "mujhe", "mujhe ")])
def test_suggestion_insertion(prefix, word, expected):
    assert app.insert_suggestion(prefix, word) == expected


def test_prediction_chips_and_stale_results():
    async def run():
        instance, page, backend = ui()
        instance.settings = replace(instance.settings, predict_delay_ms=1)
        instance.input.value = "mujhe pa"
        await instance.text_changed()
        await asyncio.wait_for(instance.predict_task, 2)
        assert len(instance.suggestion_row.controls) == 2
        await instance.suggestion_row.controls[0].on_click(None)
        assert instance.input.value == "mujhe pani "
        instance.mode.value = "urdu"
        await instance.mode_changed()
        assert instance.suggestion_row.controls == []
        await instance.shutdown()
    asyncio.run(run())


def test_phrase_grid_favorites_edit_and_one_tap_playback(monkeypatch):
    monkeypatch.setattr(fta.Audio, "pause", lambda self: None)
    monkeypatch.setattr(fta.Audio, "release", lambda self: None)
    async def run():
        instance, page, backend = ui()
        await instance.refresh()
        assert backend.warmed == ["voice-1"] and len(instance.phrase_grid.controls) == 1
        await instance.toggle_favorite(instance.phrases[0])
        assert instance.phrases[0]["favorite"]
        instance.phrase_filter.value = "favorites"
        await instance.phrase_filter_changed()
        assert len(instance.phrase_controls) == 3
        await instance.phrase_controls[0][0].on_click(None)
        assert backend.phrase_calls == [("phrase-1", "voice-1", 1.0, "ur", "neutral")]
        assert instance.audio is not None
        assert instance.phrases[0]["last_used"]
        await instance.open_phrase_editor(instance.phrases[0])
        instance.phrase_roman.value = "mujhe madad chahiye"
        instance.phrase_urdu.value = "مجھے مدد چاہیے"
        await instance.save_phrase_editor()
        assert backend.bank[0]["roman"] == "mujhe madad chahiye"
        await instance.open_phrase_editor(instance.phrases[0])
        await instance.delete_phrase_editor()
        assert not backend.bank
        await instance.shutdown()
    asyncio.run(run())


def test_phrase_http_contracts():
    calls = []
    async def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("predict"):
            assert request.url.params["prefix"] == "mujhe "
            return httpx.Response(200, json={"suggestions": ["pani"]})
        if request.url.path.endswith("warm"):
            return httpx.Response(202, json={"queued": True})
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"items": []})
    async def run():
        client = app.BackendClient(app.AppSettings(), httpx.MockTransport(handler))
        assert await client.predict("mujhe ") == ["pani"]
        assert (await client.warm_phrases("voice"))["queued"]
        await client.phrases("voice", 1.0)
        await client.save_phrase("phrase", {"favorite": True})
        await client.delete_phrase("phrase")
        await client.close()
    asyncio.run(run())
    assert ("PATCH", "/api/phrases/phrase") in calls and ("DELETE", "/api/phrases/phrase") in calls


def test_strict_session_client_headers_and_clear_on_close(tmp_path):
    async def handler(request):
        if request.url.path.endswith("verify"):
            return httpx.Response(200, json={"verified": True, "session_token": "private-session",
                                             "voice_id": "voice-1", "expires_in": 300})
        assert request.headers["x-aria-session"] == "private-session"
        assert request.headers["authorization"] == "Bearer app-key"
        return httpx.Response(200, content=wav(), headers={"content-type": "audio/wav", "X-ARIA-Watermark": "verified", "X-ARIA-Watermark-Policy": "required"})
    async def run():
        client = app.BackendClient(app.AppSettings(api_key="app-key"), httpx.MockTransport(handler))
        path = tmp_path / "challenge.wav"
        path.write_bytes(wav())
        assert await client.verify("challenge-id", path) == 300
        assert client.session_valid("voice-1") and not client.session_valid("other")
        await client.speak("pani", "voice-1", 1.0, "auto")
        await client.speak_phrase("needs-1", "voice-1", 1.0)
        await client.close()
        assert not client.sessions
    asyncio.run(run())


def test_verification_dialog_unlocks_strict_controls(tmp_path):
    class StrictBackend(Backend):
        verified = False
        async def health(self):
            return {"colab": {"reachable": True}, "workflow_mode": "research", "security_mode": "strict", "emotion_enabled": True}
        def session_valid(self, voice_id):
            return self.verified and voice_id == "voice-1"
        async def challenge(self, voice_id):
            return {"challenge_id": "one", "voice_id": voice_id, "phrase": "براہ کرم یہ الفاظ کہیں", "expires_in": 60}
        async def verify(self, identifier, path):
            self.verified = True
            return 300
        async def add_emotion(self, voice_id, emotion, path, authorization_id=None):
            self.saved_emotion = (voice_id, emotion)
    async def run():
        backend, page = StrictBackend(), Page()
        instance = app.AriaApp(page, app.AppSettings(), backend)
        await instance.refresh()
        instance.input.value = "pani"
        instance.update_controls()
        assert instance.speak_button.disabled and instance.verify_button.visible
        assert instance.emotion_button.disabled
        await instance.open_verification()
        path = tmp_path / "voice.wav"
        path.write_bytes(wav())
        await instance.file_selected(SimpleNamespace(files=[SimpleNamespace(path=str(path), name="voice.wav", size=path.stat().st_size)]))
        await instance.submit_verification()
        assert not instance.speak_button.disabled and not instance.emotion_button.disabled
        await instance.open_emotion()
        instance.selected_file = path
        instance.enroll_confirm.value = True
        instance.enroll_reference.value = "Authorized test style"
        await instance.save_emotion()
        assert backend.saved_emotion == ("voice-1", "happy")
        await instance.shutdown()
    asyncio.run(run())


def test_language_selection_preview_and_speech(monkeypatch):
    monkeypatch.setattr(fta.Audio, "pause", lambda self: None)
    monkeypatch.setattr(fta.Audio, "release", lambda self: None)
    async def run():
        instance, page, backend = ui()
        async def health():
            return {"colab": {"reachable": True}, "languages": {"default": "ur", "discovered": True,
                "items": [{"code": "ur", "name": "Urdu"}, {"code": "en", "name": "English"}]},
                "reference_limits": {"max_source_seconds": 1800, "max_upload_bytes": 268435456, "window_seconds": 30}}
        backend.health = health
        await instance.refresh()
        assert [item.key for item in instance.language.options] == ["en", "ur"]
        assert not instance.language_note.visible
        instance.language.value = "en"
        instance.input.value = "Hello, 123!"
        await instance.language_changed()
        await instance.preview_task
        assert instance.preview.value == "Hello, 123!" and not backend.previews
        assert instance.mode.visible and not instance.preview.rtl
        assert "30 minutes" in instance.reference_help()
        await instance.speak_clicked()
        assert backend.spoken[-1][-2:] == ("en", "neutral")
        await instance.shutdown()
    asyncio.run(run())


def test_redesign_navigation_theme_and_search_preserve_composer():
    async def run():
        instance, page, backend = ui()
        await instance.refresh()
        assert page.theme_mode == ft.ThemeMode.LIGHT
        instance.input.value = "me thk hu"
        await instance.change_view(SimpleNamespace(data="1"))
        assert instance.library_view.visible and not instance.compose_view.visible
        instance.phrase_search.value = "not present"
        instance.render_phrase_grid()
        assert not instance.phrase_controls
        instance.phrase_search.value = "pani"
        instance.render_phrase_grid()
        assert len(instance.phrase_controls) == 3
        await instance.toggle_theme()
        assert page.theme_mode == ft.ThemeMode.DARK
        await instance.change_view(SimpleNamespace(data="0"))
        assert instance.input.value == "me thk hu" and instance.compose_view.visible
        await instance.shutdown()
    asyncio.run(run())

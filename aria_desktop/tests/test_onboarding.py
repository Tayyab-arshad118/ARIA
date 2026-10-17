import asyncio

import pytest

from test_desktop import ui, app


def test_colab_output_labels_are_accepted():
    assert app.parse_colab_outputs("COLAB_URL=https://abc.trycloudflare.com\nCopy URL into the local backend.",
        "Copy to local .env as COLAB_API_KEY (shown once): secret-key") == ("https://abc.trycloudflare.com", "secret-key")
    with pytest.raises(ValueError):
        app.parse_colab_outputs("http://127.0.0.1:8001", "secret-key")
    with pytest.raises(ValueError):
        app.parse_colab_outputs("https://abc.trycloudflare.com", "")


def test_welcome_connect_voice_and_speak_screens():
    async def run():
        instance, page, backend = ui()
        assert instance.screen == "welcome" and not instance.compose_view.visible
        await instance.get_started()
        assert instance.screen == "connection"
        captured = []
        async def connect(*args):
            captured.append(args)
            return {"connected": True}
        backend.connect_colab = connect
        instance.colab_url_field.value = "COLAB_URL=https://abc.trycloudflare.com"
        instance.colab_key_field.value = "COLAB_API_KEY=secret-key"
        instance.groq_field.value = "groq-key"
        await instance.save_colab()
        assert captured == [("https://abc.trycloudflare.com", "secret-key", "groq-key")]
        assert instance.screen == "voices" and instance.voices_view.visible
        assert instance.colab_key_field.value == instance.groq_field.value == ""
        await instance.continue_speaking()
        assert instance.screen == "compose" and not instance.voices_view.visible
        await instance.open_connection()
        assert instance.screen == "connection" and not instance.compose_view.visible
        await instance.shutdown()
    asyncio.run(run())


def test_multilingual_preview_uses_selected_language_and_native_override():
    async def run():
        instance, page, backend = ui()
        calls = []
        async def preview(*args):
            calls.append(args)
            return "नमस्ते"
        backend.preview = preview
        instance.api_translit_enabled = True
        instance.language_names["hi"] = "Hindi"
        instance.language.value = "hi"
        instance.input.value = "namaste"
        await instance.language_changed()
        await instance.preview_task
        assert calls == [("namaste", "hi", "auto")] and instance.preview.value == "नमस्ते"
        instance.mode.value = "native"
        await instance.mode_changed()
        await instance.preview_task
        assert instance.preview.value == "namaste" and len(calls) == 1
        await instance.shutdown()
    asyncio.run(run())


def test_phrase_language_loading_and_stable_controls(monkeypatch):
    import flet_audio as fta
    monkeypatch.setattr(fta.Audio, "pause", lambda self: None)
    monkeypatch.setattr(fta.Audio, "release", lambda self: None)
    async def run():
        instance, page, backend = ui()
        await instance.refresh()
        calls = []
        async def phrases(voice, speed, language="ur"):
            calls.append(language)
            return {"items": [{**backend.bank[0], "display_text": "I need water", "language": language}]}
        backend.phrases = phrases
        instance.language.value = "en"
        instance.language_names["en"] = "English"
        instance.show_screen("library")
        await instance.language_changed()
        assert calls == ["en"] and instance.phrases[0]["display_text"] == "I need water"
        first_button = instance.phrase_controls[0][0]
        await instance.load_phrase_bank()
        assert instance.phrase_controls[0][0] is first_button
        await instance.play_phrase("phrase-1")
        assert backend.phrase_calls[-1][-1] == "en"
        assert instance.home_navigation.visible and instance.language_bar.visible
        await instance.shutdown()
    asyncio.run(run())


def test_language_chips_preview_and_native_pill_preserve_handlers():
    async def run():
        instance, page, backend = ui()
        await instance.refresh()
        instance.input.value = "Hello"
        await instance.language_pills.controls[0].on_click(None)
        await instance.preview_task
        assert instance.language.value == "en" and instance.preview.value == "Hello"
        await instance.native_mode()
        await instance.preview_task
        assert instance.mode.value == "native"
        assert instance.char_count.value == "5 / 2000"
        assert instance.screen == "welcome" and not instance.status_pills.visible
        instance.server_ready = False
        instance.show_screen("compose")
        assert instance.error_banner.visible
        assert instance.banner_title.value == "Voice server is offline"
        await instance.shutdown()
    asyncio.run(run())

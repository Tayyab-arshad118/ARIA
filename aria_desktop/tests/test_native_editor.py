import asyncio

import flet_audio as fta
import pytest

from test_desktop import app, ui


def test_native_edit_never_rewrites_roman_and_is_spoken_verbatim(monkeypatch):
    monkeypatch.setattr(fta.Audio, "pause", lambda self: None)
    monkeypatch.setattr(fta.Audio, "release", lambda self: None)
    async def run():
        instance, page, backend = ui()
        await instance.refresh()
        instance.language.value = "hi"
        instance.language_names["hi"] = "Hindi"
        instance.input.value = "namaste"
        await instance.language_changed()
        await instance.preview_task
        instance.preview.value = "नमस्ते दोस्त"
        await instance.native_changed()
        await instance.text_blurred()
        assert instance.input.value == "namaste"
        assert instance.preview.value == "नमस्ते दोस्त" and instance.preview_task is None
        await instance.speak_clicked()
        assert backend.spoken[-1] == ("नमस्ते दोस्त", "voice-1", 1.0, "native", "hi")
        assert instance.input.value == "namaste"
        await instance.shutdown()
    asyncio.run(run())


def test_native_edit_wins_over_inflight_conversion():
    async def run():
        instance, page, backend = ui()
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow(text):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            return "outdated conversion"
        backend.preview = slow
        instance.input.value = "hello"
        await instance.text_blurred()
        task = instance.preview_task
        await entered.wait()
        instance.preview.value = "میرا متن"
        await instance.native_changed()
        release.set()
        await task
        assert instance.preview.value == "میرا متن" and instance.input.value == "hello"
        await instance.shutdown()
    asyncio.run(run())


def test_blur_does_not_resubmit_completed_conversion():
    async def run():
        instance, page, backend = ui()
        instance.input.value = "mujhe pani"
        await instance.text_blurred()
        await instance.preview_task
        for _ in range(3):
            await instance.text_blurred()
        await asyncio.sleep(0)
        assert backend.previews == ["mujhe pani"]
        assert instance.input.value == "mujhe pani"
        await instance.shutdown()
    asyncio.run(run())


def test_double_tap_and_stale_suggestions_do_not_duplicate_words():
    async def run():
        instance, page, backend = ui()
        instance.input.value = "mujhe pa"
        await instance.text_changed()
        await instance.predict_task
        button = instance.suggestion_row.controls[0]
        assert button.content.color == app.INK
        await button.on_click(None)
        await button.on_click(None)
        assert instance.input.value == "mujhe pani "
        instance.input.value = "changed"
        await button.on_click(None)
        assert instance.input.value == "changed"
        await instance.shutdown()
    asyncio.run(run())


@pytest.mark.parametrize("code,name,script,rtl", [("hi", "Hindi", "हिन्दी", False),
    ("ar", "Arabic", "العربية", True), ("ja", "Japanese", "日本語", False)])
def test_language_fields_keep_independent_native_script(code, name, script, rtl):
    async def run():
        instance, page, backend = ui()
        instance.api_translit_enabled = True
        instance.language_names[code] = name
        async def preview(text, language="ur", mode="auto"):
            assert language == code
            return script
        backend.preview = preview
        instance.language.value = code
        instance.input.value = "roman input"
        await instance.language_changed()
        await instance.preview_task
        assert instance.preview.value == script and instance.input.value == "roman input"
        assert instance.preview.rtl == rtl and script in instance.preview_title.value
        assert name in instance.source_title.value
        await instance.shutdown()
    asyncio.run(run())

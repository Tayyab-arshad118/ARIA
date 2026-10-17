import time
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Request, Response
from pydantic import Field

from .text import TextInput, validate_text
from ..services.synthesis import render
from ..services.urdu_normalizer import normalize_urdu
from ..services.languages import preserve_text

router = APIRouter()


class TTSInput(TextInput):
    voice_id: str = Field("default", min_length=1, max_length=80)
    speed: float | None = Field(None, ge=0.5, le=2, allow_inf_nan=False)
    input_mode: Literal["auto", "roman", "urdu", "native"] = "auto"
    language: str = Field("ur", min_length=2, max_length=16, pattern=r"^[a-z]+(?:-[a-z]+)?$")


@router.post("/tts")
async def tts(body: TTSInput, request: Request):
    started = time.perf_counter()
    state = request.app.state
    validate_text(body.text, state.settings)
    # Serializing voice operations prevents deletion from racing with a cache write or enrollment.
    async with state.data_lock:
        voice_id, latents = state.voices.get(body.voice_id)
        state.liveness.authorize(voice_id, request.headers.get("x-aria-session"))
        tag = await state.languages.resolve(body.language, state.gpu)
        result = await state.transliterator.convert_language(body.text, body.language, body.input_mode)
        urdu = normalize_urdu(result["text"]) if body.language == "ur" else preserve_text(result["text"])
        validate_text(urdu, state.settings)
        speed = body.speed if body.speed is not None else state.settings.default_speed
        key = state.cache.key(voice_id, urdu, speed, body.language)
        audio = state.cache.get(key)
        if audio is None:
            audio = await render(state, urdu, latents, speed, voice_id, body.language)
            state.cache.put(key, voice_id, audio)
        audio, watermark_status = await state.watermarker.apply(audio)
        state.liveness.authorize(voice_id, request.headers.get("x-aria-session"))
        if body.language == "ur":
            await state.predictor.record(body.text, voice_id)
    return Response(audio, media_type="audio/wav", headers={
        "X-Urdu-Text": quote(urdu, safe=""), "X-Latency-Ms": f"{(time.perf_counter() - started) * 1000:.1f}",
        "X-Spoken-Text": quote(urdu, safe=""), "X-Language": body.language, "X-Model-Language": tag,
        "Cache-Control": "no-store",
        "X-ARIA-Generated": "true", "X-ARIA-Watermark": watermark_status,
        "X-ARIA-Emotion": state.emotions.select(voice_id, urdu, latents, speed)[3] if state.settings.emotion_enabled else "disabled",
    })

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
    emotion: Literal["neutral", "happy", "sad", "angry", "calm", "auto"] = "neutral"


@router.post("/tts")
async def tts(body: TTSInput, request: Request):
    started = time.perf_counter()
    state = request.app.state
    validate_text(body.text, state.settings)
    # Serializing voice operations prevents deletion from racing with a cache write or enrollment.
    async with state.data_lock:
        if body.voice_id != "aria_builtin":
            state.access.actor(request, "speak")
        voice_id, latents = await state.voices.resolve(body.voice_id)
        state.liveness.authorize(voice_id, request.headers.get("x-aria-session"))
        tag = await state.languages.resolve(body.language, state.gpu)
        result = await state.transliterator.convert_language(body.text, body.language, body.input_mode)
        # Native writing must not undergo Urdu letter substitutions or number rewriting.
        urdu = body.text if body.input_mode in {"native", "urdu"} else preserve_text(result["text"])
        validate_text(urdu, state.settings)
        speed = body.speed if body.speed is not None else state.settings.default_speed
        expression = state.emotions.describe(voice_id, urdu, latents, speed, body.emotion)
        key = state.cache.key(voice_id, urdu, speed, body.language, body.emotion)
        audio = state.cache.get(key)
        if audio is None:
            audio = await render(state, urdu, latents, speed, voice_id, body.language, body.emotion)
            audio, watermark_status = await state.watermarker.finalize(audio)
            state.cache.put(key, voice_id, audio)
        else:
            audio, watermark_status = await state.watermarker.finalize(audio, cached=True)
        state.liveness.authorize(voice_id, request.headers.get("x-aria-session"))
        if body.language == "ur":
            await state.predictor.record(body.text, voice_id)
        if body.voice_id != "aria_builtin":
            state.access.actor(request, "speak")
    return Response(audio, media_type="audio/wav", headers={
        "X-Urdu-Text": quote(urdu, safe=""), "X-Latency-Ms": f"{(time.perf_counter() - started) * 1000:.1f}",
        "X-Spoken-Text": quote(urdu, safe=""), "X-Language": body.language, "X-Model-Language": tag,
        "Cache-Control": "no-store",
        "X-ARIA-Generated": "true", "X-ARIA-Watermark": watermark_status,
        "X-ARIA-Watermark-Policy": state.settings.watermark_policy,
        "X-ARIA-Model-Fingerprint": state.identity.fingerprint or state.settings.model_version,
        "X-ARIA-Protection-Version": state.settings.watermark_version,
        "X-ARIA-Emotion": expression["effective"], "X-ARIA-Emotion-Requested": body.emotion,
        "X-ARIA-Emotion-Method": expression["method"],
    })

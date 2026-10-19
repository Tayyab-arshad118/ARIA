import re
import time
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..services.errors import ServiceError
from ..services.synthesis import render
from ..services.urdu_normalizer import normalize_urdu
from ..services.languages import preserve_text

router = APIRouter()
Category = Literal["needs", "medical", "family", "greetings", "custom"]


class PhraseFields(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("roman", "urdu", check_fields=False)
    @classmethod
    def meaningful(cls, value, info):
        if value is None or not value.strip():
            raise ValueError("Phrase text must not be blank")
        value = value.strip()
        if info.field_name == "roman" and (not re.search(r"[a-z]", value, re.I)
                or not re.fullmatch(r"[\x20-\x7e\n\t]+", value)):
            raise ValueError("Use Roman Urdu in the Roman field")
        if info.field_name == "urdu" and (not re.search(r"[\u0620-\u06ff]", value) or re.search(r"[a-z]", value, re.I)):
            raise ValueError("Use Urdu script in the Urdu field")
        return value


class PhraseCreate(PhraseFields):
    roman: str = Field(min_length=1, max_length=180)
    urdu: str = Field(min_length=1, max_length=180)
    category: Category = "custom"


class PhraseUpdate(PhraseFields):
    roman: str | None = Field(None, min_length=1, max_length=180)
    urdu: str | None = Field(None, min_length=1, max_length=180)
    category: Category | None = None
    favorite: bool | None = None


class VoiceChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    voice_id: str = Field("default", min_length=1, max_length=80)
    speed: float | None = Field(None, ge=0.5, le=2)
    language: str = Field("ur", min_length=2, max_length=16, pattern=r"^[a-z]+(?:-[a-z]+)?$")
    emotion: Literal["neutral", "happy", "sad", "angry", "calm", "auto"] = "neutral"


@router.get("/phrases")
async def list_phrases(request: Request, voice_id: str = Query("default", max_length=80),
                       speed: float | None = Query(None, ge=0.5, le=2), category: Category | None = None,
                       favorites: bool = False, recent: bool = False,
                       language: str = Query("ur", min_length=2, max_length=16, pattern=r"^[a-z]+(?:-[a-z]+)?$"),
                       emotion: Literal["neutral", "happy", "sad", "angry", "calm", "auto"] = "neutral"):
    state = request.app.state
    state.access.actor(request, "speak")
    async with state.data_lock:
        state.access.actor(request, "speak")
        try:
            if voice_id == "aria_builtin":
                resolved = voice_id
            else:
                resolved, _ = state.voices.get(voice_id)
        except ServiceError as error:
            if voice_id != "default" or error.status not in {404, 409}:
                raise
            resolved = None
        items = state.phrases.list(resolved, speed, category, favorites, recent)
    await state.languages.resolve(language, state.gpu)
    items = await state.phrase_translator.translate(items, language)
    keys = state.phrases.cached_keys(resolved) if resolved else set()
    actual_speed = state.settings.default_speed if speed is None else speed
    for item in items:
        item["cached"] = bool(resolved and state.phrases.key(item, resolved, actual_speed, language, emotion) in keys)
    return {"items": items, "voice_id": resolved, "ready": sum(p["cached"] for p in items),
            "total": len(items), "language": language, "warm_status": state.warmer.status if language == "ur" else "on_demand"}


@router.post("/phrases/warm", status_code=202)
async def warm_phrases(body: VoiceChoice, request: Request):
    state = request.app.state
    state.access.actor(request, "speak")
    if body.language != "ur":
        await state.languages.resolve(body.language, state.gpu)
        return {"queued": False, "warm_status": "on_demand", "language": body.language}
    async with state.data_lock:
        state.access.actor(request, "speak")
        identifier, _ = await state.voices.resolve(body.voice_id)
        state.warmer.notify(identifier)
    return {"queued": state.settings.phrase_prewarm_enabled, "voice_id": identifier,
            "speed": state.settings.default_speed, "warm_status": state.warmer.status}


@router.post("/phrases", status_code=201)
async def create_phrase(body: PhraseCreate, request: Request):
    state = request.app.state
    state.access.actor(request, "manage")
    async with state.data_lock:
        state.access.actor(request, "manage")
        phrase = state.phrases.create(body.model_dump())
        await state.predictor.rebuild()
        state.warmer.notify(invalidate=True)
        return phrase


@router.patch("/phrases/{phrase_id}")
async def update_phrase(phrase_id: str, body: PhraseUpdate, request: Request):
    state = request.app.state
    state.access.actor(request, "manage")
    changes = body.model_dump(exclude_unset=True)
    if not changes or any(value is None for value in changes.values()):
        raise ServiceError(422, "Provide at least one non-null phrase field")
    async with state.data_lock:
        state.access.actor(request, "manage")
        result = state.phrases.update(phrase_id, changes)
        if any(key in changes for key in ("roman", "urdu", "category")):
            state.phrase_translator.invalidate()
        await state.predictor.rebuild()
        state.warmer.notify(invalidate=any(key in changes for key in ("roman", "urdu", "category")))
        return result


@router.delete("/phrases/{phrase_id}", status_code=204)
async def delete_phrase(phrase_id: str, request: Request):
    state = request.app.state
    state.access.actor(request, "manage")
    async with state.data_lock:
        state.access.actor(request, "manage")
        state.phrases.delete(phrase_id)
        state.phrase_translator.invalidate()
        await state.predictor.rebuild()
        state.warmer.notify(invalidate=True)


@router.post("/phrases/{phrase_id}/speak")
async def speak_phrase(phrase_id: str, body: VoiceChoice, request: Request):
    state = request.app.state
    state.access.actor(request, "speak")
    started = time.perf_counter()
    async with state.data_lock:
        state.access.actor(request, "speak")
        phrase = state.phrases.get(phrase_id)
        voice_id, latents = await state.voices.resolve(body.voice_id)
        state.liveness.authorize(voice_id, request.headers.get("x-aria-session"))
        speed = state.settings.default_speed if body.speed is None else body.speed
        tag = await state.languages.resolve(body.language, state.gpu)
        phrase = (await state.phrase_translator.translate([phrase], body.language))[0]
        urdu = preserve_text(phrase["display_text"])
        expression = state.emotions.describe(voice_id, urdu, latents, speed, body.emotion)
        key = state.phrases.key(phrase, voice_id, speed, body.language, body.emotion)
        audio = state.phrases.audio(key)
        hit = audio is not None
        if audio is None:
            audio = await render(state, urdu, latents, speed, voice_id, body.language, body.emotion)
            audio, watermark_status = await state.watermarker.finalize(audio)
            state.phrases.put_audio(phrase, voice_id, speed, audio, body.language, body.emotion)
        else:
            audio, watermark_status = await state.watermarker.finalize(audio, cached=True)
        state.liveness.authorize(voice_id, request.headers.get("x-aria-session"))
        state.phrases.mark_used(phrase_id)
        state.access.actor(request, "speak")
        if body.language == "ur":
            await state.predictor.record(phrase["roman"], voice_id)
    return Response(audio, media_type="audio/wav", headers={"X-Urdu-Text": quote(urdu, safe=""),
        "X-Spoken-Text": quote(urdu, safe=""), "X-Language": body.language, "X-Model-Language": tag,
        "X-Latency-Ms": f"{(time.perf_counter() - started) * 1000:.1f}", "X-Audio-Cache": "hit" if hit else "miss",
        "Cache-Control": "no-store", "X-ARIA-Generated": "true", "X-ARIA-Watermark": watermark_status,
        "X-ARIA-Watermark-Policy": state.settings.watermark_policy,
        "X-ARIA-Model-Fingerprint": state.identity.fingerprint or state.settings.model_version,
        "X-ARIA-Protection-Version": state.settings.watermark_version,
        "X-ARIA-Emotion": expression["effective"], "X-ARIA-Emotion-Requested": body.emotion,
        "X-ARIA-Emotion-Method": expression["method"]})

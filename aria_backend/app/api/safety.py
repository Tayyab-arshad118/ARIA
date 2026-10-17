from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import UploadFile

from ..services.errors import ServiceError

router = APIRouter()
EmotionTag = Literal["neutral", "happy", "sad", "calm", "angry"]


async def wav_upload(request, max_fields=0):
    limit = request.app.state.settings.max_upload_bytes
    async with request.form(max_files=1, max_fields=max_fields, max_part_size=4096) as form:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise ServiceError(422, "Send a WAV file in multipart field file")
        raw = await upload.read(limit + 1)
        if len(raw) > limit:
            raise ServiceError(413, "Recording is too large")
        fields = {key: value for key, value in form.items() if isinstance(value, str)}
        return raw, fields


class ChallengeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    voice_id: str = Field("default", min_length=1, max_length=80)


@router.post("/liveness/challenge")
async def challenge(body: ChallengeInput, request: Request):
    state = request.app.state
    async with state.data_lock:
        voice_id, _ = state.voices.get(body.voice_id)
        return state.liveness.issue(voice_id)


@router.post("/liveness/verify")
async def verify(request: Request):
    state = request.app.state
    if state.settings.security_mode == "off":
        raise ServiceError(409, "Liveness verification is disabled")
    raw, fields = await wav_upload(request, max_fields=1)
    identifier = fields.get("challenge_id", "")
    async with state.data_lock:
        challenge = state.liveness.consume(identifier)
        state.voices.get(challenge.voice_id)
        reference, revision = state.liveness.reference(challenge.voice_id)
        if revision != challenge.reference_revision:
            raise ServiceError(409, "Reference changed; request another challenge")
    passed, text_score, speaker_score = await state.liveness.verify_audio(challenge, raw, reference)
    async with state.data_lock:
        # A deleted voice cannot regain access from a CPU request that was already running.
        state.voices.get(challenge.voice_id)
        if not passed:
            raise ServiceError(403, "Recording did not match the challenge and enrolled speaker; request another challenge")
        result = state.liveness.grant(challenge)
    return {"verified": True, **result, "transcript_similarity": text_score, "speaker_similarity": speaker_score}


@router.post("/watermark/detect")
async def detect(request: Request):
    raw, _ = await wav_upload(request)
    return await request.app.state.watermarker.detect(raw)


@router.get("/voices/{voice_id}/emotions")
async def emotion_list(voice_id: str, request: Request):
    state = request.app.state
    async with state.data_lock:
        resolved, _ = state.voices.get(voice_id)
        return state.emotions.list(resolved)


@router.post("/voices/{voice_id}/emotions/{emotion}", status_code=201)
async def add_emotion(voice_id: str, emotion: EmotionTag, request: Request):
    state = request.app.state
    raw, _ = await wav_upload(request)
    async with state.data_lock:
        resolved, _ = state.voices.get(voice_id)
        state.liveness.authorize(resolved, request.headers.get("x-aria-session"))
        result = await state.emotions.enroll(resolved, emotion, raw)
        state.warmer.notify(resolved, invalidate=True)
        return result


@router.delete("/voices/{voice_id}/emotions/{emotion}", status_code=204)
async def delete_emotion(voice_id: str, emotion: EmotionTag, request: Request):
    state = request.app.state
    async with state.data_lock:
        resolved, _ = state.voices.get(voice_id)
        state.liveness.authorize(resolved, request.headers.get("x-aria-session"))
        state.emotions.delete(resolved, emotion)
        state.warmer.notify(resolved, invalidate=True)

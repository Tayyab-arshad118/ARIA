import hashlib
import secrets
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import select

from ..db import AccessActor, EnrollmentApproval, RuntimeSetting, EmotionReference
import json
from ..services.access import PATIENT, SCOPES, pin_hash
from ..services.errors import ServiceError

router = APIRouter()


class PINInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pin: SecretStr
    actor_id: str = Field(PATIENT, min_length=1, max_length=80)


class CaregiverInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pin: SecretStr
    permissions: list[Literal["speak", "enroll", "manage"]] = Field(default_factory=list, max_length=3)


class ApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recording_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_type: Literal["historical", "current"]
    basis: Literal["patient_consent", "authorized_representative"]
    authorization_reference: str = Field(min_length=1, max_length=240)

    @field_validator("authorization_reference")
    @classmethod
    def nonblank_reference(cls, value):
        if not value.strip():
            raise ValueError("Provide an authorization reference")
        return value.strip()


class RecoveryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recovery_code: SecretStr
    pin: SecretStr


def recovery_code(state):
    code = secrets.token_urlsafe(32)
    with state.db.session.begin() as session:
        session.merge(RuntimeSetting(key="account_recovery", value=state.cipher.encrypt(hashlib.sha256(code.encode()).digest())))
    return code


@router.get("/access/status")
async def status(request: Request):
    access = request.app.state.access
    try:
        actor = access.actor(request, None)
    except ServiceError:
        actor = None
    return {"pin_configured": access.configured(), "actor": actor, "authentication": "device_and_pin" if access.configured() else "device"}


@router.post("/access/setup", status_code=201)
async def setup(body: PINInput, request: Request):
    state = request.app.state
    async with state.data_lock:
        if state.access.configured():
            raise ServiceError(409, "Patient PIN is already configured")
        state.access.create_actor(PATIENT, "patient", body.pin.get_secret_value(), sorted(SCOPES))
        return {**state.access.login(PATIENT, body.pin.get_secret_value()), "recovery_code": recovery_code(state)}


@router.post("/access/login")
async def login(body: PINInput, request: Request):
    state = request.app.state
    async with state.data_lock:
        return state.access.login(body.actor_id, body.pin.get_secret_value())


@router.post("/access/logout")
async def logout(request: Request):
    state = request.app.state
    state.access.sessions.pop(hashlib.sha256(request.headers.get("x-aria-account", "").encode()).hexdigest(), None)
    return {"locked": True}


@router.post("/access/recover")
async def recover(body: RecoveryInput, request: Request):
    state = request.app.state
    async with state.data_lock:
        with state.db.session.begin() as session:
            row = session.get(RuntimeSetting, "account_recovery")
            digest = hashlib.sha256(body.recovery_code.get_secret_value().encode()).digest()
            if not row or not secrets.compare_digest(state.cipher.decrypt(row.value), digest):
                raise ServiceError(403, "Recovery code was not accepted")
            patient = session.get(AccessActor, PATIENT)
            patient.pin_hash = pin_hash(body.pin.get_secret_value())
            patient.failures, patient.locked_until = 0, 0
            for actor in session.scalars(select(AccessActor).where(AccessActor.role == "caregiver")):
                actor.active = False
        state.access.sessions.clear()
        return {**state.access.login(PATIENT, body.pin.get_secret_value()), "recovery_code": recovery_code(state)}


@router.get("/access/caregivers")
async def caregivers(request: Request):
    state = request.app.state
    state.access.patient(request)
    with state.db.session() as session:
        return [{"id": a.id, "active": a.active, "permissions": state.access.unpack(a.permissions)}
            for a in session.scalars(select(AccessActor).where(AccessActor.role == "caregiver"))]


@router.post("/access/caregivers", status_code=201)
async def add_caregiver(body: CaregiverInput, request: Request):
    state = request.app.state
    async with state.data_lock:
        state.access.patient(request)
        if not state.access.configured():
            raise ServiceError(409, "Set a patient PIN before adding caregiver access")
        identifier = "caregiver_" + secrets.token_hex(6)
        state.access.create_actor(identifier, "caregiver", body.pin.get_secret_value(), sorted(set(body.permissions)))
        return {"actor_id": identifier, "permissions": body.permissions}


@router.delete("/access/caregivers/{actor_id}", status_code=204)
async def revoke_caregiver(actor_id: str, request: Request):
    state = request.app.state
    async with state.data_lock:
        state.access.patient(request)
        state.access.revoke_actor(actor_id)


@router.post("/access/authorizations", status_code=201)
async def approve(body: ApprovalInput, request: Request):
    state = request.app.state
    async with state.data_lock:
        actor = state.access.patient(request)
        return {"authorization_id": state.access.approve({**body.model_dump(), "authorizing_actor": actor["id"]})}


@router.delete("/access/authorizations/{identifier}", status_code=204)
async def revoke_approval(identifier: str, request: Request):
    state = request.app.state
    async with state.data_lock:
        state.access.patient(request)
        with state.db.session.begin() as session:
            row = session.get(EnrollmentApproval, identifier)
            if not row:
                raise ServiceError(404, "Authorization not found")
            row.active = False
        # Revocation also invalidates any profile enrolled using this grant.
        for profile in state.voices.list():
            if profile.get("kind") == "builtin":
                continue
            try:
                consent = state.access.consent(profile["id"])
            except ServiceError:
                continue
            if consent.get("authorization_id") == identifier:
                state.voices.revoke(profile["id"])
        with state.db.session() as session:
            affected = [(row.voice_id, row.emotion) for row in session.scalars(select(EmotionReference))
                if json.loads(state.cipher.decrypt(row.latents)).get("authorization", {}).get("authorization_id") == identifier]
        for voice_id, emotion in affected:
            state.emotions.delete(voice_id, emotion)
        state.warmer.notify(invalidate=True)

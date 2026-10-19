"""Dedicated generic voice provider. No redistributed reference is assumed licensed."""
import hashlib
import json
from pathlib import Path

import anyio

from ..db import RuntimeSetting
from .audio_utils import prepare_reference
from .errors import ServiceError

BUILTIN_ID = "aria_builtin"


class BuiltinVoice:
    def __init__(self, settings, db, cipher, gpu, identity):
        self.settings, self.db, self.cipher, self.gpu, self.identity = settings, db, cipher, gpu, identity

    def manifest(self):
        path = self.settings.builtin_voice_manifest
        try:
            if path is None or path.stat().st_size > 16384:
                raise ValueError()
            data = json.loads(path.read_text(encoding="utf-8"))
            if (data.get("synthetic") is not True or data.get("redistribution_permitted") is not True or
                    not all(isinstance(data.get(k), str) and data[k].strip() for k in ("license", "license_source", "reference", "sha256"))):
                raise ValueError()
            reference = (path.parent / data["reference"]).resolve()
            if not reference.is_file() or reference.stat().st_size > self.settings.max_upload_bytes:
                raise ValueError()
            return data, reference
        except (OSError, ValueError, TypeError):
            raise ServiceError(503, "ARIA Default Voice is not configured; supply a licensed synthetic reference manifest") from None

    def profile(self):
        try:
            self.manifest()
            configured = True
        except ServiceError:
            configured = False
        return {"id": BUILTIN_ID, "name": "ARIA Default Voice", "kind": "builtin", "is_default": False,
            "needs_reenrollment": False, "verification_ready": False, "authorization_status": "builtin",
            "available": configured, "status": "ready_to_initialize" if configured else "not_configured",
            "model_version": self.settings.model_version}

    async def get(self):
        from .voice_store import validate_latents
        manifest, path = self.manifest()
        raw = await anyio.to_thread.run_sync(path.read_bytes)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != manifest["sha256"]:
            raise ServiceError(409, "ARIA voice reference does not match its licensed manifest")
        fingerprint = self.identity.fingerprint
        # Reuse conditioning offline only when both reference and model identity match.
        key = "builtin_conditioning"
        with self.db.session() as session:
            row = session.get(RuntimeSetting, key)
            data = json.loads(self.cipher.decrypt(row.value)) if row else None
        if data and fingerprint and data["fingerprint"] == fingerprint and data["source"] == digest and data["version"] == self.settings.model_version:
            validate_latents(data["latents"])
            return BUILTIN_ID, data["latents"]
        fingerprint = await self.identity.sync(self.gpu, required=True)
        prepared = await anyio.to_thread.run_sync(prepare_reference, raw, self.settings)
        latents = await self.gpu.latents(prepared)
        validate_latents(latents)
        if self.settings.workflow_mode != "research" and latents.get("model_fingerprint") != fingerprint:
            raise ServiceError(409, "Checkpoint changed while preparing ARIA Voice")
        data = {"fingerprint": fingerprint, "source": digest, "version": self.settings.model_version, "latents": latents}
        with self.db.session.begin() as session:
            session.merge(RuntimeSetting(key=key, value=self.cipher.encrypt(json.dumps(data).encode())))
        return BUILTIN_ID, latents

    def fingerprint(self):
        try:
            manifest, _ = self.manifest()
            return [manifest["sha256"], self.identity.fingerprint]
        except ServiceError:
            return ["unconfigured", self.identity.fingerprint]

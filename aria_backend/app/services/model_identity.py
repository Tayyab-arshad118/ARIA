import json
import re

from ..db import RuntimeSetting
from .errors import ServiceError


class ModelIdentity:
    def __init__(self, settings, db, cipher):
        self.settings, self.db, self.cipher = settings, db, cipher
        self.fingerprint = None
        with db.session() as session:
            row = session.get(RuntimeSetting, "checkpoint_identity")
            if row:
                data = json.loads(cipher.decrypt(row.value))
                if data.get("model_version") == settings.model_version:
                    self.fingerprint = data["fingerprint"]

    def observe(self, health):
        value = health.get("model_fingerprint")
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            if self.settings.workflow_mode == "research":
                return self.settings.model_version
            raise ServiceError(409, "Update the Colab notebook: checkpoint fingerprint is required")
        if value != self.fingerprint:
            self.fingerprint = value
            with self.db.session.begin() as session:
                session.merge(RuntimeSetting(key="checkpoint_identity", value=self.cipher.encrypt(json.dumps(
                    {"model_version": self.settings.model_version, "fingerprint": value}).encode())))
        return value

    async def sync(self, gpu, required=False):
        try:
            return self.observe(await gpu.health())
        except ServiceError as error:
            if required or error.status != 503:
                raise
            return self.fingerprint

    async def require(self, gpu, expected):
        actual = await self.sync(gpu, required=True)
        if actual != expected:
            raise ServiceError(409, "Checkpoint changed; prepare this voice again before speaking")
        return actual

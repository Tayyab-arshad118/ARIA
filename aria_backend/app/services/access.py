"""Local device credential + optional PIN sessions; authorization is separate from login."""
import hashlib
import hmac
import json
import secrets
import time

from sqlalchemy import select

from ..db import AccessActor, EnrollmentApproval, VoiceConsent
from .errors import ServiceError

PATIENT = "patient"
SCOPES = {"speak", "enroll", "manage"}


def pin_hash(pin, salt=None):
    if not isinstance(pin, str) or not pin.isascii() or not pin.isdigit() or not 6 <= len(pin) <= 12:
        raise ServiceError(422, "Use a PIN of 6–12 digits")
    salt = salt or secrets.token_hex(16)
    value = hashlib.scrypt(pin.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ":" + value


class Access:
    def __init__(self, settings, db, cipher):
        self.settings, self.db, self.cipher = settings, db, cipher
        self.sessions = {}

    def pack(self, value):
        return self.cipher.encrypt(json.dumps(value, ensure_ascii=False).encode())

    def unpack(self, value):
        return json.loads(self.cipher.decrypt(value))

    def configured(self):
        with self.db.session() as session:
            return session.get(AccessActor, PATIENT) is not None

    def actor(self, request, scope="speak"):
        token = request.headers.get("x-aria-account", "")
        if not token and not self.configured():
            # The existing strong OS-protected bearer key identifies this installation's operator.
            return {"id": PATIENT, "role": "patient", "permissions": sorted(SCOPES), "method": "device"}
        key = hashlib.sha256(token.encode()).hexdigest()
        item = self.sessions.get(key)
        if not item or item[1] <= time.time():
            self.sessions.pop(key, None)
            raise ServiceError(401, "Unlock your local account with its PIN")
        with self.db.session() as session:
            actor = session.get(AccessActor, item[0])
            if not actor or not actor.active:
                raise ServiceError(403, "Account access has been revoked")
            permissions = self.unpack(actor.permissions)
            if scope is not None and actor.role != "patient" and scope not in permissions:
                raise ServiceError(403, "This caregiver is not allowed to perform that action")
            return {"id": actor.id, "role": actor.role, "permissions": permissions, "method": "pin"}

    def patient(self, request):
        actor = self.actor(request, "manage")
        if actor["role"] != "patient":
            raise ServiceError(403, "Only the patient or responsible account holder can authorize this action")
        return actor

    def create_actor(self, identifier, role, pin, permissions):
        hashed = pin_hash(pin)
        with self.db.session.begin() as session:
            if session.get(AccessActor, identifier):
                raise ServiceError(409, "Account already exists")
            session.add(AccessActor(id=identifier, role=role, pin_hash=hashed, permissions=self.pack(permissions)))
        return identifier

    def login(self, identifier, pin):
        now = time.time()
        success = False
        with self.db.session.begin() as session:
            actor = session.get(AccessActor, identifier)
            if actor and actor.locked_until > now:
                raise ServiceError(429, "Too many PIN attempts; wait before trying again")
            salt = actor.pin_hash.split(":")[0] if actor else "00" * 16
            candidate = pin_hash(pin, salt)
            success = bool(actor and actor.active and hmac.compare_digest(candidate, actor.pin_hash))
            if actor:
                if success:
                    actor.failures, actor.locked_until = 0, 0
                else:
                    actor.failures += 1
                    if actor.failures >= self.settings.pin_attempt_limit:
                        actor.locked_until = now + self.settings.pin_lock_seconds
                        actor.failures = 0
        if not success:
            raise ServiceError(401, "Account or PIN was not accepted")
        self.sessions = {k: v for k, v in self.sessions.items() if v[1] > now}
        if len(self.sessions) >= 128:
            raise ServiceError(429, "Too many active sessions; lock a session and retry")
        token = secrets.token_urlsafe(32)
        self.sessions[hashlib.sha256(token.encode()).hexdigest()] = (identifier, now + self.settings.account_session_seconds)
        return {"account_token": token, "actor_id": identifier, "expires_in": self.settings.account_session_seconds}

    def revoke_actor(self, identifier):
        if identifier == PATIENT:
            raise ServiceError(422, "The patient account cannot be revoked as a caregiver")
        with self.db.session.begin() as session:
            actor = session.get(AccessActor, identifier)
            if not actor:
                raise ServiceError(404, "Caregiver not found")
            actor.active = False
        self.sessions = {key: value for key, value in self.sessions.items() if value[0] != identifier}

    def approve(self, data):
        identifier = secrets.token_urlsafe(18)
        with self.db.session.begin() as session:
            session.add(EnrollmentApproval(id=identifier, content=self.pack({**data, "beneficiary": PATIENT})))
        return identifier

    def approval(self, identifier, source_hash):
        with self.db.session() as session:
            row = session.get(EnrollmentApproval, identifier)
            if not row or not row.active or row.used:
                raise ServiceError(403, "A current unused patient authorization is required")
            data = self.unpack(row.content)
            if not hmac.compare_digest(data["recording_sha256"], source_hash):
                raise ServiceError(403, "Authorization does not match this recording")
            return data

    def consent(self, voice_id):
        with self.db.session() as session:
            row = session.get(VoiceConsent, voice_id)
            if not row or not row.active:
                raise ServiceError(403, "This voice requires current patient authorization")
            return self.unpack(row.content)

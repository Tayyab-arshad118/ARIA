import os

from cryptography.fernet import Fernet


def load_cipher(settings):
    supplied = settings.fernet_key.get_secret_value()
    if supplied:
        return Fernet(supplied.encode("ascii"))
    directory = settings.data_dir / "voices"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".fernet.key"
    if not path.exists():
        # Never silently replace a lost key if encrypted records already exist.
        from sqlalchemy import select
        from ..db import (Database, Voice, AudioCache, TextCache, RuntimeSetting, Phrase, PhraseAudio,
                          SpokenHistory, VerificationProfile, EmotionReference)
        db = Database(settings.data_dir)
        try:
            with db.session() as session:
                if any(session.scalar(select(table).limit(1)) is not None
                       for table in (Voice, AudioCache, TextCache, RuntimeSetting, Phrase, PhraseAudio,
                                     SpokenHistory, VerificationProfile, EmotionReference)):
                    raise RuntimeError("Encryption key missing; restore the original key before opening existing data")
        finally:
            db.close()
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "wb") as output:
                output.write(Fernet.generate_key())
    return Fernet(path.read_bytes().strip())

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import LargeBinary, String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class Voice(Base):
    __tablename__ = "voices"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    model_version: Mapped[str]
    created_at: Mapped[str] = mapped_column(default=timestamp)
    latents: Mapped[bytes] = mapped_column(LargeBinary)
    raw_audio: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)


class AudioCache(Base):
    __tablename__ = "audio_cache"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    voice_id: Mapped[str] = mapped_column(index=True)
    created_at: Mapped[str] = mapped_column(default=timestamp)
    audio: Mapped[bytes] = mapped_column(LargeBinary)


class TextCache(Base):
    __tablename__ = "text_cache"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    result: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[str] = mapped_column(default=timestamp)


class RuntimeSetting(Base):
    __tablename__ = "runtime_settings"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[bytes] = mapped_column(LargeBinary)


class Phrase(Base):
    __tablename__ = "phrases"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    favorite: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[str] = mapped_column(default=timestamp)
    last_used: Mapped[str | None] = mapped_column(nullable=True)
    uses: Mapped[int] = mapped_column(default=0)


class PhraseAudio(Base):
    __tablename__ = "phrase_audio"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    phrase_id: Mapped[str] = mapped_column(index=True)
    voice_id: Mapped[str] = mapped_column(index=True)
    speed: Mapped[float]
    created_at: Mapped[str] = mapped_column(default=timestamp)
    audio: Mapped[bytes] = mapped_column(LargeBinary)


class SpokenHistory(Base):
    __tablename__ = "spoken_history"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    voice_id: Mapped[str] = mapped_column(index=True)
    text: Mapped[bytes] = mapped_column(LargeBinary)


class VerificationProfile(Base):
    __tablename__ = "verification_profiles"
    voice_id: Mapped[str] = mapped_column(String, primary_key=True)
    embedding: Mapped[bytes] = mapped_column(LargeBinary)
    model_version: Mapped[str]
    revision: Mapped[str]


class EmotionReference(Base):
    __tablename__ = "emotion_references"
    voice_id: Mapped[str] = mapped_column(String, primary_key=True)
    emotion: Mapped[str] = mapped_column(String, primary_key=True)
    latents: Mapped[bytes] = mapped_column(LargeBinary)
    raw_audio: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    model_version: Mapped[str]
    revision: Mapped[str]


class Database:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine("sqlite:///" + (directory / "aria.sqlite").as_posix(),
                                    connect_args={"check_same_thread": False})

        @event.listens_for(self.engine, "connect")
        def configure(connection, record):
            connection.execute("PRAGMA secure_delete=ON")
            connection.execute("PRAGMA busy_timeout=5000")

        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(self.engine, expire_on_commit=False)

    def close(self):
        self.engine.dispose()

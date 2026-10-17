# Database and persisted records

[Project handbook](../../../README.md) · [Application package](../README.md)

This package defines SQLite tables and SQLAlchemy session creation. [database.py](database.py) contains models and the `Database` wrapper; [__init__.py](__init__.py) exposes them to the rest of the backend.

## Stored records

| Model/table | Contents |
| --- | --- |
| `Voice` / `voices` | Profile ID/name/model metadata, encrypted voice representations, optional encrypted original audio. |
| `AudioCache` / `audio_cache` | General synthesized audio keyed by relevant voice/text/settings. |
| `TextCache` / `text_cache` | Encrypted transliteration and phrase-translation results. |
| `RuntimeSetting` / `runtime_settings` | Encrypted saved connections, remembered model languages, and seed marker. |
| `Phrase` / `phrases` | Encrypted phrase content plus favorite/use metadata. |
| `PhraseAudio` / `phrase_audio` | Separately retained prepared phrase speech. |
| `SpokenHistory` / `spoken_history` | Bounded encrypted text history for local prediction. |
| `VerificationProfile` / `verification_profiles` | Encrypted speaker baseline and its model/revision metadata. |
| `EmotionReference` / `emotion_references` | Tagged encrypted voice representations, optional audio, and revisions. |

## Encryption boundary

SQLite itself is not a fully encrypted database file. Services encrypt sensitive fields before storing them. IDs, profile names, dates, versions, favorite/use counters, and cache keys can remain readable metadata. [The crypto service](../services/crypto.py) supplies the Fernet cipher.

The database is under active `DATA_DIR`. Without an explicit encryption key, the key file is `voices/.fernet.key` within that directory. Possession of both the database and key permits decryption. Back up both, restrict access, and exclude them from Git.

## Transactions and lifecycle

Use a session context for reads and a transaction context for writes. Do not hold a session open across a remote network operation unnecessarily. Services coordinate related records and API-level data locking; the table layer alone does not make asynchronous business operations safe.

Tables are created at startup. `create_all` does not provide a general migration system for changing existing columns. Plan and test a migration before changing an existing schema; do not delete a user's database merely to make a new model definition work.

## Deletion behavior

Voice deletion explicitly clears related caches, history, verification, and emotion records. Phrase edits/delete clear prepared audio. Delete-all removes personal data and resets the phrase collection while retaining connection settings/key. Background work must re-check deletion/version state before writing.

Stop the backend before a simple file-copy backup. A Git clone restores source code and seed resources, not a user's voice profiles.

# Backend services

[Project handbook](../../../README.md) · [Application package](../README.md)

Services perform the actual work requested by the API. Shared instances are created during application startup. Their settings, database, encryption cipher, and external clients are passed in so tests can replace expensive or remote components.

## Text and languages

| Module | Responsibility |
| --- | --- |
| [transliteration.py](transliteration.py) | Local Roman Urdu dictionary/rules, optional Groq script conversion, output validation, encrypted text cache. |
| [urdu_normalizer.py](urdu_normalizer.py) | Urdu normalization, including text/number preparation for speech. |
| [languages.py](languages.py) | Language labels, logical/model aliases, encrypted discovery, model-tag validation, Unicode-preserving cleanup. |
| [chunker.py](chunker.py) | Breaks long text into model-sized pieces while preserving order and sensible boundaries. |
| [prediction.py](prediction.py) | Fast local Roman Urdu next-word/prefix suggestions from seeds and bounded history. |
| [phrase_translation.py](phrase_translation.py) | Batched meaning translation with encrypted per-language text caching and stale-write protection. |

Transliteration prepares the same language's script. Phrase translation changes the language while preserving meaning. These are intentionally separate operations. Preview can work without Colab; synthesis still checks model support.

## Audio and model calls

| Module | Responsibility |
| --- | --- |
| [reference_audio.py](reference_audio.py) | Bounded decoding/scanning of long WAV/compressed sources and reference-window selection. |
| [audio_utils.py](audio_utils.py) | WAV encoding, resampling, reference entry point, audio assembly/normalization. |
| [gpu_client.py](gpu_client.py) | Authenticated Colab HTTP calls, deadlines/retries, response bounds, language and latent checks. |
| [synthesis.py](synthesis.py) | Resolves language, optionally selects emotion references, renders chunks, and assembles ordered audio. |
| [voice_store.py](voice_store.py) | Registration, representation validation, encrypted profiles, compatibility, and related-data deletion. |

The long-source scanner keeps a short suitable window, not the entire recording as conditioning. Normal inference requires no local PyTorch/XTTS import. Heavy audio preparation is sent to worker threads so it does not block the event loop unnecessarily.

## Storage, caching, and phrases

| Module | Responsibility |
| --- | --- |
| [crypto.py](crypto.py) | Loads/creates the encryption key; refuses silent replacement over existing encrypted records. |
| [cache.py](cache.py) | General audio cache and keys including model/language/sampling/processing settings. |
| [phrases.py](phrases.py) | Source phrase CRUD, seed-once behavior, usage, per-language audio keys and retention. |
| [phrase_warmer.py](phrase_warmer.py) | One background worker; prioritizes selected voices/favorites and rechecks state before saving. |
| [errors.py](errors.py) | Safe service error type carrying status and user-facing detail. |

Phrase audio is stored separately from general typed-speech audio. Cache hits must still pass applicable authorization and protected-audio validation. Do not remove language/version/reference revisions from keys just to increase hit rate.

## Emotion, watermarking, and experimental verification

| Module | Responsibility |
| --- | --- |
| [liveness.py](liveness.py) | Single-use challenges, transcript/speaker checks, expiry, voice-bound sessions. |
| [safety_audio.py](safety_audio.py) | Bounded WAV preparation for short verification/detection workloads. |
| [watermark.py](watermark.py) | Required AudioSeal embedding/detection before caching, cache validation and local model handling. |
| [emotion.py](emotion.py) | Manual expression, optional lexical suggestions, authorized reference conditioning, honest neutral fallback and cache invalidation. |

These features load configured local weights; API requests do not download models. Missing verification models cannot grant a session. Watermark availability is explicitly reported. Emotion tags depend on a small lexicon and recordings, not a guaranteed model control.

Normal output must pass embedding and encoded-audio detection before caching/playback. Manual expression overrides the lexicon, with explicit neutral fallback. Assistive enrollment never requires an ECAPA baseline; spoken verification is research-only. See the [implementation and evaluation guide](../../../README.md#chapter-20--fyp-implementation-migration-and-evaluation).

## Change safely

Keep external clients replaceable, inputs bounded, private content out of logs, and stored sensitive payloads encrypted. When work releases the shared data lock, check its generation/revision again before persisting. Follow [service/backend tests](../../tests/README.md), particularly deletion races and stale language results.

## Assistive services

[access.py](access.py) owns PIN sessions, scopes and encrypted consent grants. [builtin_voice.py](builtin_voice.py) owns the separate licensed generic provider. [model_identity.py](model_identity.py) remembers actual checkpoint hashes. [watermark.py](watermark.py) embeds and validates before caching, revalidates cache hits, and fails closed. Manual expression selection reports an explicit neutral fallback when no authorized style exists.

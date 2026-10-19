# HTTP API handlers

[Project handbook](../../../README.md) · [Application package](../README.md)

These modules define the backend's public HTTP interface. Their routers are mounted under `/api` in the application factory. They validate inputs, choose services, hold/release the data lock where needed, and format responses. They should not load XTTS directly.

## Route-to-file map

| Module | Endpoints |
| --- | --- |
| [health.py](health.py) | `GET /health`, `GET /languages`. |
| [text.py](text.py) | `POST /transliterate`; common text validation and preview schema. |
| [tts.py](tts.py) | `POST /tts`; typed speech, cache, language, session, watermark headers. |
| [voices.py](voices.py) | `GET/POST /voices`, `DELETE /voices/{id}`, `DELETE /voices/all`. |
| [admin.py](admin.py) | Checked `POST /admin/connect` and direct `POST /admin/colab-url`. |
| [phrases.py](phrases.py) | List/create/update/delete phrases, warming, and phrase speech. |
| [predict.py](predict.py) | `GET /predict?prefix=...`. |
| [safety.py](safety.py) | Challenges, verification, watermark detection, and emotion references. |
| [__init__.py](__init__.py) | Package marker. |

The [main API chapter](../../../README.md#chapter-13--api-reference) lists every route and common error code.

## Text and speech payloads

Preview example:

```json
{"text":"namaste","language":"hi","input_mode":"auto"}
```

Preview returns the original/input result information, generic `text`, target `language`, and `method_used`. Urdu compatibility fields remain available. Known preview languages do not require Colab to be reachable.

Speech example:

```json
{"text":"नमस्ते","language":"hi","input_mode":"native","voice_id":"default","speed":1.0}
```

Speech returns raw WAV bytes. `voice_id=default` resolves a stored profile; it is not a built-in anonymous voice. Optional speed must be between 0.5 and 2. A real model must advertise the selected speech language.

## Multipart requests

Enrollment accepts one file field named `file` and a voice `name` of 1–80 nonblank characters. Verification accepts `file` plus `challenge_id`. Emotion routes accept `file` and obtain the voice/style from the URL. File/form counts and field sizes are limited before work begins. Verification and watermark detection require WAV; enrollment and emotion preparation accept the wider audio format set.

## Phrases

Creation uses `roman`, `urdu`, and optional `category`. Updates accept those fields and/or `favorite`; empty updates, explicit nulls, wrong scripts, and invalid categories are rejected. Categories are needs, medical, family, greetings, and custom.

Lists accept voice/speed/language plus filters and add translated `display_text` and a per-variant `cached` flag. Phrase speech takes voice/speed/language. The ready flag is not a guarantee that all speeds/languages are prepared.

## Authentication and errors

The configured local key is a bearer token in `Authorization`. A strict voice session is a separate `X-ARIA-Session` header. Never put either into query strings. Colab's `x-api-key` belongs only to the upstream client.

Checked Connect uses a temporary client to probe proposed credentials before saving; direct URL update does not. Connect responses contain safe error codes, never raw upstream error bodies. Missing/malformed input is reported with sanitized messages rather than exposing sensitive Pydantic input dumps.

## Changing an endpoint

Preserve shared validation, authorization before cache access, and relevant post-processing/session checks. Update the desktop client's matching method and backend tests when altering a contract. Review deletion/in-flight behavior, not only the success response.

## Account and protection contracts

[access.py](access.py) exposes patient PIN/recovery, scoped caregiver and recording-grant routes. Personal operations accept `X-ARIA-Account` after PIN setup. Speech and phrase requests accept `emotion`; response headers distinguish requested/effective style. Normal WAV responses require verified protection. See the [account route table](../../../README.md#204-patient-caregiver-and-historical-audio) for setup and revocation.

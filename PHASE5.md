# Phase 5 — Optional CPU safety features

All five implementation phases are now present. Phase 5 adds AudioSeal watermarking,
best-effort speech challenge verification, and local emotion-reference selection. Each
feature is off by default; the existing lightweight workflow remains available.

## File tree and complete code

```text
proj/
├── PHASE5.md
├── aria_backend/
│   ├── app/
│   │   ├── config.py, main.py
│   │   ├── api/
│   │   │   ├── safety.py                 # Challenge/verify, watermark detect, emotion refs
│   │   │   └── tts.py, phrases.py, voices.py, health.py
│   │   ├── db/__init__.py, db/database.py
│   │   └── services/
│   │       ├── watermark.py, liveness.py, emotion.py, safety_audio.py
│   │       └── voice_store.py, synthesis.py, cache.py, crypto.py,
│   │           gpu_client.py, phrase_warmer.py
│   ├── scripts/prepare_safety_models.py
│   ├── scripts/evaluate.py               # Accepts an optional strict-session env token
│   ├── tests/test_safety.py
│   ├── requirements-safety.txt
│   ├── .env.example, .gitignore
│   └── README.md
└── aria_desktop/
    ├── aria_app.py                       # Verification and emotion-reference dialogs
    ├── tests/test_desktop.py
    ├── pyproject.toml
    └── README.md
```

The full runnable implementations are in these files. SQLite adds separate verification
and emotion-reference tables; no destructive schema migration is required. Existing voice
profiles still work with checks off. A profile enrolled without verification lacks an
ECAPA baseline and needs re-enrollment before it can pass a challenge.

## Exact setup and run commands

Normal desktop/backend setup is unchanged. From the repository root, install the normal
requirements if necessary:

```powershell
.\.venv\Scripts\python.exe -m pip install -r aria_backend/requirements.txt -r aria_desktop/requirements.txt
```

Optional safety dependencies are installed into the **backend** environment. The matching
CPU PyTorch pair is pinned to avoid changes in torchaudio APIs used by SpeechBrain 1.0.3:

```powershell
.\.venv\Scripts\python.exe -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r aria_backend/requirements-safety.txt
```

Model files are not bundled. Download the public models once using the explicit setup
command. The command refuses downloads unless both its flag and `LOCAL_ONLY=false`
authorize them. This is a separate setup process; API requests never download models.

```powershell
$env:LOCAL_ONLY = "false"
.\.venv\Scripts\python.exe aria_backend/scripts/prepare_safety_models.py --allow-downloads
$env:LOCAL_ONLY = "true"
```

Use `--feature watermark` or `--feature liveness` to download only that feature's models.
Linux/macOS equivalents, from the repository root:

```bash
.venv/bin/python -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -r aria_backend/requirements-safety.txt
LOCAL_ONLY=false .venv/bin/python aria_backend/scripts/prepare_safety_models.py --allow-downloads
```

The configured default locations are under `aria_backend/data/models/`: AudioSeal
generator/detector checkpoint files, a local faster-whisper `small` directory, and a local
SpeechBrain ECAPA directory. These are ignored by Git and excluded from the isolated Flet
build. Use trusted weights: upstream checkpoint formats can deserialize Python objects.

Set the desired flags in the backend's existing `.env`, using the documented values in
[.env.example](aria_backend/.env.example). For example:

```dotenv
WATERMARK_ENABLED=true
SECURITY_MODE=basic
EMOTION_ENABLED=true
LOCAL_ONLY=true
```

Start the backend in terminal 1, from the repository root:

```powershell
Set-Location aria_backend
..\.venv\Scripts\python.exe -m app
```

Start the app in terminal 2, from the repository root:

```powershell
.\.venv\Scripts\python.exe aria_desktop/aria_app.py
```

For strict gating, change `SECURITY_MODE=strict` and restart the backend. Enroll a fresh
voice after enabling verification, choose it in the app, and use **Verify voice** before
speaking. Whisper/ECAPA must be available locally; missing models cause 503 rather than
silently bypassing verification. Colab still performs XTTS inference, using `LANG_TAG=ar`.
The local ASR correctly uses `LIVENESS_LANGUAGE=ur` for Urdu transcription.

## AudioSeal watermarking

When enabled, the backend applies AudioSeal on CPU to each outgoing typed-speech or
quick-phrase WAV **after** stitching, resampling and normalization. This also happens on
audio-cache hits, so enabling the flag cannot return an old unmarked cached response.
Internal encrypted caches hold pre-watermark audio; background preparation does not issue
playable files. CPU inference works in bounded chunks, with short clips padded then trimmed.
There is no loudness normalization after watermarking, only WAV encoding/peak clipping.

Every speech response includes:

| Header | Meaning |
| --- | --- |
| `X-ARIA-Generated: true` | The response was produced by this app; not evidence of a watermark |
| `X-ARIA-Watermark: embedded` | The embedding operation completed |
| `X-ARIA-Watermark: unavailable` | Watermarking was requested but failed; original audio returned |
| `X-ARIA-Watermark: disabled` | The feature flag is off |
| `X-ARIA-Emotion` | Chosen lexical tag, or `disabled` |

Unavailable AudioSeal dependencies/weights or processing errors produce a structured
warning without audio, text, secrets or raw exception details. Speech still works.
A retry cooldown avoids repeated model loading/log warnings. Detection fails with 503
when the detector is unavailable; it does not pretend an unavailable check is negative.

`POST /api/watermark/detect` accepts multipart WAV field `file` and returns:

```json
{"detected": true, "score": 0.99, "message_bits": "0100000101010010", "aria_payload_match": true}
```

This is an example response shape, not a measured model result. `score` aggregates the
AudioSeal detector's fraction of positively classified frames, weighted by chunk duration.
The message is taken from the strongest chunk; mixed-watermark audio can therefore be
ambiguous. Payload matching is **not** cryptographic attribution: the 16-bit marker is
public and forgeable. Detection and perceptual transparency are best-effort, especially
for very short, clipped, edited or re-encoded clips. “Embedded” reports successful
processing, not a guarantee that a later detector will recover the watermark.

API example from the backend directory (uses environment-based authentication):

```python
from pathlib import Path
import httpx
from app.config import Settings

settings = Settings()
key = settings.aria_key.get_secret_value()
headers = {"Authorization": f"Bearer {key}"} if key else {}
with Path("generated.wav").open("rb") as source:
    response = httpx.post("http://127.0.0.1:8001/api/watermark/detect", headers=headers,
                         files={"file": ("generated.wav", source, "audio/wav")}, timeout=120)
response.raise_for_status()
print(response.json())
```

Reference: [AudioSeal's implementation and API](https://github.com/facebookresearch/audioseal).

## Challenge-response verification

| Mode | Behavior |
| --- | --- |
| `off` | No challenge or speech gate; no ECAPA enrollment baseline is computed |
| `basic` | Enrollment computes an encrypted ECAPA baseline; verification is available but optional |
| `strict` | Both `/api/tts` and `/api/phrases/{id}/speak` require a valid voice-bound session token, including cache hits |

The backend issues an Urdu prompt containing four randomly selected words. A challenge
is single-use and expires after 60 seconds by default, including upload, queue time and
CPU verification. The user records the displayed prompt and uploads the WAV. The app
supports file selection; microphone capture remains an explicitly optional future extra.

CPU faster-whisper transcribes the recording. The backend normalizes its Urdu, computes
text similarity, and requires the random words to occur in order. ECAPA cosine similarity
compares the challenge recording with the enrolled speaker baseline. **Both** configurable
thresholds must pass. A successful verification creates a random session token that lasts
300 seconds by default. No transcript, challenge recording, or session token is written
to disk. ECAPA enrollment vectors are encrypted with the existing Fernet key.

| Route | Input | Result |
| --- | --- | --- |
| `POST /api/liveness/challenge` | `{voice_id?: "default"}` | `challenge_id`, resolved `voice_id`, `phrase`, `expires_in` |
| `POST /api/liveness/verify` | Multipart `file` WAV and `challenge_id` | `verified`, `session_token`, `voice_id`, `expires_in`, similarity scores |

Send the returned token as **`X-ARIA-Session`**, in addition to the optional backend
`Authorization` header. The Flet client does this automatically and retains tokens only
in memory. Tokens bind to a specific voice, model version and verification reference
revision; another voice cannot use them. Restart, expiry, voice deletion and delete-all
invalidate the relevant state. Tokens are checked before cache/GPU work and again after
outgoing audio processing. App disconnect clears client-held tokens; server-issued tokens
otherwise remain valid until expiry or revocation by voice deletion/server shutdown.

Verification attempts consume the challenge even when they fail. An expired/replayed
challenge gives 410; a nonmatching phrase/speaker gives 403; missing verification baseline
gives 409; unavailable models give 503. A recording that finishes after the challenge's
deadline cannot obtain a token. Deleting a profile while verification runs prevents it
from being re-authorized by the pending CPU result.

These checks are **best-effort, not foolproof anti-deepfake protection**. They do not prove
consent or ownership of enrollment audio, reliably defeat live voice cloning, or replace
account authentication. ASR mistakes, accents, impairments, noise and threshold choices
can reject genuine speech. In particular, someone with profound speech inability may
be unable to complete the challenge. Keep checks off or optional for users who cannot
produce the required speech; strict mode is not universally suitable for this prosthetic.
The thresholds must be evaluated with your own users/reference conditions.

Sources: [faster-whisper CPU transcription](https://github.com/SYSTRAN/faster-whisper),
[SpeechBrain ECAPA model](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb).

## Emotion references: honest scope

With `EMOTION_ENABLED=true`, a simple local Urdu/Roman lexicon labels text as `neutral`,
`happy`, `sad`, `calm`, or `angry`, with limited nearby-negation handling. There is no
additional LLM/API call for sentiment. If the selected voice has a matching tagged
reference, its encrypted latents are used. Otherwise the base reference is used.
Small configurable speed/temperature deltas accompany non-neutral tags, within existing
XTTS request bounds. Cache fingerprints include the selected reference revision and
emotion settings; changing a reference invalidates that voice's caches and wakes warming.

**XTTS has no native emotion control, so the effect depends on the reference clips.**
Sampling/speed changes do not guarantee an emotion. Sarcasm, ambiguous wording and
lexicon mistakes are expected limitations; this is not a clinical emotion assessment.

The app's **Emotion reference** button appears when enabled. Choose a style and a
6–30 second WAV of the selected speaker, then save. It replaces that style's previous
reference. With verification enabled, ECAPA must match the enrolled speaker; strict mode
also requires a current session token. With checks off, the user is responsible for choosing
a clip from the intended speaker. Raw clips are retained only when `KEEP_RAW_AUDIO=true`,
and then encrypted; returned XTTS latents are always encrypted locally.

| Route | Input | Result |
| --- | --- | --- |
| `GET /api/voices/{id}/emotions` | Voice ID | Reference tags, model versions and re-enrollment flags |
| `POST /api/voices/{id}/emotions/{tag}` | Multipart `file` WAV | 201 with voice ID, tag and model version |
| `DELETE /api/voices/{id}/emotions/{tag}` | Voice ID/tag; strict session header if applicable | 204; removes reference and invalidates cached audio |

Voice/delete-all removal also removes these references, ECAPA baselines and sessions.
Changing ECAPA weights requires changing `LIVENESS_MODEL_VERSION` and re-enrolling
verification baselines. Changing XTTS weights still requires the existing model-swap flow.

## Environment/configuration

Every new setting is documented in [the backend template](aria_backend/.env.example).

- Watermark: `WATERMARK_ENABLED`, `WATERMARK_GENERATOR_PATH`, `WATERMARK_DETECTOR_PATH`,
  `WATERMARK_MESSAGE_BITS`, `WATERMARK_THRESHOLD`, `WATERMARK_BIT_THRESHOLD`,
  `WATERMARK_FRAME_THRESHOLD`, `WATERMARK_CHUNK_SECONDS`, `WATERMARK_DETECT_MAX_SECONDS`,
  `WATERMARK_RETRY_SECONDS`.
- Verification: `SECURITY_MODE`, `LIVENESS_WHISPER_PATH`, `LIVENESS_SPEAKER_PATH`,
  `LIVENESS_MODEL_VERSION`, `LIVENESS_LANGUAGE`, `LIVENESS_BEAM_SIZE`, `LIVENESS_VAD_FILTER`,
  `LIVENESS_COMPUTE_TYPE`, `LIVENESS_TRANSCRIPT_THRESHOLD`, `LIVENESS_SPEAKER_THRESHOLD`,
  `LIVENESS_CHALLENGE_SECONDS`, `LIVENESS_SESSION_SECONDS`, `LIVENESS_MAX_PENDING`,
  `LIVENESS_MIN_SECONDS`, `LIVENESS_MAX_SECONDS`.
- CPU/model setup: `SAFETY_CPU_THREADS`, `SAFETY_CACHE_DIR`, `SAFETY_WHISPER_REPO`,
  `SAFETY_SPEAKER_REPO`, `SAFETY_WATERMARK_REPO`.
- Emotion: `EMOTION_ENABLED`, `EMOTION_SPEED_DELTA`, `EMOTION_TEMPERATURE_DELTA`.
- Optional evaluator authentication: `LIVENESS_SESSION_TOKEN`, read only from the evaluator's
  environment/.env and never included in its CSV/summary output.

Runtime inference accepts only configured local safety model paths; API requests do not
fetch weights, even with `LOCAL_ONLY=false`. Downloads occur only from the separately
invoked setup script. All optional inference stays on CPU. Model loading and CPU work
run in worker threads; per-engine locks bound concurrent model use. Watermark processing
adds work even to cached playback, and verification can be slow on modest CPUs.

## Test commands and checklist

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q aria_backend/tests/test_safety.py aria_desktop/tests
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

Use `.venv/bin/python` on Linux/macOS. **153 repository tests passed**: 82 backend,
40 app and 31 notebook tests. Safety tests inject CPU engine doubles and synthetic audio;
the base environment passes compilation and dependency checks. The existing Starlette
TestClient/httpx deprecation warning remains non-failing. Optional model inference has
not been exercised with real AudioSeal/Whisper/ECAPA weights in this workspace.

Acceptance checklist:

- Flags off: enrollment, ordinary speech, phrases and cached playback still work.
- Enable watermarking with local weights; detect a generated clip and compare an unmarked clip.
- Missing watermark weights: speech succeeds with `unavailable` and a structured warning;
  detection returns 503 rather than a false negative.
- Enable basic verification and re-enroll; a matching challenge produces a token.
- Strict mode rejects missing/expired/wrong-voice tokens for typed speech and phrase cache hits.
- Replayed, expired, wrong-text, wrong-speaker and missing-model checks cannot grant a token.
- Edit/delete a voice or delete all; corresponding tokens and biometric/reference data disappear.
- Upload an emotion reference, verify cache invalidation, and listen for any actual effect.
- On the real Colab/desktop/device, assess quality, usability and timing before relying on these checks.

## Final assumptions, limitations and future work

**Assumptions:** the user supplies a trusted, matching full XTTS-v2 checkpoint/config/extended
vocabulary, trained for Urdu using `ar`; reference recordings are suitable and authorized.
This is a single-user, single-process local backend and free testing deployment. Model
versions are updated deliberately when weights change. Optional safety weights are installed
locally before enabling their features; existing profiles are re-enrolled when needed.

**Limitations:** the genuine XTTS checkpoint, real optional safety models, native playback
and Android APK have not been exercised here. Tests do not establish clinical usefulness,
intelligibility, speaker fidelity, watermark reliability or resistance to determined spoofing.
Strict liveness may exclude users who cannot speak. Roman Urdu rules and lexical emotion
classification are approximate. Free Colab/quick-tunnel availability is unstable. Generated
keys, connection settings, model versions and reference management need careful local handling.

The privacy architecture remains explicit: reference audio travels to the user's Colab for
latent computation; latents and text travel there per synthesis request without server-side
voice storage by the provided notebook. Groq receives text only when its transliteration
flags allow it. Local biometric, audio, phrase and history content is encrypted at rest;
some metadata is plaintext, and access to both database and key defeats that encryption.
Google/Cloudflare still provide hosting/transport. Deletion does not erase backups or
third-party copies. See [the backend privacy statement](aria_backend/README.md).

**Future work:** train a local Roman Urdu seq2seq transliterator to remove the LLM
dependency; investigate on-device inference; replace the ephemeral Colab tunnel with a
stable host; and consider a Flutter rewrite of the front end. Also calibrate verification
and watermark thresholds on representative data, add accessible alternatives to spoken
challenges, and implement optional microphone capture with deliberate recording controls.

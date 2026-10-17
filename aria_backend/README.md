# A.R.I.A — Local backend (Phases 2, 4 and 5)

This CPU-only FastAPI backend handles Roman Urdu conversion, text normalization,
chunking, encrypted voice profiles, audio assembly, and caching. It sends only reference
WAVs for enrollment and text/latents for synthesis to your configured Colab GPU server.
Voice enrollment and emotion-reference uploads accept WAV, MP3, M4A, AAC, OGG and FLAC;
the backend converts them in memory to the required mono WAV. See the
[conversion sample and command](../examples/audio/README.md).
Quick phrase listing and playback accept a `language` code (default `ur`). Groq translates
the original phrase meanings in batches, caches encrypted translations, and keeps generated
audio separate per language. Cards return `display_text` and `language`; playback returns
`X-Spoken-Text`, `X-Language` and `X-Model-Language`. Unsupported languages or failed translation
do not fall back to speaking Urdu. `PHRASE_TRANSLATION_TIMEOUT_SECONDS` defaults to 30 seconds
per batch; translated audio is generated on demand and reusable offline once cached.
The [Flet app](../aria_desktop/README.md) is available, and [Phase 4](../PHASE4.md) adds
phrase CRUD, prepared audio, favorites/recents, and local prediction. [Phase 5](../PHASE5.md)
adds optional watermarking, speech verification and emotion references. These flags are
off by default; there are no paid dependencies required to use the default setup.

For the current protected installation and API-first transliteration settings, use the
[latest setup guide](../UI_AND_SECURITY.md). Private configuration takes precedence over
the project `.env` when present. On this machine Groq is enabled, backend authentication
is required, and runtime data is outside the synced project folder.

## File tree

```text
aria_backend/
├── app/
│   ├── __init__.py, __main__.py, main.py, config.py, cli.py
│   ├── api/
│   │   ├── __init__.py, tts.py, voices.py, text.py, admin.py, health.py
│   │   └── phrases.py, predict.py       # Phrase CRUD/playback and local prediction
│   ├── db/
│   │   └── __init__.py, database.py     # SQLite/SQLAlchemy tables and sessions
│   └── services/
│       ├── __init__.py, errors.py, crypto.py, gpu_client.py
│       ├── transliteration.py, urdu_normalizer.py, chunker.py
│       ├── voice_store.py, audio_utils.py, cache.py
│       └── phrases.py, phrase_warmer.py, prediction.py, synthesis.py
├── data/
│   ├── roman_urdu_dictionary.json       # 2,826 Roman spellings
│   └── default_phrases.json             # 60 bilingual seeds for Phase 4
├── scripts/evaluate.py                 # Optional CPU CER/ECAPA evaluation
├── scripts/benchmark_predict.py        # Local HTTP latency measurement
├── tests/
│   └── conftest.py, test_api.py, test_services.py, test_evaluation.py, test_phase4.py
├── requirements.txt, requirements-eval.txt
├── .env.example, .gitignore
└── README.md
```

All code is supplied in these files. The normal server does not import PyTorch, Coqui,
Whisper, or SpeechBrain. The optional evaluation command imports its ML dependencies
only when run.

```text
Flet app --> Local FastAPI (CPU) --> Your Colab XTTS server (GPU)
                         |                   via HTTPS/cloudflared
                         +--> SQLite + Fernet-encrypted voice/audio/text data
                         +--> Dictionary and phoneme rules
                         +--> Groq ONLY with explicit enablement and LOCAL_ONLY=false
```

## Exact setup and run commands

Requires Python 3.10 or later; tested on Python 3.12. Start the
[Phase 1 notebook](../colab/ARIA_Colab_GPU.ipynb) through cell 6 first for live voice use.
Local transliteration and startup work while Colab is offline.

Windows PowerShell, from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r aria_backend/requirements.txt
Copy-Item aria_backend/.env.example aria_backend/.env
```

Edit [the environment template](.env.example)'s copied `.env` file. Set `COLAB_URL` and
`COLAB_API_KEY` from the notebook, and set `MODEL_VERSION` and `LANG_TAG` to match it.
Only perform the copy once so an existing configuration is not overwritten.
Keep `LANG_TAG=ar` for your Urdu fine-tune. All credentials come from environment/.env;
there are no production keys in source, examples, test output, or the notebook.

```powershell
Set-Location aria_backend
..\.venv\Scripts\python.exe -m app
```

Linux/macOS, from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r aria_backend/requirements.txt
cp -n aria_backend/.env.example aria_backend/.env
# Edit aria_backend/.env with your session URL/key.
cd aria_backend
../.venv/bin/python -m app
```

The default local URL is `http://127.0.0.1:8001`. Interactive API documentation is at
`http://127.0.0.1:8001/docs` when bearer auth is disabled. With `ARIA_KEY` configured,
all routes including documentation require the bearer header; use an HTTP client that
can send it. Run **one worker**: the in-memory locks, runtime configuration, and GPU
concurrency limits intentionally support one desktop user/process. Do not use reload
or multiple workers for the running app.

## API contracts

When `ARIA_KEY` is nonempty, send `Authorization: Bearer <environment value>` on every request.

| Method/route | Input | Output |
| --- | --- | --- |
| `POST /api/transliterate` | `{"text":"mujhe pani chahiye"}` | `original`, `urdu`, `method_used` |
| `POST /api/tts` | `text`, optional `voice_id` (default `default`), `speed`, `input_mode` (`auto`, `roman`, `urdu`) | Raw `audio/wav`, URL-encoded `X-Urdu-Text`, `X-Latency-Ms` |
| `POST /api/voices` | Multipart `file` WAV and `name` string | 201 with `id`, `name`, `created_at`, `model_version`, `needs_reenrollment` |
| `GET /api/voices` | None | Array of profile objects, additionally `is_default` |
| `DELETE /api/voices/{id}` | Voice UUID | 204; deletes profile and its cached audio |
| `DELETE /api/voices/all` | None | Deletes all profiles, retained recordings, audio cache and transliteration cache |
| `GET /api/health` | None | Local `ok`, `colab.reachable` with GPU status or failure detail, `model_version`, `local_only` |
| `POST /api/admin/colab-url` | `colab_url`, optional `colab_api_key` | `colab_url`, `updated`; never returns the key |

There is no bundled default voice. `default` chooses the oldest enrolled voice matching
the current model. A missing profile gives 404; an old-model profile gives 409 and requires
re-enrollment. Local health returns 200 even with Colab offline, with `colab.reachable=false`.
Text input is limited by `MAX_TEXT_CHARS`; exceptionally long individual words are rejected
instead of silently split. The header contains the normalized text actually spoken,
including numbers expanded to words; preview keeps digits intact.

### Update the Colab session without restarting

From the [backend folder](.):

```powershell
..\.venv\Scripts\python.exe -m app.cli set-colab-url https://YOUR-NEW-HOST.trycloudflare.com
```

If the notebook generated a new key, update `COLAB_API_KEY` in your local `.env` first,
then run:

```powershell
..\.venv\Scripts\python.exe -m app.cli set-colab-url https://YOUR-NEW-HOST.trycloudflare.com --update-key
```

Use `--backend http://127.0.0.1:8001` if necessary. On Linux use
`../.venv/bin/python` in these commands. Secrets are read from environment/.env and never
passed on the command line. The update is applied to the running process and stored
encrypted in SQLite; it takes precedence over `.env` on future starts. To replace a
stored value, run the command again. The administrative route waits for active voice
operations to finish, so an update never mixes GPU sessions within one synthesis.
Use a longer client timeout if updating during a long synthesis; the CLI defaults to 30 seconds.

### Small client smoke test

This example runs from the backend directory after you install the requirements. Replace
the reference path with a WAV you are allowed to use; it does not contain a literal API key.

```python
from pathlib import Path
import httpx
from app.config import Settings

settings = Settings()
key = settings.aria_key.get_secret_value()
headers = {"Authorization": f"Bearer {key}"} if key else {}
with httpx.Client(base_url="http://127.0.0.1:8001", headers=headers, timeout=300) as client:
    print(client.get("/api/health").json())
    with Path("reference.wav").open("rb") as source:
        response = client.post("/api/voices", data={"name": "My voice"},
                               files={"file": ("reference.wav", source, "audio/wav")})
    response.raise_for_status()
    voice_id = response.json()["id"]
    response = client.post("/api/tts", json={"text": "mujhe pani chahiye", "voice_id": voice_id})
    response.raise_for_status()
    Path("spoken.wav").write_bytes(response.content)
```

## Transliteration and audio behavior

The default dictionary-first order is script detection → clean Roman text → dictionary →
optional Groq → phoneme rules. The current private setup selects `TRANSLIT_STRATEGY=api_first`,
which tries Groq before dictionary/rules. Urdu/Arabic script already present causes passthrough, including mixed-script input,
as specified. `input_mode=urdu` also bypasses conversion; `roman` and `auto` retain the
script-detection safeguard. Dictionary conversion handles spelling variants word by word;
an unknown word can trigger Groq for the whole sentence. The 20 few-shot examples and
strict output/digit validation reject English explanations and malformed model output.
Missing keys, timeouts, rate limits, or invalid output fall back to local rules.

Groq uses `openai/gpt-oss-120b` by default, temperature 0, low reasoning effort, and a
512-token completion limit. Change the model through `GROQ_MODEL`. The compatible
endpoint and reasoning mode follow [Groq's model documentation](https://console.groq.com/docs/model/openai/gpt-oss-120b).
For optional usage, provide your own free-tier key, set `LLM_TRANSLIT_ENABLED=true`,
and set `LOCAL_ONLY=false`; no paid account or call is needed for the default path.
Availability and free-tier limits are controlled by Groq.

Every transliteration result is cached by a hash that includes its input and conversion
policy, dictionary revision, and Groq model. Switching to local-only mode cannot reuse
a result from the previously enabled LLM policy. Cached rule fallbacks remain until
eviction or deletion; a temporarily offline result will not be retried immediately.

Normalization maps Arabic letter variants to Urdu, removes tatweel/vocalization marks,
standardizes punctuation, and speaks integers, decimals, leading-zero identifiers, and
Arabic/Urdu digits as Urdu words. Roman spelling is ambiguous: dictionary and phoneme
rules cannot infer every intended word. Mixed script and proper names may need manual
Urdu corrections; this is a test implementation, not a validated language model.

The chunker respects `۔`, `؟`, `!`, question marks, and newlines, with up to 180 characters
per chunk and no broken words. `asyncio.gather` preserves order while the GPU client
limits concurrent requests to two. The Colab notebook serializes GPU execution.
Audio is resampled to 24 kHz by default, joined with 150 ms silence, RMS normalized and
peak limited. This is not a LUFS loudness meter. Changing speed, temperature, model
version, chunk settings, output rate, or voice invalidates the relevant audio cache key.

## Encryption, deletion, and privacy

Reference uploads accept WAV, MP3, M4A, AAC, OGG and FLAC, up to 30 minutes and 256 MiB.
The backend scans the source in bounded decoded blocks and selects a 6–30 second section
using silence and clipping checks, then converts it to 22.05 kHz mono PCM WAV before
`/latents`. Use one clear speaker; selection does not identify or separate speakers.
See [long audio and languages](../docs/LONG_AUDIO_AND_LANGUAGES.md) for limits and model language setup.
Neither multipart parsing nor processing writes a
temporary reference file. With `KEEP_RAW_AUDIO=false`, the original is forgotten after
enrollment. With it true, the **original** recording is stored as a Fernet-encrypted blob.

Voice latents, optional recordings, generated audio cache, transliteration cache values,
and runtime Colab credentials are encrypted in `data/aria.sqlite`. Profile names, model
versions, UUIDs, timestamps, and cache hashes are metadata stored in plaintext. Set
`FERNET_KEY` or keep the automatically generated `data/voices/.fernet.key` alongside a
database backup. Losing/changing the key prevents decryption; the app does not silently
replace a missing key when encrypted data exists. Restrict access to both database and
key; encryption does not protect against someone who can read both. POSIX key files use
mode 0600; Windows access follows the parent folder's ACL.

**Accurate privacy statement for this architecture:** Voice recordings and voice latents
are retained only on the user's machine, encrypted at rest when retained. Enrollment
necessarily sends a reference WAV to the user's Colab server to compute latents. Latents
and text are sent per synthesis request to that server and are not stored there by the
provided notebook. Typed text is sent to Groq only when `LLM_TRANSLIT_ENABLED=true`,
`LOCAL_ONLY=false`, and a key is available. With it off, transliteration and local processing
need no third-party inference service. `LOCAL_ONLY=true` disables those calls while
allowing the user's configured Colab server; Cloudflare/Google still provide transport
and hosting for that server. Package and optional evaluation-model downloads are setup
operations, not part of the speech request pipeline.

“Delete all” clears all stored user voice and text content, with SQLite secure deletion
enabled. It retains application settings, runtime connection credentials, and the key
so the configured app remains usable. Individual deletion also removes that voice's audio
cache and learning history. Phase 4 also clears custom/edited phrases, favorites, recents,
and prepared phrase audio, then restores the public seed bank and its baseline predictor.
Deletion cannot erase backups, synced copies, caller-saved WAV files, data already
transmitted to a provider, or guarantee physical overwrite on SSDs. A shared operation
lock prevents in-flight synthesis/enrollment from recreating deleted records afterward.

Logs contain only structured error event/type fields; raw text, recordings, latents,
upstream error bodies, and secrets are omitted. Request validation responses do not
echo submitted data. There is no request access log in the documented launch command.
Avoid adding request/body debug logging when running this app yourself.

Phase 5 additionally encrypts ECAPA enrollment embeddings and emotion-reference latents
and optional raw clips. Challenge recordings/transcripts and session tokens are not
persisted; challenges and hashed token state expire in memory. Voice deletion/delete-all
also removes these biometric/reference records and revokes their sessions. See the
[Phase 5 guide](../PHASE5.md) for best-effort limits and the distinction between a successful
watermark embedding operation and proof of provenance.

## Model swaps and troubleshooting

- Change `MODEL_PATH`, `CONFIG_PATH`, `VOCAB_PATH`, and `LANG_TAG` in Colab and reload
  its cells. Change `MODEL_VERSION` in both environments; restart the local backend for
  that configuration change. **Re-enroll voices because old latents are invalid for the
  new model.** Local profiles flag `needs_reenrollment`; the stateless Colab protocol
  cannot detect same-shaped latents from another checkpoint.
- `503 Colab server unreachable, restart the notebook and update the URL`: restart
  notebook serving and use the admin CLI. GPU transport retries transient failures with
  exponential backoff. A client timeout cannot cancel an already-running Colab CUDA call;
  retrying may repeat computation but creates no remote profile state.
- `502 Colab rejected the API key`: refresh the local key and run the CLI with `--update-key`.
  `502` for invalid upstream payloads can indicate mismatched model files or request limits.
- `422` enrollment: record continuous clear speech, reduce clipping/silence, check duration.
- `409` synthesis: re-enroll with the current model or choose a compatible profile.
- Encryption errors: restore the matching key; never replace it to try to decrypt old data.
- LAN access: later phone clients need the laptop's LAN IP; `127.0.0.1` on a phone points
  to that phone. Set `HOST=0.0.0.0`, configure `ARIA_KEY`, and permit the port on your LAN.
- Roman rules can pronounce unfamiliar names poorly. Enter corrected Urdu script when
  precise output matters. Number normalization reads long IDs digit by digit; it does not
  interpret dates, units, phone punctuation, or mathematical expressions semantically.

## Tests and acceptance checklist

Verified locally on Python 3.12: **50 backend tests plus 31 Phase 1 tests passed**
(`81 passed` combined). The backend checks include a real HTTP server process and CLI
runtime update. `pip check` reported no broken requirements. The installed Starlette
version emitted one non-failing TestClient/httpx deprecation warning.

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q aria_backend/tests
# Include the Phase 1 notebook suite if its test dependencies are installed:
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.\.venv\Scripts\python.exe -m pytest -q
```

- Normalizer: Arabic variants, diacritics, punctuation, numbers, decimals and leading zeros.
- Chunker: sentence boundaries, maximum length, no split words, oversized-word rejection.
- Transliteration: dictionary, LLM success, garbage/empty/failing/rate-limited responses,
  encrypted caching, and network suppression for missing keys/local-only/disabled LLM.
- Voice store: encrypted latent and optional raw-audio round trips, model mismatch,
  default voice selection, cache deletion, missing key handling, and delete-all.
- API: mocked GPU enrollment/tts, WAV headers and sample rate, ordered audio/silence,
  bounded concurrency, auth, sanitized errors, URL/key persistence and offline errors.
- On your Colab: enroll a real reference, listen to Roman and Urdu input, update the
  tunnel URL live, and confirm deleting a voice removes it from the app API.

These automated tests use mock GPU/LLM responses. They verify behavior, not Urdu
intelligibility, speaker fidelity, or real hosted-service availability.

## Optional full-pipeline evaluation

[scripts/evaluate.py](scripts/evaluate.py) sends each sentence through `/api/tts`, runs
faster-whisper `small` in CPU int8 mode, and computes ECAPA cosine similarity to your
reference. It writes a CSV with per-sentence CER/similarity and a JSON summary. CER
normalizes Urdu letters/numbers and removes punctuation/whitespace; corpus CER is
total character edits divided by total reference characters.

Install a matching **CPU** PyTorch/torchaudio pair in a separate evaluation environment
if you want to avoid adding ML packages to the normal backend environment, then:

```powershell
..\.venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
..\.venv\Scripts\python.exe -m pip install -r requirements-eval.txt
```

Create a JSON file containing your actual evaluation sentences, for example:

```json
[
  {"text": "mujhe pani chahiye", "urdu": "مجھے پانی چاہیے"},
  {"text": "aap kaise hain", "urdu": "آپ کیسے ہیں"}
]
```

Set `EVAL_WHISPER_MODEL` and `EVAL_SPEAKER_MODEL` to downloaded local model directories
for offline/local-only evaluation. Model downloads are denied by default. To download
on the first evaluation, explicitly pass `--allow-model-downloads` **and** temporarily
set `LOCAL_ONLY=false`; keep `LLM_TRANSLIT_ENABLED=false` if you still want local
transliteration. This evaluator setting does not reconfigure a running backend.

```powershell
..\.venv\Scripts\python.exe scripts/evaluate.py sentences.json --reference reference.wav --voice-id default --output evaluation.csv
```

The provided base-XTTS baseline is **CER 0.486 / speaker similarity 0.522 on 8 sentences**.
No new score is claimed here. A meaningful comparison requires the original eight
sentences, same reference audio, same ASR/ECAPA weights, and the same normalization.
Only metric helpers are unit tested locally; actual evaluator ML inference needs the
optional dependencies and downloaded weights. The report contains evaluation text;
store/share it deliberately.

References: [faster-whisper CPU API](https://github.com/SYSTRAN/faster-whisper),
[SpeechBrain ECAPA model](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb),
[HTTPX async clients](https://www.python-httpx.org/async/),
[Pydantic settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).

## Phase 2 assumptions

The local app is a single-user, single-process service. Colab supplies a matching XTTS
model and valid latent arrays. URL/key updates are the only runtime configuration changes;
other `.env` changes require restarting the backend. Profiles and caches are local SQLite
data, with bounded cache entry counts. Phrase CRUD/cache warming and online prediction
are implemented in [Phase 4](../PHASE4.md). Liveness, watermarking and emotion selection
are implemented behind flags in [Phase 5](../PHASE5.md), with best-effort guarantees and
separate local model requirements.

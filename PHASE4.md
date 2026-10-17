# Phase 4 — Quick phrases and local prediction

Phase 4 extends the existing backend and single-file Flet app. It adds a persistent bank
of 60 bilingual phrases, CRUD, favorites, recents, encrypted prepared audio per voice,
and Roman Urdu suggestion chips. [Phase 5](PHASE5.md) now adds optional safety features.

## Files delivered or extended

```text
proj/
├── PHASE4.md
├── aria_backend/
│   ├── app/
│   │   ├── config.py, main.py
│   │   ├── api/
│   │   │   ├── phrases.py, predict.py
│   │   │   └── tts.py, voices.py, admin.py
│   │   ├── db/
│   │   │   └── __init__.py, database.py
│   │   └── services/
│   │       ├── phrases.py, phrase_warmer.py, prediction.py, synthesis.py
│   │       └── voice_store.py, crypto.py
│   ├── data/default_phrases.json     # 60 existing seeds, now active
│   ├── scripts/benchmark_predict.py
│   ├── tests/test_phase4.py, tests/test_api.py
│   ├── .env.example
│   └── README.md
└── aria_desktop/
    ├── aria_app.py                  # Still one app source file
    ├── tests/test_desktop.py
    ├── pyproject.toml
    ├── .env.example
    └── README.md
```

Full implementations are in the listed files. No new runtime package is required.
SQLite adds the new tables on startup; existing voices and caches are retained.
The phrase seed runs only once. Deleting a built-in phrase does not resurrect it at the
next startup. “Delete all my data” resets the bank to its original built-in phrases.

## Exact run commands

Use your existing environment configuration from Phases 2 and 3. If setting up for the
first time, follow the [backend](aria_backend/README.md) and [app](aria_desktop/README.md)
setup guides to create their separate environment files; do not overwrite existing keys.

From the repository root, Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r aria_backend/requirements.txt -r aria_desktop/requirements.txt
# Terminal 1:
Set-Location aria_backend
..\.venv\Scripts\python.exe -m app
```

In a second terminal, from the repository root:

```powershell
.\.venv\Scripts\python.exe aria_desktop/aria_app.py
```

Linux/macOS equivalents:

```bash
.venv/bin/python -m pip install -r aria_backend/requirements.txt -r aria_desktop/requirements.txt
# Terminal 1, from the repository root:
cd aria_backend
../.venv/bin/python -m app
# Terminal 2, from the repository root:
.venv/bin/python aria_desktop/aria_app.py
```

Run the Colab notebook and configure its URL/key as before for new audio generation.
Already prepared phrases play while Colab is unavailable, provided the local backend,
encryption key, matching voice profile, and cached voice/speed/model combination exist.

## App workflow

- **Quick phrases:** scroll below the speech composer. Tap the bilingual phrase card
  once to speak it using the selected voice and speed. “Ready” means that exact variant
  is cached; “Prepare on tap” generates it on first use.
- **Favorites / recents:** tap a star to toggle a favorite. The “Show phrases” selector
  provides Favorites, Recently spoken (up to 20), or one of the five categories.
- **CRUD:** Add phrase opens Roman Urdu, Urdu script, and category fields. Edit opens
  the same form for an existing card. Save persists it; Delete removes it immediately.
  Both language fields are required and limited to 180 characters.
- **Prediction chips:** type Roman Urdu. Suggestions replace the final partial word;
  after a space, they add the next word. For example, `mujhe pa` → `pani` produces
  `mujhe pani `. Up to five chips appear, independently of transliteration. Urdu-script
  input suppresses Roman suggestions. Clicking a chip adds a word; it does not speak.
- **Voice changes:** selecting or enrolling a voice requests preparation for that voice.
  The idle UI refreshes ready indicators every 10 seconds by default. Speech at a custom
  speed is prepared on demand; background preparation uses `DEFAULT_SPEED`.

## API contracts

The same optional `Authorization: Bearer ...` protection applies to every new route.

| Route | Input | Response |
| --- | --- | --- |
| `GET /api/phrases` | Optional `voice_id=default`, `speed`, `category`, `favorites`, `recent` | `items`, resolved `voice_id`, `ready`, `total`, `warm_status` |
| `POST /api/phrases` | `{roman, urdu, category?}` | 201 with created phrase |
| `PATCH /api/phrases/{id}` | One or more of `roman`, `urdu`, `category`, `favorite` | Updated phrase |
| `DELETE /api/phrases/{id}` | None | 204 |
| `POST /api/phrases/{id}/speak` | `{voice_id?: "default", speed?: number}` | Raw WAV and `X-Urdu-Text`, `X-Latency-Ms`, `X-Audio-Cache: hit|miss` |
| `POST /api/phrases/warm` | `{voice_id?: "default"}` | 202 with `queued`, `voice_id`, default `speed`, `warm_status` |
| `GET /api/predict?prefix=...` | Roman text prefix, including any trailing space | `{prefix, suggestions: [word, ...]}` and `X-Prediction-Ms` |

Each phrase has `id`, `roman`, `urdu`, `category`, `favorite`, `last_used`, and `uses`.
List responses add a voice/speed-specific `cached` flag. Categories are `needs`, `medical`,
`family`, `greetings`, and `custom`, with 12 default phrases in each category. List without
an enrolled default voice still works; it returns `voice_id=null` and uncached cards.

`PATCH` rejects empty updates, explicit null fields, invalid categories, and blank/wrong
script text. Favorite flags are booleans. A nonexistent phrase gives 404; reaching
`PHRASE_MAX_COUNT` gives 409. Invalid inputs return sanitized 422 errors.

Warm status is `disabled`, `idle`, `warming`, `ready`, `waiting_for_gpu`, or `error`.
It describes the background worker; use each card's `cached` flag for the selected voice
and speed. A 202 response queues background work; it does not promise completion.

## Cache preparation and invalidation

The single background worker prepares all bank phrases for compatible voice profiles,
with the selected voice first and favorites first within a voice. It starts on backend
startup, enrollment, phrase edits, and explicit warm requests. Switching priority takes
effect after any current GPU operation finishes. Colab failures leave cached clips intact
and retry later. Updating the runtime URL wakes the worker; a request already sent to the
old URL may finish or time out before the next pass.

GPU generation runs outside the data lock. Before saving the result, the worker verifies
the phrase, voice, model/settings cache key, and invalidation generation again. Edits,
deletion, or “delete all” prevent an old in-flight result from restoring stale content.
Shutdown cancels the worker and closes its clients. There is no claim that disconnecting
a request cancels an already-running remote CUDA kernel.

Prepared audio uses its own encrypted table, so the ordinary TTS cache cannot evict the
phrase bank. Keys include phrase ID, voice ID, normalized Urdu, speed, model version,
temperature, and audio-processing defaults. Each phrase/voice retains the current
default-speed variant and up to two recent custom-speed variants. Phrase edits/delete
clear its prepared audio. Individual voice deletion removes its audio and learning history.

On a model swap, change `MODEL_VERSION` locally and reload the matching Colab files.
Old voice profiles are flagged for re-enrollment and cannot use their old cache. New
compatible voice profiles are warmed automatically. The backend does not reuse old
latents with new weights. Background preparation requires a live Colab server; it is not
instant on a cold start. A cache miss may also queue behind current GPU work.

## Prediction and privacy

The predictor is a local backoff trigram model built from the bank's Roman text and
bounded local speech history. History has double the corpus weight of a seed phrase.
It first tries the last two complete words, then one, then global word frequency,
filtering by the final partial token. Ties are deterministic. An immutable precomputed
prefix index makes each request a few dictionary lookups without a database/GPU lock.
Model replacements are built in a CPU thread and swapped in when ready.

Every successful `/api/tts` or phrase-speech response records one encrypted history row
and refreshes the model, including successful audio-cache hits. Failed synthesis and
background preparation do not count as spoken history. This records successful audio
delivery, not proof that the user heard or completed playback. Roman prediction learns
from Roman input and bilingual phrase labels; Urdu-only free text is retained as history
but is not reverse-transliterated into Roman training tokens. Training considers up to
128 tokens per utterance and ignores words longer than 40 characters.

Phrase text/category, learning history, and prepared WAVs are Fernet-encrypted in SQLite.
Favorite flags, IDs, counts, timestamps, voice IDs, and speed metadata remain plaintext.
The trained index is held in process memory. Predictions never call Groq or Colab.
Phrase synthesis uses the stored Urdu directly and never sends the Roman phrase to Groq.

Deleting a phrase removes it from the bank and its prepared audio; previously spoken
history may still contribute its words. **DELETE /api/voices/all** clears all personal
voices, recordings, caches, custom/edited phrases, favorites, recents and learning history,
then restores the public 60-phrase seed bank and rebuilds its baseline predictor. Connection
settings and the encryption key remain. It cannot erase backups or already-transmitted data.

## New settings

The complete templates remain [backend .env.example](aria_backend/.env.example) and
[app .env.example](aria_desktop/.env.example).

| Setting | Default | Effect |
| --- | --- | --- |
| `PHRASE_SEED_PATH` | Bundled `data/default_phrases.json` | Seed source, applied only to a new/reset bank |
| `PHRASE_MAX_COUNT` | 500 | Bounds bank size |
| `PHRASE_PREWARM_ENABLED` | true | Enables automatic preparation; false still permits on-tap generation |
| `PHRASE_WARM_RETRY_SECONDS` | 30 | Background rescan/retry interval |
| `PREDICTION_HISTORY_LIMIT` | 1000 | Old encrypted history rows are pruned |
| `ARIA_PREDICT_DELAY_MS` | 120 | App typing debounce before a suggestion request |
| `ARIA_PHRASE_REFRESH_SECONDS` | 10 | App refresh interval while idle |

All environment changes require restarting the relevant process, apart from the existing
Colab URL/key update route. Existing `.env` files need not add these keys to use defaults.

## Test commands and latency evidence

The combined repository suite passes **131 tests** (62 backend, 38 app, 31 notebook).
This includes 12 Phase 4 backend cases plus the new app interaction/contract checks.
The existing Starlette TestClient/httpx deprecation warning is non-failing.

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q aria_backend/tests/test_phase4.py aria_desktop/tests
.\.venv\Scripts\python.exe -m pytest -q
# With the backend running locally:
.\.venv\Scripts\python.exe aria_backend/scripts/benchmark_predict.py --requests 200
```

Use `.venv/bin/python` for Linux/macOS. The benchmark reads the optional API key from
the backend environment and prints aggregate timings only.

Measured locally on this machine with the real HTTP server and the 60-phrase bank,
over **200 requests**: median **1.05 ms**, p95 **1.45 ms**, maximum **2.04 ms** round trip;
p95 prediction-handler time **0.023 ms**. This meets the 50 ms target in this measurement.
It is not a real-time guarantee under arbitrary machine load or network conditions.
The 120 ms UI typing debounce is separate from server prediction latency.

Acceptance checklist:

- Bank contains 60 phrases in five categories; create/edit/delete and favorites persist.
- Deleted seed phrases remain deleted after restart; recents update after successful speech.
- First phrase speech misses cache; repeat uses cached WAV even with Colab offline.
- Different voice/speed/text/model cannot incorrectly reuse cached audio.
- Enrollment automatically warms the bank; edits regenerate affected clips.
- Cached playback and prediction work while a warm request is blocked on the GPU.
- Delete-all during warming cannot recreate deleted voice/audio/history data.
- Roman suggestions respect partial words, use history, survive restart, and reset with deletion.
- Flet supports one-tap cards, filters, favorite toggles, phrase editing, and suggestion insertion.
- On your real setup, let Colab finish warming and listen to a cached phrase from each category.

Automated audio tests use synthetic WAVs and mocked GPU inference. No real Urdu quality,
speaker-similarity, APK, or native audio-output result is claimed by those tests.

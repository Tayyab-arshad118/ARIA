# A.R.I.A — Every word, yours.

**Artificial Restoration of Individuals’ Audio**

ARIA lets someone type a message and hear it in a voice they have registered. It combines a desktop app, a local server on the user's computer, and an XTTS voice model running on a Colab GPU. Quick phrases, Roman-to-native-script conversion, and optional voice checks are included.

This is the main project handbook. Start with Chapters 1–6 to use the app. Later chapters explain the internals and maintenance. Every project folder also has a focused README explaining its files.

The working interface is **Python/Flet**. There is no separate Dart app to run. Model weights, private keys, personal recordings, and runtime databases are not included in Git. Automated tests verify software behavior; they do not establish the quality of your particular voice checkpoint.

## Contents

1. [What ARIA does](#chapter-1--what-aria-does)
2. [The three parts of the system](#chapter-2--the-three-parts-of-the-system)
3. [What you need](#chapter-3--what-you-need)
4. [Start on Windows](#chapter-4--start-on-windows)
5. [Set up Colab and connect it](#chapter-5--set-up-colab-and-connect-it)
6. [Use the app](#chapter-6--use-the-app)
7. [Voice registration and long recordings](#chapter-7--voice-registration-and-long-recordings)
8. [How text becomes speech](#chapter-8--how-text-becomes-speech)
9. [Languages and quick phrases](#chapter-9--languages-and-quick-phrases)
10. [Settings and keys](#chapter-10--settings-and-keys)
11. [Storage, privacy, and deletion](#chapter-11--storage-privacy-and-deletion)
12. [Optional safety and emotion features](#chapter-12--optional-safety-and-emotion-features)
13. [API reference](#chapter-13--api-reference)
14. [Manual setup and other devices](#chapter-14--manual-setup-and-other-devices)
15. [Tests and quality checks](#chapter-15--tests-and-quality-checks)
16. [Troubleshooting](#chapter-16--troubleshooting)
17. [Backups, updates, and model changes](#chapter-17--backups-updates-and-model-changes)
18. [Repository map and development](#chapter-18--repository-map-and-development)
19. [Glossary and current limits](#chapter-19--glossary-and-current-limits)

## Chapter 1 — What ARIA does

The normal flow is **connect → register/select a voice → choose a language → type → check the native text → speak**.

| Feature | What it means |
| --- | --- |
| Registered voices | Upload a suitable recording to create a reusable voice profile. |
| Two text fields | Type Roman text in one field; see and optionally edit native-script text in the other. |
| Multiple languages | Text preview supports the backend's known languages; speech depends on the loaded model. |
| Quick phrases | Tap a common phrase whose displayed meaning and speech follow the selected language. |
| Word suggestions | Local Roman Urdu suggestions complete words or propose the next word. |
| Audio conversion | WAV, MP3, M4A, AAC, OGG, and FLAC references are prepared locally. |
| Long recordings | Up to 30 minutes / 256 MiB of source audio by default; a short usable section is selected. |
| Cached speech | Previously generated matching audio can be reused. |
| Responsive interface | Separate welcome, connection, voice, compose, and phrase screens, with light/dark modes. |
| Optional checks | Watermarking, spoken challenges, and emotion references are independently configurable. |

Registration does not train a new voice model. It derives a reusable voice representation using your supplied checkpoint. The repository's example speech is synthetic demonstration material, not a personal voice profile.

## Chapter 2 — The three parts of the system

```text
You type or select a recording
             |
             v
Flet app on your computer
             |
             v
Local FastAPI backend -------- encrypted SQLite storage
       |              |
       |              +------- Groq: optional text conversion/translation
       v
Your Colab GPU server -------- XTTS model + temporary HTTPS tunnel
       |
       v
Audio returns through the backend to the app
```

**The app** displays controls, collects input, and plays audio. It talks only to the local backend.

**The backend** checks requests, converts recordings, prepares text, manages encrypted storage, and calls Colab/Groq. The normal backend does not load XTTS or need a local GPU.

**Colab** keeps the voice model in GPU memory, computes voice representations, and generates new speech. A temporary tunnel makes it reachable. New speech needs the GPU server; text preview can work while it is offline.

**Groq** handles optional text work. It does not clone voices. This project supports Groq keys, not xAI's similarly named Grok service.

## Chapter 3 — What you need

For the standard Windows setup:

- Python 3.12 with the Windows `py` launcher.
- Internet for initial dependencies and live cloud services.
- Your matching XTTS checkpoint, configuration, and vocabulary files.
- A Colab GPU runtime for new voice registration and new speech.
- A clear recording of one speaker that you are allowed to use.
- A Groq key if you want API-assisted script conversion and translated quick phrases.

The desktop dependencies pin Flet 0.28.3 and flet-audio 0.1.0. Install from the supplied requirements instead of choosing unrelated versions. Local CUDA is unnecessary for the usual desktop/backend setup.

Without Groq, local Urdu conversion and native-script input remain available. Without Colab, local text functions and matching cached speech remain useful, but new voice generation does not.

## Chapter 4 — Start on Windows

### Get the source

Download/extract the repository ZIP, or clone it:

```powershell
git clone https://github.com/Tayyab-arshad118/ARIA.git
Set-Location ARIA
```

### Open the launcher

Double-click [Start ARIA.bat](Start%20ARIA.bat). It:

1. Creates `.venv` if missing.
2. Installs backend/app dependencies when their requirements change.
3. Initializes protected local settings if missing.
4. Starts the local backend, waits for it to respond, and opens the desktop app.

You do not need to type a local server address or local bearer key for this standard installation. First launch can take longer because packages are installed. If startup fails, read the printed message rather than opening repeated copies.

The launcher uses port 8001 by default, prevents duplicate launcher instances, and can reuse a compatible responding backend. It does not kill unrelated processes occupying a port. Closing the app stops the backend that launcher started; a reused backend is left running. Startup logs go to `startup.log` in the active data folder.

To check installation/settings without opening the app, run from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts/launch_aria.py --check
```

The [launcher folder](scripts/README.md) explains each startup file.

## Chapter 5 — Set up Colab and connect it

### Open the notebook and provide the model

Upload [ARIA_Colab_GPU.ipynb](colab/ARIA_Colab_GPU.ipynb) to Google Colab. Select **Runtime → Change runtime type → GPU**. A T4 is the intended testing configuration.

Provide your matching `model.pth`, `config.json`, and `vocab.json`, normally in Google Drive. A vocabulary from another checkpoint may have incompatible token IDs or embedding sizes. This notebook performs inference, not training.

### Run the numbered cells

| Cell | What it does | What you do |
| --- | --- | --- |
| 1 | Install packages | Run in a fresh GPU runtime; restart if requested. |
| 2 | Mount Drive | Authorize access and locate your files. |
| 3 | Read paths, limits, and key settings | Set paths and copy the generated key when displayed. |
| 4 | Load model and tokenizer | Wait for loading and language checks to finish. |
| 5 | Define the inference API | Run after the model is loaded. |
| 6 | Start server and tunnel | Copy `COLAB_URL`; keep the runtime running. |
| 7 | Optional public-route self-test | Supply a short reference WAV and inspect/listen to the result. |
| 8 | Stop server and tunnel | Run only when finished, not during initial setup. |

In cell 3, set `MODEL_PATH`, `CONFIG_PATH`, and `VOCAB_PATH` to your actual files. `SAMPLE_REFERENCE_PATH` is for the short self-test WAV. Long-file selection happens in the local backend, not in this direct notebook self-test.

For this Urdu fine-tuning convention, keep **`LANG_TAG=ar`**. It is the checkpoint's training token, not an instruction to translate Urdu into Arabic. Logical app Urdu `ur` maps to that model tag. Other checkpoints need their own compatible configuration.

### Paste the two outputs into ARIA

Choose **Get started → Connect**, then enter:

1. **Key from cell 3:** the Colab API key. Its complete labelled output line is accepted.
2. **URL from cell 6:** the current HTTPS tunnel URL. A `COLAB_URL=` line is accepted.
3. **Groq key, optional:** enables API text conversion; blank keeps a saved key.

Choose **Check & connect**. The backend probes the proposed server before saving. A failed check leaves the previous connection intact. The updated notebook must advertise its language list.

These Connect fields are the correct place for Colab/Groq values. They are sent to and retained by the backend. **Advanced** is different: it configures the app's connection to the local backend, not the Colab tunnel.

### Reconnect after a Colab restart

The tunnel URL can change, and a new runtime may produce a new key. Paste both current outputs from the same notebook session. Do not combine a new URL with an old session's key. The desktop launcher cannot start or keep Colab alive for you.

See [the Colab folder guide](colab/README.md) for model assumptions and the direct GPU API.

## Chapter 6 — Use the app

### Welcome, status, and sizing

The welcome screen uses the supplied ARIA logo and “Every word, yours.” The two status pills separately report the local backend and voice server. A working backend does not necessarily mean Colab is online.

The app uses a centered phone-style layout. Short windows use compact spacing. Wheel/touch/keyboard scrolling still works for long content, while scrollbars are hidden. Continue stays at the bottom of voice selection.

### Register or select a voice

Select a saved profile, or choose **Add a voice**, enter a name, and select a recording. Then choose **Continue to speaking**. Profiles marked for re-enrollment belong to an incompatible model version.

The speed slider ranges from 0.5× to 2.0×. **Change voice** returns to selection. Verification and emotion-reference controls appear only when their backend features are enabled.

### Use the two text fields

1. Select **Speak in**: English, Urdu, or a language from More.
2. Type phonetic/Roman writing in the first field, such as `namaste` for Hindi.
3. The second field shows the native-script result, such as `नमस्ते`.
4. Check the result; edit that native field directly if needed.
5. Press **Speak**. **Stop** ends playback, not a model calculation already running in Colab.

A native edit leaves the Roman field unchanged, cancels pending conversion, and is used for speech. Editing Roman input again resumes conversion. Changing language resets the native-edit override. Old responses cannot overwrite newer/manual edits, and repeated suggestion taps are guarded against.

**Auto-convert** prepares the selected language's script. **Native script** uses text as written. English already written in English can look the same in both fields. The composer transliterates writing; it does not translate arbitrary sentences between languages.

### Use quick phrases

Open **Phrases**, select a language, and tap a card. The card and speech use that language. You can search, filter categories, star favorites, and view recently spoken phrases.

Quick phrases translate **meaning**: an Urdu request for water becomes an English request for water, rather than English letters spelling Urdu sounds. Their source collection/editor remains Roman Urdu plus Urdu. New target-language translations need Groq; translated text and generated audio are cached separately.

A ready indicator applies to the selected voice, language, speed, and compatible model/settings. It does not mean every variant is prepared.

## Chapter 7 — Voice registration and long recordings

```text
Upload → validate size/format → decode in bounded blocks → choose usable section
       → mono PCM16 WAV at 22.05 kHz → Colab /latents → encrypted voice profile
```

The backend chooses a reference window using non-silent audio and clipping checks. It does not identify different speakers, separate a conversation into people, or understand recording quality semantically. Use one clear speaker without background music.

| Default limit | Value | Meaning |
| --- | --- | --- |
| Source duration | 1,800 seconds | Up to 30 minutes of input audio. |
| Source size | 268,435,456 bytes | 256 MiB; this still limits long recordings. |
| Selected reference | 6–30 seconds | Only this section conditions the model. |
| Source channels | One or two | Mono/stereo input; prepared output is mono. |
| Source sample rate | 8–96 kHz | Outside the configured range is rejected. |
| Prepared reference | 22.05 kHz PCM16 WAV | Sent to Colab. |
| Concurrent uploads | One | Bounds simultaneous large upload/processing work. |
| Upload body deadline | 300 seconds | Limits how long the request can send its body. |

WAV, MP3, M4A, AAC, OGG, and FLAC are supported. PyAV decodes compressed audio locally; standard wheels normally do not need a separate ffmpeg executable. Playlists and remote audio URLs are not recordings accepted by this upload path.

A 30-minute recording is **not** sent in full to XTTS and is not used for training. Upload buffers remain in memory; decoded blocks are bounded, but increasing file-size limits still increases RAM needs. Too much silence/clipping, invalid values, unsupported formats, or insufficient usable audio can cause rejection.

To prepare a reference manually, from the repository root:

```powershell
.\.venv\Scripts\python.exe aria_backend/scripts/convert_audio.py "input.mp3" "output.wav"
```

This exports the selected section, not the full length of a long recording, and refuses to overwrite an existing output. See [the audio examples](examples/audio/README.md).

## Chapter 8 — How text becomes speech

1. **Preview:** the app briefly waits after typing. Urdu can use a dictionary/rules; Groq can prepare other scripts. The preview does not need an online GPU.
2. **Final wording:** manual native edits bypass conversion. The backend checks text size and model language support.
3. **Voice lookup:** it decrypts the chosen voice's representations. Strict mode checks the voice session.
4. **Cache lookup:** matching speech can be reused. Keys include voice, language/model tag, text, speed, model version, and processing settings.
5. **Chunking:** text is split into smaller sections, normally at sentence/word boundaries, with a default 180-character model request limit. Long Chinese/Japanese text can split by characters.
6. **Generation:** the backend sends text and voice representations to Colab. Local concurrency is bounded; actual GPU execution is serialized in the notebook.
7. **Assembly:** ordered chunks are resampled to 24 kHz, joined with a default 150 ms pause, and loudness-normalized with peak limiting.
8. **Optional processing:** emotion references may influence generation; outgoing audio can be watermarked. Strict authorization is checked again.
9. **Playback:** the returned WAV is played with a new audio control; old playback is stopped/released.

The default text limit is 2,000 characters. Long messages may require several GPU calls. Playback uses a completed WAV, not a streaming speech connection. Loudness processing is RMS-based rather than LUFS mastering.

## Chapter 9 — Languages and quick phrases

### Preview support is different from model support

The text layer knows Urdu, English, Hindi, Arabic, Spanish, French, German, Italian, Portuguese, Polish, Turkish, Russian, Dutch, Czech, Chinese, Japanese, Hungarian, and Korean. This does not prove that every checkpoint can speak all of them well.

The notebook reports `cfg.languages` through health. `SUPPORTED_LANG_TAGS` can restrict that list but cannot add a missing model language. The backend encrypts and remembers discovered tags; changing `MODEL_VERSION` invalidates remembered compatibility.

`LANGUAGE_ALIASES` maps app codes to checkpoint codes. The default maps logical Urdu `ur` to `LANG_TAG`, normally `ar` for this fine-tune. Advertise Arabic under that token only if your checkpoint genuinely supports it as intended.

### Local and API conversion

The dictionary contains 2,826 Roman spellings, including informal forms such as `me`. Rules approximate some unknown Urdu spellings. Word suggestions are local Roman Urdu predictions, not a multilingual language model.

Groq runs when the effective settings enable it and provide a key. `api_first` tries it before Urdu dictionary fallback; `dictionary_first` uses fully recognized local input first. Non-Urdu API conversion reports a failure instead of silently pretending a failed conversion succeeded. Native-script input remains available.

Check names, numbers, and wording before speaking. English and other Latin-script languages may already be in their normal alphabet. Selecting Hindi and entering `namaste` is a clearer script-conversion demonstration than entering an English sentence while English is selected.

### Phrase storage and preparation

The built-in collection has 60 phrases across needs, medical, family, greetings, and custom categories. It seeds once. Deleting a built-in phrase does not restore it at every restart; delete-all resets the collection to its defaults.

Translation uses Groq batches of up to 30 source phrases, with a separate default timeout of 30 seconds per request. Results are encrypted and keyed by source wording and target language. Editing the source produces a new translation. Missing access or failed translation does not silently play Urdu instead.

The background warmer prepares default Urdu phrase audio for compatible voices when enabled. Other languages are generated on demand. Prepared phrase audio is separate from the general speech cache and keeps the default-speed variant plus bounded recent speed variants per voice/phrase/language. Edits/deletions invalidate affected audio. In-flight jobs re-check state before saving so outdated work cannot restore deleted results.

### Offline behavior

| Situation | Expected result |
| --- | --- |
| Colab offline, Groq working | Preview can work; new model speech cannot. |
| Groq unavailable, Urdu input | Local dictionary/rules may still work. |
| Native-script input | No conversion needed; uncached speech still needs Colab. |
| Matching audio already cached | Playback can work without new GPU generation. |
| Phrase translation cached but audio missing | Words may be available; generating audio still needs the model. |
| Strict verification enabled | Cached speech still requires a valid voice-bound session. |

## Chapter 10 — Settings and keys

### The keys serve different purposes

| Value | Purpose | Where it belongs |
| --- | --- | --- |
| Colab URL | Address of the running GPU server | Normal Connect screen. |
| `COLAB_API_KEY` | Authorizes that Colab session | Connect; sent upstream as `x-api-key`. |
| `GROQ_API_KEY` | Authorizes API text work | Optional Connect field or protected backend configuration. |
| `ARIA_KEY` | Authorizes app access to the local backend | Generated/shared by setup; Advanced for custom clients. |
| `FERNET_KEY` | Encrypts/decrypts stored data | Backend configuration or generated local key file; never a Connect field. |

The app temporarily holds entered Colab/Groq values to send the setup request. The backend stores successful connection values encrypted. Entered secret fields are cleared after successful connection or leaving that screen; they are not written into repository files.

### Configuration precedence

The backend chooses an environment file in this order:

1. `ARIA_BACKEND_ENV_FILE`, if set.
2. Private `ARIA/config/backend.env`, if present.
3. Project `aria_backend/.env`.

The app uses `ARIA_APP_ENV_FILE`, then private `ARIA/config/desktop.env`, then project `aria_desktop/.env`. Process environment values override the chosen file.

On Windows, private files normally live under `%LOCALAPPDATA%\ARIA\config`. Other-platform discovery uses `LOCALAPPDATA`, then `XDG_CONFIG_HOME`, or a home `.config` fallback, as implemented in the settings modules.

**Saved runtime connections are another layer.** Colab settings saved through Connect are loaded from the encrypted database. A saved Groq key also enables API-first text behavior at startup. Therefore, editing `.env` or `LOCAL_ONLY` alone may not override a saved integration. Check both the chosen file and stored runtime settings when diagnosing conflicts. There is no separate in-app clear-Groq-key control yet.

### Common settings

| Group | Settings | Defaults or purpose |
| --- | --- | --- |
| Local server | `HOST`, `PORT` | `127.0.0.1`, `8001`. |
| Access | `ARIA_KEY`, `REQUIRE_AUTH`, `ALLOWED_HOSTS`, `ALLOWED_ORIGINS` | Base development defaults are permissive; the private helper creates a strong token and loopback restrictions. |
| API text | `LLM_TRANSLIT_ENABLED`, `LOCAL_ONLY`, `TRANSLIT_STRATEGY`, `GROQ_MODEL` | Off/local by default; model default `openai/gpt-oss-120b`. Connect can enable API-first behavior. |
| Model identity | `MODEL_VERSION`, `LANG_TAG`, `LANGUAGE_ALIASES` | Controls compatibility and language mapping. |
| Storage | `DATA_DIR`, `FERNET_KEY`, `KEEP_RAW_AUDIO` | Location, encryption, optional originals; raw retention is false by default. |
| Text | `MAX_TEXT_CHARS`, `CHUNK_MAX_CHARS` | 2000 and 180. |
| Uploads | `MAX_SOURCE_SECONDS`, `MAX_UPLOAD_BYTES`, `MAX_REQUEST_BYTES` | 1800 seconds, 256 MiB source, 258 MiB multipart request. |
| Resource bounds | `MAX_JSON_BYTES`, `MAX_PARALLEL_UPLOADS`, `MAX_INFLIGHT` | 1 MiB JSON, one upload, eight requests. |
| Timeouts | `GPU_TIMEOUT_SECONDS`, `GROQ_TIMEOUT_SECONDS`, `PHRASE_TRANSLATION_TIMEOUT_SECONDS` | 120, 10, and 30 seconds. |
| Caches | `AUDIO_CACHE_ENTRIES`, `TRANSLIT_CACHE_ENTRIES` | 100 general audio entries and 5000 text entries. |
| Optional features | `SECURITY_MODE`, `WATERMARK_ENABLED`, `EMOTION_ENABLED` | Off by default. |
| App | `ARIA_PREVIEW_DELAY_MS`, `ARIA_REQUEST_TIMEOUT_SECONDS`, `ARIA_MAX_UPLOAD_BYTES` | 450 ms, 300 seconds, 256 MiB. |

All supported settings are listed in [the backend example](aria_backend/.env.example) and [the desktop example](aria_desktop/.env.example). Keep upload limits consistent between client and server. Increasing source duration does not require a longer conditioning window; changing the selected window also requires matching notebook limits.

## Chapter 11 — Storage, privacy, and deletion

### Where information goes

New runtime data normally lives under `%LOCALAPPDATA%\ARIA\data` with the private Windows setup. The setup helper preserves an existing project database location when appropriate. Without that setup, the backend defaults to `aria_backend/data`. Check active `DATA_DIR` rather than guessing.

| Information | Location/use |
| --- | --- |
| Original recording | Prepared in local memory; saved encrypted only when `KEEP_RAW_AUDIO=true`. |
| Selected reference WAV | Sent to your Colab server to compute voice representations. |
| Voice representations | Encrypted locally; sent to Colab during synthesis. |
| Message text | Local backend, Colab for speech, and Groq when API text conversion is enabled. |
| Phrase translations/history/audio caches | Encrypted local database contents. |
| Credentials | Protected configuration and/or encrypted runtime settings. |
| Names, IDs, versions, timestamps, cache hashes | Some metadata is plaintext. |
| Challenge recordings/session tokens | Temporary memory; enrollment verification vectors are encrypted. |

The database is `aria.sqlite`. Without a supplied `FERNET_KEY`, the generated key is `voices/.fernet.key` under `DATA_DIR`. Back up the database and correct key together. Anyone who can read both can decrypt the records; encryption is not a replacement for operating-system access controls.

### Request protection

The backend applies configured bearer authentication, host/origin restrictions, size/time limits, admission/rate limits, and sanitized errors. API documentation is disabled by default. Private setup is stronger than bare development defaults. Use one backend process: locks, budgets, and verification sessions are process-local.

The notebook uses a separate API key, bounded requests, validated array shapes/types without pickle loading, serialized GPU work, and no user voice database. Google Colab, Cloudflare, and enabled Groq are external services; the complete workflow is not entirely on-device.

### Deletion and backups

Deleting one voice removes associated audio, learned history, verification baseline, and emotion references. Delete-all removes personal voice/audio/text/history records, revokes sessions, and resets phrases. Runtime connection settings and the encryption key remain so the installation can still function.

Deletion does not erase external backups, source files kept elsewhere, or third-party copies. Do not delete the encryption key as a routine reset: startup refuses to silently replace a missing key while encrypted records remain.

Git ignores private environments, keys, databases, personal recordings, model weights, logs, and caches. The audio under `examples/audio` is an intentional synthetic sample exception. Keep the bundled font license with the font.

## Chapter 12 — Optional safety and emotion features

These backend features are not needed for ordinary speech. They require additional local CPU dependencies/models. Preparation commands are in [backend scripts](aria_backend/scripts/README.md).

### Watermarking

`WATERMARK_ENABLED=true` applies AudioSeal after audio assembly, including cache hits. Internal caches hold pre-watermark audio. `X-ARIA-Watermark` reports `embedded`, `unavailable`, or `disabled`.

Unavailable embedding can return normal audio with the unavailable status. Unavailable detection reports an error rather than a false negative. The public 16-bit marker is not a cryptographic signature or proof of ownership. Editing or re-encoding audio can affect detection.

### Spoken challenge verification

| Mode | Behavior |
| --- | --- |
| `off` | No speech gate or verification baseline at enrollment. |
| `basic` | Enrollment can store a baseline; verification is optional. |
| `strict` | Speech and relevant reference actions require a valid voice-bound session, including cached speech. |

The user records the displayed Urdu challenge and uploads a short WAV. Local Whisper checks the words; ECAPA checks speaker similarity. Both checks must pass. Challenges are single-use, normally expire within 60 seconds including verification time, and successful sessions normally last 300 seconds. The app sends the token as `X-ARIA-Session`.

Re-enroll after enabling verification if a voice lacks its baseline. Missing models cause an error rather than a silent bypass. These checks do not prove consent or defeat every spoof. Strict spoken challenges can be unsuitable for users unable to produce the required speech.

### Emotion references

`EMOTION_ENABLED=true` enables neutral, happy, sad, calm, and angry styles. A small local Urdu/Roman-oriented lexicon chooses a tag, optionally swaps to a matching voice reference, and makes modest speed/temperature changes. It is not general multilingual emotion understanding or a guaranteed XTTS emotion control.

Uploads use the same supported formats and long-source preparation as enrollment. Verification, when enabled, also checks speaker matching. Replacing a reference invalidates affected audio caches.

## Chapter 13 — API reference

### Local backend

Paths below are relative to `http://127.0.0.1:8001`. Send `Authorization: Bearer <ARIA_KEY>` when configured. Strict mode also needs `X-ARIA-Session` for the chosen voice.

| Method and route | Purpose |
| --- | --- |
| `GET /api/health` | Backend/GPU state, model version, language catalogs, upload limits, and feature flags. |
| `GET /api/languages` | Model-advertised speech languages, including remembered discovery. |
| `POST /api/transliterate` | Convert `{text, language?, input_mode?}`; no GPU needed for known preview languages. |
| `POST /api/tts` | Speak `{text, voice_id?, speed?, language?, input_mode?}`; returns WAV bytes. |
| `GET /api/voices` | List metadata and compatibility flags. |
| `POST /api/voices` | Enroll multipart audio `file` and a `name`. |
| `DELETE /api/voices/{voice_id}` | Remove a voice and associated records. |
| `DELETE /api/voices/all` | Delete personal data and reset phrases. |
| `POST /api/admin/connect` | Check/save `{colab_url, colab_api_key, groq_api_key?}`. |
| `POST /api/admin/colab-url` | Save a URL and optional key without the full connection probe. |
| `GET /api/phrases` | List/filter by `voice_id`, `speed`, `language`, `category`, `favorites`, `recent`. |
| `POST /api/phrases` | Create `{roman, urdu, category?}`; source fields have a 180-character limit. |
| `PATCH /api/phrases/{id}` | Change source wording, category, or favorite status. |
| `DELETE /api/phrases/{id}` | Remove a phrase and prepared audio. |
| `POST /api/phrases/{id}/speak` | Speak with `{voice_id?, speed?, language?}`. |
| `POST /api/phrases/warm` | Request background preparation; non-Urdu variants are on demand. |
| `GET /api/predict?prefix=...` | Up to five local Roman Urdu suggestions. |
| `POST /api/liveness/challenge` | Create a challenge for `{voice_id?}`. |
| `POST /api/liveness/verify` | Verify multipart WAV `file` and `challenge_id`. |
| `POST /api/watermark/detect` | Inspect multipart WAV `file`. |
| `GET /api/voices/{voice_id}/emotions` | List emotion references. |
| `POST /api/voices/{voice_id}/emotions/{emotion}` | Upload a style reference. |
| `DELETE /api/voices/{voice_id}/emotions/{emotion}` | Remove a style reference. |

Input modes are `auto`, `roman`, `urdu` (legacy), and `native`. The UI mainly exposes Auto-convert and Native script. Default logical language is `ur`. Phrase results add `display_text`, `language`, and `cached`.

Speech headers include percent-encoded `X-Spoken-Text`, `X-Language`, `X-Model-Language`, latency, and optional-feature status. `X-Urdu-Text` remains a compatibility header. Phrase speech adds `X-Audio-Cache: hit|miss`.

Common HTTP statuses:

- **401:** local authentication failed.
- **403:** origin or verification restrictions.
- **404:** requested record not found.
- **409:** incompatible/changed state, such as a voice needing re-enrollment.
- **410:** expired or used challenge.
- **413:** request/file too large.
- **422:** invalid fields, values, or unsupported input.
- **429:** admission/rate limit or busy server.
- **502/503:** upstream or optional-service problems.

Checked Connect returns specific error codes for rejected keys, unreachable servers, invalid responses, model mismatch, and old notebooks. See [the API folder](aria_backend/app/api/README.md) for route-to-file navigation.

### Colab API

Colab uses `x-api-key`, not the local bearer token.

| Route | Input/output |
| --- | --- |
| `GET /health` | Readiness, GPU name, default tag, and supported languages. |
| `POST /latents` | Multipart short WAV; returns base64 NumPy voice arrays. |
| `POST /synthesize` | Text, voice arrays, optional language/speed/temperature; returns `wav_b64` and sample rate. |

The backend normally calls these endpoints. The app must not treat the Colab tunnel as its local backend address.

## Chapter 14 — Manual setup and other devices

### Windows developer setup

From the repository root, create the environment only if it is missing:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r aria_backend/requirements.txt -r aria_desktop/requirements.txt
.\.venv\Scripts\python.exe aria_backend/scripts/configure_local.py --no-prompt
```

The helper initializes/shares protected settings. Without `--no-prompt`, it also offers a hidden Groq-key prompt. Do not replace a working encryption key or configuration casually.

Terminal 1, from the repository root:

```powershell
Set-Location aria_backend
..\.venv\Scripts\python.exe -m app
```

Terminal 2, from the repository root:

```powershell
.\.venv\Scripts\python.exe aria_desktop/aria_app.py
```

If you deliberately use project `.env` files instead, copy the two examples only when no real file exists. Private configuration takes precedence. Match the app/backend `ARIA_KEY`.

### Linux/macOS

The batch/PowerShell launcher is Windows-specific. Use separate terminals:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r aria_backend/requirements.txt -r aria_desktop/requirements.txt
.venv/bin/python aria_backend/scripts/configure_local.py --no-prompt
# Terminal 1:
cd aria_backend
../.venv/bin/python -m app
# Terminal 2, starting from the repository root:
.venv/bin/python aria_desktop/aria_app.py
```

Native audio/file-picker dependencies vary by platform. These commands explain the layout, not a claim that every operating system has been acceptance-tested.

### Update a tunnel from the command line

From the backend folder:

```powershell
..\.venv\Scripts\python.exe -m app.cli set-colab-url https://YOUR-TUNNEL.trycloudflare.com --update-key
```

Replace the placeholder URL. `--update-key` reads the key from backend settings; do not put the real key into the command line. Unlike checked Connect, this route saves without probing the model first.

### Phone layout and Android

A phone-style desktop layout does not automatically install an Android app. The [Flet build configuration](aria_desktop/pyproject.toml) specifies entry point, dependencies, assets, and network permission. APK creation requires the appropriate Flet/Android build environment and device testing.

The [desktop packaging instructions](aria_desktop/README.md#optional-android-packaging) give the build commands and explain why the app must be packaged from its own directory.

A phone's `127.0.0.1` refers to the phone, not the laptop. A phone client using a laptop backend needs deliberately configured binding, a strong bearer key, allowed hosts, firewall/network access, and the laptop's reachable address in Advanced. Protect public/untrusted network traffic with HTTPS. The default launcher is a loopback desktop setup, not public hosting.

## Chapter 15 — Tests and quality checks

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r aria_backend/requirements.txt -r aria_desktop/requirements.txt -r requirements-test.txt
.\.venv\Scripts\python.exe -m pytest aria_backend/tests aria_desktop/tests tests -q
```

For a focused check:

```powershell
.\.venv\Scripts\python.exe -m pytest aria_desktop/tests -q
.\.venv\Scripts\python.exe -m pytest aria_backend/tests -q
.\.venv\Scripts\python.exe -m pytest tests/test_colab_notebook.py -q
```

Backend tests use temporary data and fake GPU/services. Desktop tests use real Flet controls with fake page/transport objects. Notebook tests execute cells with fake model/CUDA objects, without loading your checkpoint.

Coverage includes language routing, conversion, independent native editing, stale-response handling, cache separation, upload limits, encryption/deletion, authentication, phrases, and optional safety control flow. These tests do not measure real voice quality or clinical suitability.

[Capture helpers](aria_desktop/tests/README.md) record a running local preview at phone sizes. Screenshots are snapshots, not inference benchmarks. The optional [evaluation script](aria_backend/scripts/README.md) measures transcription error and speaker similarity using separately installed models and your evaluation data.

## Chapter 16 — Troubleshooting

| Symptom | Likely cause and next step |
| --- | --- |
| Python missing | Install/configure Python 3.12 and the `py` launcher. |
| First launch takes time | Dependencies may be installing; read output rather than starting repeated copies. |
| Port 8001 occupied | Close the previous manually started backend or change both client/server settings. |
| Backend key rejected | App/server `ARIA_KEY` differs, or the wrong settings file is active. |
| Backend connected, GPU offline | Run Colab through cell 6 and update both outputs. |
| Colab key rejected | Use the key from the same session as the URL. |
| Notebook update required | Load the supplied notebook and rerun model/API/server cells. |
| Model mismatch | Check `LANG_TAG`, model/config/vocabulary compatibility, and model version. |
| Preview language works but speech fails | The checkpoint may not advertise/support that language. |
| English result unchanged | English already uses Latin letters; both fields may legitimately match. |
| Phonetic text stays unconverted | Check Groq and Auto-convert; Native script intentionally bypasses conversion. |
| Conversion unavailable | Check Groq credentials, network/provider limits, and effective saved settings. |
| Native edit stops automatic updates | Intentional override: edit Roman input or change mode/language to resume conversion. |
| Reference rejected | Check clear single-speaker audio, silence/clipping, duration/size, channels, and rate. |
| Voice needs re-enrollment | Model version changed or an optional verification baseline is missing. |
| Cached speech asks for verification | Strict sessions apply to cache hits too. |
| Challenge fails/expires | Use the exact current prompt and intended speaker; check time limits and local models. |
| Encrypted data unreadable | Restore the original key paired with the database; do not generate a replacement over existing data. |
| No sound after speech succeeds | Check output device/volume and playback status; stop and retry. |
| Settings edits ignored | Check explicit overrides, private file precedence, and saved runtime connections. |
| No visible scrollbar | Intentional: wheel/touch/keyboard still scroll long content. |

## Chapter 17 — Backups, updates, and model changes

### Back up the installation's data

Stop the backend, then back up the active runtime directory and its matching encryption key. Preserve private environment configuration separately with restricted access. A source-code clone alone does not restore profiles.

Keep backups out of Git. Prefer a clean backend shutdown before copying SQLite, rather than copying a live database midway through writes or omitting necessary sidecar files.

### Update application code

Close the app/launcher, update the source, and restart. The Windows helper detects changed requirement files. Keep data and personal settings separate from source updates; do not overwrite them with examples.

### Replace the model

1. Update Colab with matching checkpoint/config/vocabulary files.
2. Verify training tag and supported languages.
3. Set a new deliberate local `MODEL_VERSION`.
4. Reload the model/API/tunnel and reconnect.
5. Re-enroll voices; old arrays may be incompatible even if their shapes match.
6. Listen to real output in each intended language.

A tunnel URL change alone is not a model change. New emotion references or processing settings affect relevant cache keys. Replacing verification weights also requires compatible verification versions/baselines.

## Chapter 18 — Repository map and development

| Folder | What its README explains |
| --- | --- |
| [aria_backend](aria_backend/README.md) | Local server setup and implementation map. |
| [Backend app](aria_backend/app/README.md) | Configuration, startup, lifecycle, shared services. |
| [API](aria_backend/app/api/README.md) | HTTP handlers and response conventions. |
| [Database](aria_backend/app/db/README.md) | Tables, persistence, encryption boundaries. |
| [Services](aria_backend/app/services/README.md) | Text/audio/voice/cache/phrase/safety processing. |
| [Backend data](aria_backend/data/README.md) | Bundled resources versus private runtime data. |
| [Backend scripts](aria_backend/scripts/README.md) | Setup, conversion, benchmarking, model preparation, evaluation. |
| [Backend tests](aria_backend/tests/README.md) | Feature-to-test mapping. |
| [aria_desktop](aria_desktop/README.md) | Flet UI, state, configuration, packaging. |
| [Desktop tests](aria_desktop/tests/README.md) | UI regressions and screenshot tools. |
| [colab](colab/README.md) | GPU notebook and direct inference API. |
| [docs](docs/README.md) | Documentation organization and visuals. |
| [Screenshots](docs/screenshots/README.md) | Image gallery, viewport naming, limitations. |
| [examples](examples/README.md) | Demonstration material. |
| [Audio examples](examples/audio/README.md) | Synthetic MP3/WAV and conversion. |
| [scripts](scripts/README.md) | Local launcher and process ownership. |
| [tests](tests/README.md) | Notebook contracts and test dependencies. |

When changing a feature, update its implementation, relevant tests, example settings where needed, and its folder README. Keep this handbook about current behavior, not the history of implementation phases. Avoid adding a competing setup guide.

There is no separate Flutter prototype folder. Flet's internal rendering/build technology is not a second app you need to maintain.

## Chapter 19 — Glossary and current limits

| Term | Meaning here |
| --- | --- |
| Backend | Local Python server used by the app. |
| GPU server | Colab process running the voice model. |
| Checkpoint | Saved model weights, supplied separately. |
| Tokenizer/vocabulary | Model-specific mapping between text and token numbers. |
| Latents/embedding | Numeric representations derived from a recording. |
| Transliteration | Phonetic writing in another script: `namaste` → `नमस्ते`. |
| Translation | Changing language while preserving meaning. |
| Native script | The usual writing system of a language. |
| Cache | Saved results that avoid repeating work. |
| Tunnel | Temporary HTTPS address forwarding to Colab. |
| Bearer token | Key sent in a header to authorize a local API request. |
| Encryption at rest | Stored contents are encrypted; different from network encryption. |
| Re-enrollment | Creating a new compatible voice/baseline after model changes. |

ARIA is a development/research application with implemented workflows. Real checkpoint quality, language intelligibility, speaker similarity, optional verification reliability, watermark robustness, and Android distribution need separate acceptance checks. It does not provide continuous training, speaker separation, guaranteed emotion control, built-in microphone capture, or permanent hosted inference. Colab/tunnel availability and API limits can affect operation.

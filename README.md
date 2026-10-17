# A.R.I.A — Artificial Restoration of Individuals' Audio

Start here: double-click [Start ARIA.bat](Start%20ARIA.bat), then paste the two Colab outputs in the app.
Latest: [flat light/dark design, transparent logo and offline language preview](docs/DESIGN_UPDATE.md).
See the [simple startup guide](docs/EASY_START.md) for the welcome, connection and voice setup flow.
Also available: [long recordings and model language selection](docs/LONG_AUDIO_AND_LANGUAGES.md).
Also available: [Groq-first conversion, the Apple-inspired interface and backend hardening](UI_AND_SECURITY.md).
This machine reads its protected configuration outside the OneDrive project. The dictionary
now contains 2,826 Roman spellings, including `me` → `میں`.

Phase 1 delivers a complete, self-contained Colab notebook for the Urdu XTTS GPU server.
Phase 2 is implemented in [aria_backend](aria_backend/README.md): local FastAPI, Roman Urdu
conversion, encrypted voice storage, audio caching, runtime GPU configuration, and tests.
Use that guide for the Phase 2 file tree, exact run commands, API contracts, and checklist.
Phase 3 is implemented in [aria_desktop](aria_desktop/README.md): a single-file Flet app
with Urdu preview, voice enrollment, playback, connection settings, and Android build configuration.
Phase 4 adds [quick phrases and prediction](PHASE4.md): CRUD, favorites/recents,
prepared audio per voice, and local next-word chips.
Phase 5 adds [optional CPU safety features](PHASE5.md): AudioSeal watermarking,
challenge-response verification and emotion-reference selection. All five code phases
are implemented; the Phase 5 guide includes final assumptions, limitations and future work.
Final local verification: **153 tests passed**, with mocked GPU/safety engines. Real
checkpoint inference, optional safety-model quality, native audio and APK testing remain
external acceptance steps; see the Phase 5 setup guide before enabling those flags.
The sections below describe Phase 1.

## Files

```text
proj/
├── colab/
│   └── ARIA_Colab_GPU.ipynb       # All installation, server, tunnel, and self-test code
├── tests/
│   └── test_colab_notebook.py    # Executes actual notebook cells with a fake GPU/model
├── requirements-test.txt        # CPU-only local verification dependencies
├── .gitignore
└── README.md
```

The full implementation is in [the notebook](colab/ARIA_Colab_GPU.ipynb). It does not import
server code from this repository: uploading this single notebook to Colab is sufficient.

## Architecture

```text
Future Flet app --> Future local FastAPI backend --> HTTPS quick tunnel --> Colab T4
                        |                                  |                 |
                 local voice profiles              Cloudflare transport   XTTS model
                 encryption/cache/SQLite                                  from Drive

Phase 1:                          GET /health      POST /latents      POST /synthesize
```

## Run in Colab

1. Open [Google Colab](https://colab.research.google.com/), choose **File → Upload notebook**,
   and upload [ARIA_Colab_GPU.ipynb](colab/ARIA_Colab_GPU.ipynb).
2. Select **Runtime → Change runtime type → T4 GPU**. Run numbered cells **1–2** to
   install packages and authorize Drive. If prompted to restart after installation,
   restart the runtime and continue with cell 2.
3. Put your matching `model.pth`, `config.json`, and `vocab.json` together in Drive.
   Adjust `MODEL_PATH`, `CONFIG_PATH`, and `VOCAB_PATH` in cell **3** to their mounted
   paths. Keep `LANG_TAG=ar` for this Urdu fine-tune and its 11 added tokenizer characters.
   Set `SAMPLE_REFERENCE_PATH` to a real 6–30 second WAV for the self-test.
4. Run cells **3–6**. Copy the randomly generated key shown once by cell 3 to the future
   local backend environment as `COLAB_API_KEY`. Copy cell 6's public URL as `COLAB_URL`.
   Never paste the actual key into notebook source. Environment-supplied `API_KEY` is
   accepted without printing it. Existing environment values override cell defaults.
5. Run cell **7** to check the public route, authorization, enrollment, and Urdu synthesis.
   Listen to the result and assess voice similarity and intelligibility yourself.
6. Cell **8** shuts down the server and tunnel. Run it only when finished; **Run all** will
   also execute shutdown. To resume, run cell 6 again.

The notebook downloads the Linux AMD64 cloudflared binary and uses an account-free
quick tunnel. URLs change between sessions and have no uptime guarantee.
See [Cloudflare's quick-tunnel documentation](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

## API contracts

All routes require `x-api-key`. No documentation endpoint is published.

| Route | Request | Success response |
| --- | --- | --- |
| `GET /health` | Header only | `ok`, GPU name, default `lang`, and configured `languages` list |
| `POST /latents` | Multipart WAV field named `file` | `gpt_cond_latent`, `speaker_embedding` as base64 `.npy` strings |
| `POST /synthesize` | `text`, both latent strings, optional `language`, `temperature` and `speed` | `wav_b64` (base64 PCM16 WAV), `sr` |

NumPy serialization/deserialization uses `allow_pickle=False`. Latents must be finite
float32 arrays. Their shapes are checked against the loaded model before allocation;
same-shaped arrays from another model cannot be identified without the version metadata
that the local backend maintains. Inference uses the requested supported `language`,
defaulting to `LANG_TAG`. Output rate comes from the matching model configuration, normally 24 kHz.

Errors: 401 invalid/missing key; 408 upload timeout; 413 oversized request/upload;
415 wrong encoding/content type; 422 invalid audio/text/latents; 429 too many active
requests; 503 lock timeout/GPU memory exhaustion; 500 other model failures. Malformed
multipart data can return 400. Validation errors never echo submitted text or latents.

## Configuration

Every model path, language choice, inference default, request limit, timeout, and network
setting lives in the notebook's environment-based configuration. Structural dimensions
and output sample rate come from the loaded model configuration. The notebook contains
comments for each settings group; credentials are never committed.

| Group | Environment settings |
| --- | --- |
| Model | `MODEL_PATH`, `CONFIG_PATH`, `VOCAB_PATH`, `LANG_TAG`, `MODEL_VERSION` |
| Credentials | `API_KEY` (generated if absent; never put a literal secret in a cell) |
| Sampling | `TEMPERATURE`, `SPEED`, `MIN_TEMPERATURE`, `MAX_TEMPERATURE`, `MIN_SPEED`, `MAX_SPEED`, `TOP_K`, `TOP_P`, `LENGTH_PENALTY`, `REPETITION_PENALTY`, `DO_SAMPLE`, `NUM_BEAMS` |
| Conditioning | `GPT_COND_LEN`, `GPT_COND_CHUNK_LEN`, `SOUND_NORM_REFS` |
| Audio limits | `MIN_REF_SECONDS`, `MAX_REF_SECONDS`, `MIN_REF_SR`, `MAX_REF_SR`, `MAX_REF_CHANNELS`, `MAX_WAV_BYTES`, `MAX_OUTPUT_SECONDS` |
| Request limits | `MAX_REQUEST_BYTES`, `MAX_LATENT_BYTES`, `MAX_LATENT_TOKENS`, `MAX_TEXT_CHARS`, `MAX_INFLIGHT` |
| Timeouts | `BODY_TIMEOUT_SECONDS`, `LOCK_TIMEOUT_SECONDS`, `STARTUP_TIMEOUT_SECONDS`, `TUNNEL_TIMEOUT_SECONDS`, `CLIENT_TIMEOUT_SECONDS` |
| Server/tunnel | `HOST`, `PORT`, `CLOUDFLARED_PATH`, `CLOUDFLARED_DOWNLOAD_URL`, `TUNNEL_PROTOCOL` |
| Setup/self-test | `COQUI_TTS_SPEC`, `DRIVE_MOUNT`, `SAMPLE_REFERENCE_PATH`, `SELF_TEST_TEXT` |

The default package is `coqui-tts==0.27.5`, with Transformers constrained below 5;
Colab's existing matching CUDA PyTorch/torchaudio pair is retained. Compatibility with
your training environment must be established by the real self-test. See the
[Coqui package requirements](https://pypi.org/project/coqui-tts/0.27.5/).

To change an existing non-secret environment setting in Colab, stop cell 6 using cell 8,
set the new value with `os.environ['SETTING_NAME'] = 'value'`, then rerun cells 3–6.
Editing a `setdefault` value alone does not replace an existing environment value.

On a model swap: change `MODEL_PATH`, `CONFIG_PATH`, `VOCAB_PATH`, `LANG_TAG`, and
`MODEL_VERSION`, rerun the Colab cells, and **re-enroll voices because old latents are
invalid for the new model**. Use a new model version even if overwriting files in place.

## Privacy and runtime behavior

Reference recordings are sent to the user's Colab server for `/latents`; generated
latents are returned and sent again with each synthesis request. The server processes
recordings, text, latents, and generated WAVs in RAM and creates no user voice files or
voice cache. Multipart uploads stay in RAM even above Starlette's normal spool threshold.
The self-test reads an existing Drive clip that the user placed there; it does not delete
that source recording. The model remains loaded for the session.

Both GPU operations share a lock. Request bodies are authenticated and bounded before
multipart/JSON parsing, including chunked transfers. All accepted requests together are
bounded by `MAX_INFLIGHT`; excess requests receive 429. Health stays available during
inference provided an admission slot remains. CUDA runs with `torch.no_grad()`, and
temporary tensors are released followed by `torch.cuda.empty_cache()` after GPU calls.
This is not secure memory erasure and cannot clear live model tensors. There is no
hard cancellation of an in-progress CUDA kernel; a timed-out client may leave work finishing.

Cloudflare and Google host/transport the data in this testing architecture. Model
installation downloads packages and the tunnel binary; no Groq or other text service
is called in Phase 1. The future `LOCAL_ONLY` flag and encrypted local voice store are
Phase 2 features, not implemented claims about this server. It would be inaccurate to
say enrollment recordings never leave the local machine in this architecture.

Logs omit request bodies, audio, latents, API keys, and raw exception messages. The only
key display is the expressly requested one-time generated key in cell 3. Clear outputs
before saving/sharing, including the self-test audio. Notebook metadata requests omission
of outputs on save, and the delivered file has no saved outputs.

## Local verification commands

These tests use fake model/CUDA objects and synthetic WAV data. They do not download
XTTS, use your Drive, open a tunnel, or claim to measure speech quality.
The lifecycle test starts a real local Uvicorn listener with a simulated cloudflared process.
Local verification: **31 tests passed** on Python 3.12. The installed Starlette release
emitted one non-failing deprecation warning about its TestClient's httpx integration.

Windows PowerShell, from the project root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Linux/macOS, from the project root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m pytest -q
```

Checklist:

- Notebook schema valid; every Python cell compiles; no stored output or credentials.
- All three endpoints reject missing/wrong keys.
- Valid WAV → finite float32 latents → playable 24 kHz WAV with the fake model.
- Large accepted WAV uploads never roll over to disk and upload handles are closed.
- Invalid WAVs, nonfinite/wrong-shaped/pickled latents, malicious array dimensions,
  oversized/chunked bodies, invalid speed/temperature, and token overflow are rejected.
- GPU work is serialized; lock timeout, GPU OOM, and internal failures release the lock
  and clean the CUDA cache without revealing private exception messages.
- A real local Uvicorn server starts, restarts, and shuts down; the simulated tunnel
  process is terminated and its old URL removed from the environment.
- **On Colab:** execute cell 7 against your real checkpoint and listen to the Urdu result.

## Troubleshooting and assumptions

The notebook includes detailed troubleshooting for checkpoint keys and tokenizer size,
safe checkpoint loading, dependency conflicts, Drive authorization, HTTP errors, tunnel
startup/expiration, and model swaps.

Assumptions for Phase 1: your files form a trusted full XTTS-v2 inference checkpoint,
the Urdu vocabulary matches its embeddings, and `ar` is the training language token.
A Colab GPU session, mounted Drive, and a suitable reference clip must be supplied by
the user. The reference primitive path uses in-memory soundfile decoding followed by
XTTS's GPT-conditioning and speaker-embedding functions; it does not use Coqui's
on-disk voice cache. See the [XTTS implementation](https://github.com/idiap/coqui-ai-TTS/blob/v0.27.5/TTS/tts/models/xtts.py).

Free Colab and quick tunnels are for testing. Restarting a notebook loses its generated
key and changes the tunnel URL. Urdu quality depends on your fine-tune; stock XTTS does
not make this a validated Urdu prosthetic. Real GPU/checkpoint execution remains a
user-side acceptance step because the project contains no model artifacts or Colab session.

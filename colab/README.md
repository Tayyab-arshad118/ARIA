# Colab GPU notebook

[Project handbook](../README.md)

[ARIA_Colab_GPU.ipynb](ARIA_Colab_GPU.ipynb) runs the supplied XTTS checkpoint on a Colab GPU and exposes three small inference endpoints through an HTTPS tunnel. It does not provide the checkpoint, train a new model, perform Groq conversion, or keep the user's profile database.

## Before running

Select a Colab GPU runtime, provide trusted matching model/config/vocabulary files, and authorize Drive if storing them there. The intended Urdu fine-tune uses the XTTS token `ar`; app-level Urdu is `ur`. Do not mix tokenizer files or embedding sizes from unrelated checkpoints.

The full end-user walkthrough is in [Chapter 5](../README.md#chapter-5--set-up-colab-and-connect-it).

## Cell map

| Number / cell ID | Responsibility |
| --- | --- |
| 1 / `install` | Install inference/API dependencies while using the runtime's matching CUDA torch pair. |
| 2 / `drive` | Mount the user's Drive. |
| 3 / `config` | Set non-secret paths/defaults, validate configuration, read/generate the API key. |
| 4 / `model` | Load checkpoint, vocabulary, supported tags, and latent-shape expectations. |
| 5 / `api` | Define bounded authenticated health/latent/synthesis endpoints. |
| 6 / `serve` | Start Uvicorn and cloudflared, discover a public URL, and manage restart/cleanup. |
| 7 / `self-test` | Test the public route, authentication, reference processing, and synthesis. |
| 8 / `shutdown` | Stop server and tunnel; optional, only when finished. |

Markdown cells explain troubleshooting and the local-backend long-recording/language integration. Running every cell through shutdown will stop the server you just started; leave the shutdown cell for the end of a session.

## Key configuration

- `MODEL_PATH`, `CONFIG_PATH`, `VOCAB_PATH`: matching files available in the runtime.
- `LANG_TAG`: default model token, normally `ar` for this Urdu fine-tune.
- `MODEL_VERSION`: descriptive model identity; keep the local backend's version deliberate when replacing weights.
- `SUPPORTED_LANG_TAGS`: optional comma-separated restriction of configured model languages, not a way to add unsupported languages.
- `SAMPLE_REFERENCE_PATH`: short suitable WAV for the direct self-test.
- Request, reference, output, token, and timeout defaults: set in the config cell and kept consistent with backend expectations.

Environment values can override notebook defaults. A generated API key is shown when created; do not hardcode real keys into source or share saved outputs containing them.

## Inference API

All routes require the notebook's `x-api-key`. No public documentation endpoint is exposed.

| Endpoint | Behavior |
| --- | --- |
| `GET /health` | Model readiness, GPU name, default language, supported language tags. |
| `POST /latents` | Receives a short multipart WAV `file`; returns base64 numeric arrays for the voice. |
| `POST /synthesize` | Receives text/voice arrays plus language/sampling options; returns base64 WAV and sample rate. |

Incoming voice arrays must have expected float32 shapes and finite values; NumPy loading disables pickle. The server checks request bounds and serializes GPU work. The notebook does not prove that same-shaped arrays came from the same checkpoint, which is why local model-version/re-enrollment management matters.

## Long recordings and privacy

The local backend accepts long/compressed recordings, selects a short usable section, and sends that prepared WAV here. Do not increase notebook upload limits merely because the source file is 30 minutes long. The direct notebook self-test still needs a short reference.

The supplied server handles references and output in memory rather than maintaining a voice database. Reference data, text, and voice representations still travel to Colab through the tunnel. Google/Cloudflare are external infrastructure.

## Reconnect, debug, and verify

After restarting Colab/tunnel, copy the current key and URL into the app's Connect screen. If configuration changes, rerun the appropriate config/model/API/server cells. If the app reports an old notebook or language mismatch, confirm you ran this version and matching model settings.

Listen to the self-test; an HTTP success does not establish intelligibility or speaker similarity. Local [notebook tests](../tests/README.md) use a fake model/CUDA implementation and do not certify the actual checkpoint.

## Checkpoint identity

The notebook hashes the checkpoint, configuration and vocabulary into a 64-character SHA-256 fingerprint. Health and conditioning responses include it; synthesis rejects a mismatched requested fingerprint. Run this updated notebook before using the assistive backend. A display version string alone cannot make old conditioning compatible. The hashing step does not rewrite or train weights.

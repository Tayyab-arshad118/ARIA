# Long recordings and model languages

Restart the local backend and app after installing these changes. Upload the updated
[Colab notebook](../colab/ARIA_Colab_GPU.ipynb) and run cells 3–6 with your existing model
paths. Copy the current Colab URL/key into the backend using the existing setup flow,
then press **Refresh** in the app. An older running notebook must be replaced to accept
the new synthesis language field and advertise its languages.

## Long source recordings

**Add a voice** and emotion references accept WAV, MP3, M4A, AAC, OGG and FLAC. Defaults:

| Setting | Default | Purpose |
| --- | --- | --- |
| `MAX_SOURCE_SECONDS` | 1800 | Source duration: 30 minutes |
| `MAX_UPLOAD_BYTES` | 268435456 | Source size: 256 MiB |
| `MAX_REQUEST_BYTES` | 270532608 | Multipart request including headers |
| `ARIA_MAX_UPLOAD_BYTES` (app) | 268435456 | App source size check |
| `MIN_REFERENCE_SECONDS` / `MAX_REFERENCE_SECONDS` | 6 / 30 | Selected conditioning section |
| `REFERENCE_SCAN_STEP_SECONDS` | 5 | Rolling selection interval |
| `MAX_PARALLEL_UPLOADS` | 1 | Concurrent upload/processing admission |
| `MAX_JSON_BYTES` | 1048576 | Independent JSON request bound |
| `BODY_TIMEOUT_SECONDS` | 300 | Upload body deadline |

The source can be much longer than 30 seconds. The local backend scans it in bounded
decoded blocks, selects a section with useful non-silent audio and limited clipping,
and converts that section to mono PCM16 WAV at 22.05 kHz. It sends only that section to
Colab for voice conditioning. This does **not** train on or condition on the entire long
recording. Selection measures signal energy and clipping, not semantic speech quality;
use one clear speaker without background music. Multi-speaker separation is not provided.

Increase source limits in the backend's active environment file and the matching app
upload limit if needed. Keep the multipart limit larger than the upload limit. Changing
the conditioning window also requires matching notebook reference limits; changing only
the source limit does not. Accepted uploads remain in RAM, and decoded buffers are bounded;
larger upload limits still require more RAM. Original recordings are not retained unless
`KEEP_RAW_AUDIO=true`. Liveness challenges remain short WAV recordings.

The [manual converter](../aria_backend/scripts/convert_audio.py) also exports the selected
reference section. The [sample MP3 and WAV](../examples/audio/README.md) demonstrate conversion.

## Model language selection

The notebook reads `cfg.languages` from your loaded checkpoint configuration and reports
those tags in `/health`. `SUPPORTED_LANG_TAGS` optionally restricts that configured list
using comma-separated tags. It cannot add a language absent from the model configuration.
Configuration advertises support; test output quality with your actual fine-tuned weights.

The app's **Language** dropdown is populated from the backend's `/api/languages` catalog.
Keep `LANG_TAG=ar` for your Urdu fine-tune. By default, logical app language `ur` maps to
the model's `ar` token. Other configured tags, such as `en` or `hi`, appear automatically.
`LANGUAGE_ALIASES` can explicitly configure additional aliases while preserving the Urdu
mapping, for example `{"ur":"ar","ar":"ar"}` if the same checkpoint also genuinely supports
Arabic under that token. No automatic language detection is performed.

With Groq enabled, automatic transliteration now works for every selected model language.
Choose **Native script** to bypass it. Only Urdu uses the Urdu normalizer and local word
suggestions. See [simple startup and conversion](EASY_START.md) for the current behavior.
The composer provides multilingual speech synthesis and transliteration. Quick phrases additionally
translate their meanings into the selected language with Groq, for both the cards and speech.

`POST /api/tts` accepts `language` (default `ur`). Its response includes `X-Spoken-Text`
(percent-encoded), `X-Language`, and `X-Model-Language`. `X-Urdu-Text` remains a legacy
compatibility header. Audio cache keys include the language and model tag. Discovered
languages are encrypted and remembered for offline cached playback, and invalidated when
`MODEL_VERSION` changes. A legacy server only exposes the default Urdu mapping.

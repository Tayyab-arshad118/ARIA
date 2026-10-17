# Audio conversion sample

`sample-speech.mp3` is a short synthetic spoken recording made with Windows text-to-speech,
not a recording or clone of a real person. `sample-speech.wav` is the converted 22.05 kHz
mono PCM16 result. These files demonstrate conversion; use your own authorized speech
recording when enrolling a personal voice.

The app's **Add a voice → Choose audio** now accepts WAV, MP3, M4A, AAC, OGG and FLAC.
The local backend converts to WAV automatically before requesting Colab latents. Duration,
silence, clipping and upload limits still apply. Conversion is in memory and does not
upload the source to an external conversion service. Emotion references support the same
formats. Liveness verification and watermark detection still require WAV.

To create a WAV manually, from the project root:

```powershell
.\.venv\Scripts\python.exe aria_backend/scripts/convert_audio.py "input.mp3" "output.wav"
```

This command accepts sources up to 30 minutes / 256 MiB and selects a suitable 6–30 second
reference window; it does not export the full length of a long recording. It refuses
to overwrite an existing output. It requires the updated backend requirements, which
include PyAV's audio decoding support; no separate ffmpeg executable is needed for the
standard wheel installation.

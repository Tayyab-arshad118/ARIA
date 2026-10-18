# Examples

[Project handbook](../README.md)

This folder contains small shareable demonstration assets. It is not the location for a user's real voice recordings, profiles, generated speech library, credentials, or evaluation dataset.

## Included example

[audio](audio/) contains [sample-speech.mp3](audio/sample-speech.mp3) and [sample-speech.wav](audio/sample-speech.wav). The source is synthetic Windows text-to-speech, not a recording/clone of a real person. The prepared WAV is mono PCM16 at 22.05 kHz. These demonstrate conversion without needing a personal recording.

From the project root, prepare a reference with:

```powershell
.\.venv\Scripts\python.exe aria_backend/scripts/convert_audio.py "input.mp3" "output.wav"
```

The converter accepts supported sources up to 30 minutes / 256 MiB and chooses a suitable 6–30-second reference section; it does not export the entire long recording. It refuses to overwrite an existing output. PyAV handles compressed decoding locally. Enrollment and emotion references accept WAV, MP3, M4A, AAC, OGG, and FLAC; experimental verification and watermark detection require WAV.

Patients can supply appropriately authorized historical recordings from before speech loss. This file import does not require the patient to speak now. The prototype does not yet implement the separate consent/representative workflow described in the main handbook.

Use your own authorized single-speaker recording for actual voice enrollment. A synthetic conversion sample does not test the fidelity of a person's cloned voice. The example files are intentionally allowed through Git ignore rules; arbitrary personal audio elsewhere is ignored.

When adding examples, explain what is supplied, how it was produced, how to run it, and what it does not prove. Keep files small and free of real secrets or private user content.

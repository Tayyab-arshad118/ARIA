# Backend utility scripts

[Project handbook](../../README.md) · [Backend folder](../README.md)

These are explicit setup/development commands. They are not automatically run during normal API requests. Examples below start at the repository root and assume `.venv` exists.

## Configuration helper

[configure_local.py](configure_local.py) creates protected backend/app environment files, shares a strong local bearer token, and chooses/preserves a runtime data location. It applies Windows access restrictions or restrictive file permissions where supported.

```powershell
.\.venv\Scripts\python.exe aria_backend/scripts/configure_local.py --no-prompt
```

Without `--no-prompt`, it offers a hidden Groq-key prompt; blank keeps an existing key. It does not migrate an existing database automatically. Keep the current `DATA_DIR` and encryption key when preserving profiles.

## Audio preparation

[convert_audio.py](convert_audio.py) validates a source and writes the selected mono PCM16 reference WAV. It refuses to overwrite an existing output.

```powershell
.\.venv\Scripts\python.exe aria_backend/scripts/convert_audio.py "input.mp3" "reference.wav"
```

Default source limits are 30 minutes / 256 MiB. Output is a suitable section of up to 30 seconds, not a full-length transcoding tool. The [synthetic sample](../../examples/audio/README.md) demonstrates conversion without requiring a personal recording.

## Prediction benchmark

[benchmark_predict.py](benchmark_predict.py) calls the running backend with sample Roman prefixes and reports round-trip/server timing statistics. It measures prediction, not speech generation.

```powershell
.\.venv\Scripts\python.exe aria_backend/scripts/benchmark_predict.py --requests 200 --backend http://127.0.0.1:8001
```

It uses the configured backend bearer key without printing it. Timing depends on your hardware, process load, and deployment; the script's budget check is not a universal performance promise.

## Optional safety models

[prepare_safety_models.py](prepare_safety_models.py) is the explicit downloader for AudioSeal and Whisper/ECAPA assets. Ordinary API calls never run it.

Install the extra CPU dependencies first:

```powershell
.\.venv\Scripts\python.exe -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r aria_backend/requirements-safety.txt
```

Then allow downloads for this setup process. This example preserves your previous process environment value:

```powershell
$previousLocalOnly = $env:LOCAL_ONLY
try {
    $env:LOCAL_ONLY = "false"
    .\.venv\Scripts\python.exe aria_backend/scripts/prepare_safety_models.py --allow-downloads --feature all
} finally {
    $env:LOCAL_ONLY = $previousLocalOnly
}
```

`--feature` accepts `all`, `watermark`, or `liveness`. Both the flag and `LOCAL_ONLY=false` are required. Files go to configured paths; defaults are under the backend's model-data directory. Use trusted weights. Enable the desired feature separately in effective backend settings after preparation and restart.

## Optional speech evaluation

[evaluate.py](evaluate.py) calls the speech backend, transcribes output with local Whisper, and compares speaker representations with ECAPA. It writes CSV and a JSON summary. Install [evaluation requirements](../requirements-eval.txt) and a compatible CPU torch/torchaudio pair first.

Input is a JSON list like:

```json
[{"text":"mujhe pani chahiye","urdu":"مجھے پانی چاہیے"}]
```

```powershell
.\.venv\Scripts\python.exe aria_backend/scripts/evaluate.py "sentences.json" --reference "speaker.wav" --voice-id default --output "evaluation.csv"
```

`sentences.json` and `speaker.wav` are files you supply, not bundled evaluation data. Optional flags include `--backend` and `--allow-model-downloads`. Offline evaluation needs local model paths, especially `EVAL_SPEAKER_MODEL`; downloads also require effective `LOCAL_ONLY=false`. Strict speech can use `LIVENESS_SESSION_TOKEN` from evaluator settings.

The current evaluator's reference normalization and expected `urdu` field are Urdu-oriented; it is not a universal multilingual benchmark. Character error rate and speaker similarity are measurements to interpret, not proof of intelligibility or clinical usefulness. Keep private references and reports out of Git.

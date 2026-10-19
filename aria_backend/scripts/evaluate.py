"""Optional CPU evaluation of the running full text-to-speech backend."""
import argparse
import csv
import io
import json
import os
from pathlib import Path
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import soundfile as sf

from app.config import Settings, backend_env_file
from app.services.audio_utils import resample
from app.services.urdu_normalizer import normalize_urdu


def metric_text(text):
    # CER convention: normalize Urdu and numbers, remove punctuation and whitespace.
    return "".join(c for c in normalize_urdu(text) if not c.isspace() and not unicodedata.category(c).startswith("P"))


def edit_distance(reference, hypothesis):
    previous = list(range(len(hypothesis) + 1))
    for i, left in enumerate(reference, 1):
        current = [i]
        for j, right in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sentences", type=Path, help="JSON list of {text, urdu} objects")
    parser.add_argument("--reference", type=Path, required=True, help="Original speaker reference WAV")
    parser.add_argument("--voice-id", default="default")
    parser.add_argument("--backend", default="http://127.0.0.1:8001")
    parser.add_argument("--output", type=Path, default=Path("evaluation.csv"))
    parser.add_argument("--allow-model-downloads", action="store_true")
    parser.add_argument("--wav-directory", type=Path, help="Evaluate existing clips instead of calling TTS; rows may name audio_file")
    parser.add_argument("--language", default="ur")
    parser.add_argument("--emotion", choices=["neutral", "happy", "sad", "angry", "calm", "auto"], default="neutral")
    args = parser.parse_args()
    settings = Settings()
    # dotenv loads these evaluator-only settings without replacing environment values.
    from dotenv import dotenv_values
    values = {**dotenv_values(backend_env_file()), **os.environ}
    whisper_model = values.get("EVAL_WHISPER_MODEL", "small")
    speaker_model = values.get("EVAL_SPEAKER_MODEL", "speechbrain/spkrec-ecapa-voxceleb")
    model_cache = Path(values.get("EVAL_MODEL_CACHE", str(settings.data_dir / "eval_models")))
    downloads = args.allow_model_downloads and not settings.local_only
    if not downloads:
        os.environ["HF_HUB_OFFLINE"] = "1"
        if not Path(speaker_model).is_dir():
            parser.error("Offline evaluation requires EVAL_SPEAKER_MODEL pointing to a downloaded model directory")
    try:
        import torch
        from faster_whisper import WhisperModel
        from speechbrain.inference.speaker import EncoderClassifier
        from speechbrain.utils.fetching import LocalStrategy
    except ImportError:
        parser.error("Install requirements-eval.txt and a matching CPU torch/torchaudio pair first")
    records = json.loads(args.sentences.read_text(encoding="utf-8"))
    if not isinstance(records, list) or not records or any(
        not isinstance(row, dict) or not isinstance(row.get("text"), str)
        or not isinstance(row.get("urdu"), str) or not metric_text(row["urdu"]) for row in records
    ):
        parser.error("Provide a nonempty JSON list with text and Urdu reference strings")
    asr = WhisperModel(whisper_model, device="cpu", compute_type="int8",
                       download_root=str(model_cache / "whisper"), local_files_only=not downloads)
    speaker = EncoderClassifier.from_hparams(source=speaker_model, savedir=str(model_cache / "ecapa"),
        run_opts={"device": "cpu"}, local_strategy=LocalStrategy.COPY)
    reference, ref_sr = sf.read(args.reference, dtype="float32", always_2d=True)
    ref_16k = resample(reference.mean(axis=1), ref_sr, 16000)
    with torch.no_grad():
        ref_embedding = speaker.encode_batch(torch.from_numpy(ref_16k).unsqueeze(0)).reshape(-1)
    headers = {"Authorization": "Bearer " + settings.aria_key.get_secret_value()} if settings.aria_key.get_secret_value() else {}
    if values.get("LIVENESS_SESSION_TOKEN"):
        headers["X-ARIA-Session"] = values["LIVENESS_SESSION_TOKEN"]
    if values.get("ARIA_ACCOUNT_TOKEN"):
        headers["X-ARIA-Account"] = values["ARIA_ACCOUNT_TOKEN"]
    rows, distances, characters = [], 0, 0
    with httpx.Client(base_url=args.backend, headers=headers, timeout=settings.gpu_timeout_seconds * 4,
                      follow_redirects=False, trust_env=False) as client:
        for index, row in enumerate(records, 1):
            if args.wav_directory:
                directory = args.wav_directory.resolve()
                path = (directory / row.get("audio_file", f"{index}.wav")).resolve()
                if directory not in path.parents or not path.is_file():
                    parser.error("Each audio_file must be an existing file inside --wav-directory")
                raw = path.read_bytes()
            else:
                response = client.post("/api/tts", json={"text": row["text"], "voice_id": args.voice_id,
                    "language": args.language, "emotion": args.emotion})
                if response.status_code != 200 or response.headers.get("x-aria-watermark") != "verified":
                    parser.exit(1, f"Sentence {index} speech/protection failed; no metrics fabricated.\n")
                raw = response.content
            audio, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=True)
            audio_16k = resample(audio.mean(axis=1), sr, 16000)
            segments, _ = asr.transcribe(audio_16k, language=values.get("EVAL_ASR_LANGUAGE", "ur"), beam_size=5)
            transcript = " ".join(segment.text.strip() for segment in segments)
            expected, heard = metric_text(row["urdu"]), metric_text(transcript)
            distance = edit_distance(expected, heard)
            with torch.no_grad():
                embedding = speaker.encode_batch(torch.from_numpy(audio_16k).unsqueeze(0)).reshape(-1)
                similarity = float(torch.nn.functional.cosine_similarity(ref_embedding, embedding, dim=0))
            rows.append({"index": index, "text": row["text"], "expected_urdu": row["urdu"], "transcript": transcript,
                         "cer": distance / len(expected), "speaker_similarity": similarity})
            distances += distance
            characters += len(expected)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    summary = {"sentences": len(rows), "corpus_cer": distances / characters,
               "mean_speaker_similarity": sum(r["speaker_similarity"] for r in rows) / len(rows),
               "comparison_note": "No baseline is fabricated. Compare separately measured runs with the same held-out speakers, sentences, references, ASR model and normalization."}
    args.output.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

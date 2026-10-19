"""Reproducible real-engine watermark evaluation; requires explicit WAV source/control folders."""
import argparse
import asyncio
import hashlib
import io
import json
from pathlib import Path
import sys

import av
import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.services.audio_utils import encode_wav, resample
from app.services.watermark import Watermarker
from app.services.errors import ServiceError


def codec_roundtrip(samples, sr, kind):
    target_rate = 44100
    samples = resample(samples, sr, target_rate).astype(np.float32)
    buffer = io.BytesIO()
    with av.open(buffer, mode="w", format="mp3" if kind == "mp3" else "mp4") as container:
        stream = container.add_stream("libmp3lame" if kind == "mp3" else "aac", rate=target_rate)
        stream.layout, stream.bit_rate = "mono", 96000
        frame = av.AudioFrame.from_ndarray(samples[None, :], format="fltp", layout="mono")
        frame.sample_rate = target_rate
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    frames = []
    with av.open(io.BytesIO(buffer.getvalue())) as container:
        converter = av.AudioResampler(format="fltp", layout="mono", rate=sr)
        for frame in container.decode(audio=0):
            frames.extend(part.to_ndarray().reshape(-1) for part in converter.resample(frame))
    return np.concatenate(frames)


def transformations(raw, seed):
    samples, sr = sf.read(io.BytesIO(raw), dtype="float32")
    if samples.ndim != 1:
        raise ValueError("Evaluation expects mono WAVs")
    rng = np.random.default_rng(seed)
    rms = float(np.sqrt(np.mean(samples ** 2)))
    yield "wav_export", encode_wav(samples, sr)
    yield "resample_16k_roundtrip", encode_wav(resample(resample(samples, sr, 16000), 16000, sr), sr)
    yield "noise_20db", encode_wav(samples + rng.normal(0, rms / 10, len(samples)).astype(np.float32), sr)
    cut = int(len(samples) * 0.1)
    yield "trim_10pct_each_end", encode_wav(samples[cut:len(samples) - cut] if cut else samples, sr)
    for codec in ("mp3", "aac"):
        yield codec + "_96kbps", encode_wav(codec_roundtrip(samples, sr, codec), sr)


async def evaluate(settings, sources, genuine, seed, marker=None):
    marker = marker or Watermarker(settings)
    records = []
    embedded = 0
    for is_source, paths in ((True, sources), (False, genuine)):
        for index, path in enumerate(paths):
            raw = path.read_bytes()
            record = {"group": "synthetic_source" if is_source else "genuine_control",
                "file_sha256": hashlib.sha256(raw).hexdigest(), "index": index, "conditions": []}
            if is_source:
                try:
                    marked, status = await marker.finalize(raw)
                    if status != "verified":
                        raise ServiceError(503, "Required protection not active")
                    embedded += 1
                    before, sr = sf.read(io.BytesIO(raw), dtype="float32")
                    after, _ = sf.read(io.BytesIO(marked), dtype="float32")
                    error = np.mean((before - after) ** 2)
                    record["embedding_snr_db"] = float(10 * np.log10(max(float(np.mean(before ** 2)), 1e-12) / max(float(error), 1e-12)))
                    raw = marked
                except ServiceError:
                    record["embedding"] = "failed"
                    records.append(record)
                    continue
                record["embedding"] = "verified"
            for name, transformed in transformations(raw, seed + index):
                try:
                    result = await marker.detect(transformed)
                    bits = result.get("message_bits")
                    record["conditions"].append({"condition": name, **result,
                        "bit_error_rate": sum(a != b for a, b in zip(bits, settings.watermark_message_bits)) / 16 if bits and len(bits) == 16 else None})
                except ServiceError:
                    record["conditions"].append({"condition": name, "error": "detector_unavailable"})
            records.append(record)
    summary = {}
    names = sorted({c["condition"] for row in records for c in row["conditions"]})
    for name in names:
        positive = [c for row in records if row["group"] == "synthetic_source" for c in row["conditions"] if c["condition"] == name and "detected" in c]
        negative = [c for row in records if row["group"] == "genuine_control" for c in row["conditions"] if c["condition"] == name and "detected" in c]
        summary[name] = {"marked_count": len(positive), "genuine_count": len(negative),
            "true_positive_rate": sum(c["detected"] for c in positive) / len(positive) if positive else None,
            "false_positive_rate": sum(c["detected"] for c in negative) / len(negative) if negative else None,
            "marked_payload_recovery": sum(c["aria_payload_match"] for c in positive) / len(positive) if positive else None}
    return {"seed": seed, "watermark_fingerprint": marker.fingerprint(), "source_count": len(sources),
        "genuine_count": len(genuine), "embedding_success_rate": embedded / len(sources) if sources else None,
        "conditions": summary, "records": records,
        "limits": "SNR is waveform distortion only. Speaker similarity, intelligibility and emotion require separate real-model/listener evaluation. Null FPR means no genuine-human controls were supplied."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True, help="Folder of authorized synthetic WAVs to embed")
    parser.add_argument("--genuine", type=Path, help="Folder of authorized genuine-human WAV controls, never synthetic substitutes")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new report filename")
    sources = sorted(args.sources.glob("*.wav"))
    genuine = sorted(args.genuine.glob("*.wav")) if args.genuine else []
    if not sources or (args.genuine and not genuine):
        parser.error("Each supplied folder must contain WAV files")
    settings = Settings().model_copy(update={"watermark_policy": "required", "watermark_enabled": True})
    marker = Watermarker(settings)
    try:
        marker.load()
    except Exception:
        parser.exit(2, "AudioSeal models/runtime unavailable. No evaluation scores were produced. Install trusted local weights and retry.\n")
    report = asyncio.run(evaluate(settings, sources, genuine, args.seed, marker))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, ensure_ascii=False, allow_nan=False)
    print("Report written. Embedding success:", report["embedding_success_rate"], "Genuine controls:", len(genuine))


if __name__ == "__main__":
    main()

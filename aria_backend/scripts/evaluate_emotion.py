"""Generate protected, blinded expression trials and score listener labels without inventing ratings."""
import argparse
import csv
import hashlib
import json
import random
from pathlib import Path
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings

EMOTIONS = ("neutral", "happy", "sad", "angry", "calm")


def score(trials, ratings):
    expected = {row["blind_id"]: row for row in trials}
    matrix = {label: {guess: 0 for guess in EMOTIONS} for label in EMOTIONS}
    seen, per_trial = set(), {}
    for row in ratings:
        pair = (row["listener_id"], row["blind_id"])
        if pair in seen or row["blind_id"] not in expected or row["label"] not in EMOTIONS or not row["listener_id"].strip():
            raise ValueError("Invalid or duplicate listener response")
        seen.add(pair)
        truth = expected[row["blind_id"]]["requested_emotion"]
        matrix[truth][row["label"]] += 1
        per_trial.setdefault(row["blind_id"], []).append(row["label"])
    total = len(seen)
    if not total:
        raise ValueError("No listener responses")
    f1 = []
    for label in EMOTIONS:
        tp = matrix[label][label]
        fp = sum(matrix[other][label] for other in EMOTIONS if other != label)
        fn = sum(matrix[label][other] for other in EMOTIONS if other != label)
        f1.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0)
    agreeing = pairs = 0
    for labels in per_trial.values():
        for i, left in enumerate(labels):
            for right in labels[i + 1:]:
                agreeing += left == right
                pairs += 1
    return {"ratings": total, "trials_rated": len(per_trial), "confusion_matrix": matrix,
        "support": {label: sum(matrix[label].values()) for label in EMOTIONS},
        "missing_requested_emotions": [label for label in EMOTIONS if not sum(matrix[label].values())],
        "speakers_rated": len({expected[identifier].get("voice_id") for identifier in per_trial}),
        "accuracy": sum(matrix[label][label] for label in EMOTIONS) / total,
        "macro_f1": sum(f1) / len(f1), "pairwise_listener_agreement": agreeing / pairs if pairs else None,
        "limits": "Agreement is raw pairwise agreement, not chance corrected. Report missing labels/speakers, fallback trials, pronunciation and identity ratings separately. No clinical claim follows from these scores."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("--plan", type=Path, required=True, help="JSON: speakers [{voice_id, held_out:true}], sentences [{id,text,language}]")
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--backend", default="http://127.0.0.1:8001")
    generate.add_argument("--seed", type=int, default=2026)
    assess = sub.add_parser("score")
    assess.add_argument("--trials", type=Path, required=True)
    assess.add_argument("--ratings", type=Path, required=True)
    assess.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; choose a new destination")
    if args.command == "score":
        try:
            trials = json.loads(args.trials.read_text(encoding="utf-8"))["trials"]
            with args.ratings.open(encoding="utf-8-sig", newline="") as source:
                result = score(trials, list(csv.DictReader(source)))
        except (ValueError, KeyError):
            parser.error("Invalid trial manifest or listener ratings")
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if len(plan.get("speakers", [])) < 2 or not plan.get("sentences") or not all(p.get("held_out") is True for p in plan["speakers"]):
        parser.error("Use at least two explicitly held-out speakers and a nonempty fixed sentence set")
    import os
    settings = Settings()
    headers = {"Authorization": "Bearer " + settings.aria_key.get_secret_value()}
    if os.environ.get("ARIA_ACCOUNT_TOKEN"):
        headers["X-ARIA-Account"] = os.environ["ARIA_ACCOUNT_TOKEN"]
    jobs = [(speaker["voice_id"], sentence, emotion) for speaker in plan["speakers"] for sentence in plan["sentences"] for emotion in EMOTIONS]
    random.Random(args.seed).shuffle(jobs)
    args.output.mkdir(parents=True)
    trials = []
    with httpx.Client(base_url=args.backend, headers=headers, timeout=300, trust_env=False) as client:
        for number, (voice, sentence, emotion) in enumerate(jobs, 1):
            response = client.post("/api/tts", json={"voice_id": voice, "text": sentence["text"],
                "language": sentence["language"], "input_mode": "native", "emotion": emotion})
            if response.status_code != 200 or response.headers.get("x-aria-watermark") != "verified":
                parser.exit(1, "Trial generation stopped: speech/protection unavailable. No result was fabricated.\n")
            identifier = f"trial-{number:04d}"
            (args.output / (identifier + ".wav")).write_bytes(response.content)
            trials.append({"blind_id": identifier, "voice_id": voice, "sentence_id": sentence["id"],
                "language": sentence["language"], "model_fingerprint": response.headers.get("x-aria-model-fingerprint"),
                "protection_version": response.headers.get("x-aria-protection-version"),
                "requested_emotion": emotion, "effective_emotion": response.headers.get("x-aria-emotion"),
                "method": response.headers.get("x-aria-emotion-method"), "sha256": hashlib.sha256(response.content).hexdigest()})
            (args.output / "private-trials.json").write_text(json.dumps({"seed": args.seed,
                "plan_sha256": hashlib.sha256(args.plan.read_bytes()).hexdigest(), "complete": False, "trials": trials}, indent=2), encoding="utf-8")
    (args.output / "private-trials.json").write_text(json.dumps({"seed": args.seed,
        "plan_sha256": hashlib.sha256(args.plan.read_bytes()).hexdigest(), "complete": True, "trials": trials}, indent=2), encoding="utf-8")
    with (args.output / "ratings-template.csv").open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(["listener_id", "blind_id", "label"])
        writer.writerows(["", trial["blind_id"], ""] for trial in trials)
    print("Trials generated. Keep private-trials.json hidden from listeners; collect actual ratings before scoring.")


if __name__ == "__main__":
    main()

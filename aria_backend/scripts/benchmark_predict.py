"""Measure local prediction round-trip latency; prints no input text or credentials."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", default="http://127.0.0.1:8001")
    parser.add_argument("--requests", type=int, default=200)
    args = parser.parse_args()
    if args.requests < 20:
        parser.error("Use at least 20 requests")
    settings = Settings()
    key = settings.aria_key.get_secret_value()
    headers = {"Authorization": "Bearer " + key} if key else {}
    timings, server_timings = [], []
    prefixes = ["mujhe ", "mujhe pa", "aap ", "meri ", "mujhe pani "]
    try:
        with httpx.Client(base_url=args.backend, headers=headers, trust_env=False, timeout=5) as client:
            client.get("/api/predict", params={"prefix": ""}).raise_for_status()
            for index in range(args.requests):
                start = time.perf_counter()
                response = client.get("/api/predict", params={"prefix": prefixes[index % len(prefixes)]})
                response.raise_for_status()
                timings.append((time.perf_counter() - start) * 1000)
                server_timings.append(float(response.headers["x-prediction-ms"]))
    except (httpx.HTTPError, KeyError, ValueError):
        parser.exit(1, "Benchmark failed; check the backend address, key, and Phase 4 version.\n")
    p95 = statistics.quantiles(timings, n=100)[94]
    print(json.dumps({"requests": args.requests, "round_trip_p50_ms": statistics.median(timings),
        "round_trip_p95_ms": p95, "round_trip_max_ms": max(timings),
        "server_p95_ms": statistics.quantiles(server_timings, n=100)[94], "p95_under_50ms": p95 < 50}, indent=2))


if __name__ == "__main__":
    main()

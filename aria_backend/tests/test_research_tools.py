import asyncio
import importlib.util
from pathlib import Path

import pytest

from app.config import Settings
from app.services.errors import ServiceError
from test_api import reference


def module(name):
    path = Path(__file__).resolve().parents[1] / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_listener_metrics_require_actual_distinct_ratings():
    tool = module("evaluate_emotion")
    trials = [{"blind_id": "a", "requested_emotion": "happy", "voice_id": "one"},
              {"blind_id": "b", "requested_emotion": "sad", "voice_id": "two"}]
    ratings = [{"blind_id": "a", "listener_id": "1", "label": "happy"},
               {"blind_id": "a", "listener_id": "2", "label": "neutral"},
               {"blind_id": "b", "listener_id": "1", "label": "sad"},
               {"blind_id": "b", "listener_id": "2", "label": "sad"}]
    result = tool.score(trials, ratings)
    assert result["accuracy"] == 0.75 and result["pairwise_listener_agreement"] == 0.5
    assert result["speakers_rated"] == 2 and "angry" in result["missing_requested_emotions"]
    with pytest.raises(ValueError):
        tool.score(trials, ratings + [ratings[0]])
    with pytest.raises(ValueError):
        tool.score(trials, [])


def test_protection_report_marks_missing_controls_without_fabricating_fpr(tmp_path):
    tool = module("evaluate_protection")
    path = tmp_path / "synthetic.wav"
    path.write_bytes(reference())
    class Marker:
        def fingerprint(self):
            return ["injected-test-engine"]
        async def finalize(self, raw):
            return raw, "verified"
        async def detect(self, raw):
            return {"detected": True, "score": 0.99, "message_bits": "0100000101010010", "aria_payload_match": True}
    result = asyncio.run(tool.evaluate(Settings(_env_file=None), [path], [], 2026, Marker()))
    assert result["embedding_success_rate"] == 1
    assert set(result["conditions"]) == {"wav_export", "resample_16k_roundtrip", "noise_20db", "trim_10pct_each_end", "mp3_96kbps", "aac_96kbps"}
    assert all(item["false_positive_rate"] is None for item in result["conditions"].values())

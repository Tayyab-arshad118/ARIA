import importlib.util
from pathlib import Path


def test_cer_distance_and_urdu_normalization():
    path = Path(__file__).resolve().parents[1] / "scripts" / "evaluate.py"
    spec = importlib.util.spec_from_file_location("aria_evaluate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.edit_distance("abc", "axc") == 1
    assert module.edit_distance("abc", "") == 3
    assert module.edit_distance("", "abc") == 3
    assert module.metric_text("مُجھے 2 گلاس۔") == module.metric_text("مجھے دو گلاس")

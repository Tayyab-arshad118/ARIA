"""Explicit one-time download of public safety model weights; never runs from API requests."""
import argparse
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-downloads", action="store_true")
    parser.add_argument("--feature", choices=["all", "watermark", "liveness"], default="all")
    args = parser.parse_args()
    settings = Settings()
    if not args.allow_downloads or settings.local_only:
        parser.error("Downloads need --allow-downloads and LOCAL_ONLY=false for this setup process")
    try:
        from huggingface_hub import hf_hub_download, snapshot_download
        if args.feature in {"all", "watermark"}:
            for filename, target in (("generator_base.pth", settings.watermark_generator_path),
                                      ("detector_base.pth", settings.watermark_detector_path)):
                source = hf_hub_download(settings.safety_watermark_repo, filename=filename, token=False)
                target.parent.mkdir(parents=True, exist_ok=True)
                if Path(source).resolve() != target.resolve():
                    shutil.copyfile(source, target)
        if args.feature in {"all", "liveness"}:
            for repo, target in ((settings.safety_whisper_repo, settings.liveness_whisper_path),
                                 (settings.safety_speaker_repo, settings.liveness_speaker_path)):
                snapshot_download(repo, local_dir=target, token=False,
                    allow_patterns=["*.json", "*.bin", "*.txt", "*.ckpt", "*.yaml"])
    except Exception:
        parser.exit(1, "Model preparation failed. Check dependencies, repository settings, network access and disk space.\n")
    print("Safety model files prepared. Restore LOCAL_ONLY=true before starting the backend if desired.")


if __name__ == "__main__":
    main()

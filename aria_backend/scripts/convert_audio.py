"""Select a usable reference section and convert it to 22.05 kHz mono PCM WAV."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.services.audio_utils import prepare_reference
from app.services.errors import ServiceError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; choose a new filename")
    settings = Settings()
    try:
        with args.input.open("rb") as source:
            raw = source.read(settings.max_upload_bytes + 1)
        wav = prepare_reference(raw, settings)
        with args.output.open("xb") as output:
            output.write(wav)
    except ServiceError as error:
        parser.exit(1, error.detail + "\n")
    except OSError:
        parser.exit(1, "Cannot read input or create output. Check the paths.\n")
    print("Selected reference converted to mono PCM WAV at", settings.reference_sample_rate,
          "Hz (up to", settings.max_reference_seconds, "seconds).")


if __name__ == "__main__":
    main()

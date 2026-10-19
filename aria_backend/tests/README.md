# Backend tests

[Project handbook](../../README.md) · [Backend folder](../README.md)

This suite checks the local server without needing your real checkpoint or paid API calls. Fixtures inject fake GPU/HTTP/safety engines, use synthetic audio, and create temporary databases. [conftest.py](conftest.py) sets up package imports.

## Test map

| File | Main behavior |
| --- | --- |
| [test_api.py](test_api.py) | Core voice/preview/speech APIs, encryption, cache behavior, upstream failures, startup contracts. |
| [test_audio_conversion.py](test_audio_conversion.py) | Real compressed-audio decoding, long sources, selected window, rejected/oversized inputs. |
| [test_services.py](test_services.py) | Text normalization/conversion, chunking, configuration, and low-level helpers. |
| [test_languages.py](test_languages.py) | Model language discovery, persistence, routing, and language-separated speech. |
| [test_setup_and_conversion.py](test_setup_and_conversion.py) | Checked Connect, preserved settings on failure, multilingual conversion, preview without Colab. |
| [test_phrase_languages.py](test_phrase_languages.py) | Translated cards/speech, per-language cache, batch failures, deletion during translation. |
| [test_phase4.py](test_phase4.py) | Phrase CRUD/favorites/history, prediction, background warming, and deletion races; filename reflects development history. |
| [test_hardening.py](test_hardening.py) | Authentication, host/origin restrictions, rate/body limits, upload admission, dictionary/API-first behavior. |
| [test_safety.py](test_safety.py) | Verification, session expiry, watermark status, emotion references, optional-model failures. |
| [test_evaluation.py](test_evaluation.py) | Evaluator normalization and metric helpers. |

## Run

From the repository root after installing normal backend and test dependencies:

```powershell
.\.venv\Scripts\python.exe -m pytest aria_backend/tests -q
.\.venv\Scripts\python.exe -m pytest aria_backend/tests/test_phrase_languages.py -q
```

For a particular failure, use `-k` with a test-name fragment. Keep new fixtures temporary, prevent real model downloads, and use dummy keys rather than live credentials.

## What passing means

Passing tests support the software contracts and error paths. They do not verify the real user's checkpoint, the acoustic quality of cloning, actual AudioSeal/Whisper/ECAPA accuracy, or production deployment behavior. Those need separate integration and listening checks.

For UI behavior see [desktop tests](../../aria_desktop/tests/README.md); for GPU notebook contracts see [root tests](../../tests/README.md).

## Assistive regressions

[test_assistive.py](test_assistive.py) covers generic provider persistence, consent/scope/recovery, native Urdu, checkpoint identity, manual expression and protected cache failures. [test_research_tools.py](test_research_tools.py) checks evaluation accounting without inventing model or listener outcomes. Legacy experimental fixtures explicitly select research policy.

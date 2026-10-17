# Notebook contract tests

[Project handbook](../README.md)

This root test folder focuses on the GPU notebook's server contract. Backend tests live in [aria_backend/tests](../aria_backend/tests/README.md), and desktop tests in [aria_desktop/tests](../aria_desktop/tests/README.md).

[test_colab_notebook.py](test_colab_notebook.py) loads notebook cell source and executes it with fake model/CUDA objects. It checks authorization, input and latent validation, selected language forwarding, request limits, GPU serialization, safe failure behavior, and server/tunnel startup/shutdown with a fake tunnel.

## Run

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
.\.venv\Scripts\python.exe -m pytest tests/test_colab_notebook.py -q
```

[requirements-test.txt](../requirements-test.txt) supplies CPU notebook-test dependencies. It is not a substitute for the backend/desktop requirement files when running the entire project's tests.

## What these tests deliberately avoid

They do not load XTTS weights, mount Drive, download CUDA models, or evaluate acoustic quality. The fake model checks the shape of the integration, not the behavior of a real speaker checkpoint. Keep real reference recordings and credentials out of fixtures.

When modifying notebook cell IDs or moving code between cells, update the extraction fixtures as well as the notebook. Keep notebook outputs empty before publishing, and exercise the actual public self-test separately when changing GPU integration behavior.

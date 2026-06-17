# Third-party Licenses

This project (Notebook Ollama) is licensed under MIT (see [`LICENSE`](./LICENSE)).
The runtime depends on the following open-source packages. All required
dependencies use permissive licenses (MIT / BSD / Apache-2.0). One optional
dependency uses the AGPL-3.0 license and is **not** installed by default.

## Required dependencies (permissive)

| Package | License |
|---|---|
| fastapi | MIT |
| uvicorn | BSD-3-Clause |
| pydantic, pydantic-settings | MIT |
| httpx, anyio | BSD-3-Clause / MIT |
| structlog | MIT / Apache-2.0 |
| tenacity | Apache-2.0 |
| python-ulid | MIT |
| tiktoken | MIT (OpenAI) |
| python-docx | MIT |
| python-pptx | MIT |
| openpyxl | MIT |
| markdown-it-py | MIT |
| trafilatura | Apache-2.0 |
| qdrant-client | Apache-2.0 |
| python-multipart | Apache-2.0 |
| sse-starlette | BSD-3-Clause |
| mcp (Anthropic) | MIT |
| pyyaml | MIT |
| truststore | MIT |

## Optional dependency (AGPL-3.0)

| Package | License | Notes |
|---|---|---|
| **PyMuPDF** | **AGPL-3.0** | Used only when the PDF parser is invoked. The dependency is not installed by default. Run `scripts/install-pdf-support.sh` (or `.ps1`) to opt-in. |

### What AGPL means here

PyMuPDF is dual-licensed under AGPL-3.0 or a commercial license from Artifex.
If you install the `[pdf]` extra and then **distribute** Notebook Ollama or
**operate it as a network service for third parties**, the AGPL §13 "remote
network interaction" clause may require you to:

- Release the entire combined application's source code under an AGPL-compatible license, and
- Offer your users access to that source code.

For **personal / private use** on a single machine, there are no additional
obligations beyond the AGPL terms applicable to the PyMuPDF binary itself.

If AGPL is incompatible with your deployment plans, you have two options:

1. Purchase a commercial PyMuPDF license from Artifex.
2. Do not install the `[pdf]` extra; replace the PDF parser with a permissively
   licensed alternative (for example, [pypdf](https://pypi.org/project/pypdf/)
   under BSD-3 or [pdfplumber](https://pypi.org/project/pdfplumber/) under MIT)
   and re-implement `core/ingestion/parsers/pdf.py` accordingly.

## Optional dependency group (recording)

The `recording` extra (server-side recording, live caption, STT, speaker
diarization) is **not installed by default**. It pulls in the following
third-party packages — all permissive. The packages are dependencies (not
vendored/copied source), and the STT / diarization **models are not shipped**
with this repository: they are fetched or reused locally and are gitignored.

| Package | License | Notes |
|---|---|---|
| faster-whisper | MIT | |
| ctranslate2 | MIT | CUDA inference engine (pulled by faster-whisper) |
| av (PyAV) | BSD-3-Clause | wraps FFmpeg (LGPL/GPL) dynamically; not statically linked |
| pyaudiowpatch | MIT | PyAudio fork with WASAPI loopback |
| sherpa-onnx | Apache-2.0 | **NOTICE retention required** — keep the upstream NOTICE |
| onnxruntime | MIT | runtime for sherpa-onnx |
| soundfile | BSD-3-Clause | wraps libsndfile (**LGPL-2.1**), dynamically linked in the wheel |
| scipy | BSD-3-Clause | |
| numpy | BSD-3-Clause | |
| webrtcvad-wheels | MIT | wraps Google WebRTC VAD (BSD-3-Clause) |
| huggingface-hub, tokenizers, tqdm | Apache-2.0 / MIT | transitive |

### Models (not shipped, gitignored)

| Model | License | Notes |
|---|---|---|
| Whisper (OpenAI) via Systran faster-whisper-* | MIT | downloaded to the HuggingFace cache on first use |
| sherpa-onnx-pyannote-segmentation-3.0 | MIT | speaker segmentation; keep the model's bundled LICENSE |
| 3D-Speaker ERes2Net embedding | Apache-2.0 | speaker embedding (voiceprint) |

Because these are dependencies/models rather than embedded source, MIT
licensing of this repository's own code is unaffected. Each module vendored
from the author's MIT meeting-transcriber project was audited for embedded
third-party source before inclusion (see `core/recording/PROVENANCE.md`).

## Frontend (apps/web)

The Svelte/Vite frontend uses only permissive (MIT / Apache-2.0) packages
declared in `apps/web/package.json`. None require additional opt-in.

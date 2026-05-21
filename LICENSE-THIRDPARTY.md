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

## Frontend (apps/web)

The Svelte/Vite frontend uses only permissive (MIT / Apache-2.0) packages
declared in `apps/web/package.json`. None require additional opt-in.

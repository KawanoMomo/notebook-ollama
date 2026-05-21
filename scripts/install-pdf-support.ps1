# Opt-in installer for the AGPL-3.0 licensed PyMuPDF dependency, which is
# required for PDF ingestion in Notebook Ollama.
#
# The core Notebook Ollama project is MIT licensed. PyMuPDF is intentionally
# NOT bundled with the default install so that users who do not need PDF
# parsing are not subjected to AGPL obligations.

$ErrorActionPreference = "Stop"

Write-Host @"
==============================================================================
  Notebook Ollama - PDF support installer
==============================================================================
PyMuPDF (https://pymupdf.readthedocs.io/) is required for PDF ingestion.

PyMuPDF is dual-licensed:

  * GNU Affero General Public License v3.0 (AGPL-3.0), OR
  * Commercial license from Artifex Software, Inc.

If you install this dependency and later distribute or operate Notebook Ollama
as a NETWORK SERVICE for third parties, the AGPL "remote network interaction"
clause (Section 13) may require you to release the entire combined
application's source code to your users under AGPL-compatible terms.

For PERSONAL / PRIVATE USE on a single machine, the AGPL obligations are
limited to PyMuPDF itself.

Full text: https://www.gnu.org/licenses/agpl-3.0.html
==============================================================================
"@

$ans = Read-Host "Do you accept these terms and proceed with installation? [y/N]"
if ($ans -notmatch '^[yY](es)?$') {
    Write-Host "Aborted. PDF support was not installed."
    exit 1
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "Installing PyMuPDF via uv..."
    uv sync --extra pdf
} else {
    Write-Host "Installing PyMuPDF via pip..."
    python -m pip install '.[pdf]'
}

Write-Host ""
Write-Host "Done. PDF ingestion is now enabled."

"""PPTX→PDF変換の制御フロー(COMはモック、spec §8 エラー処理)。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import core.ingestion.pptx_to_pdf as mod
from core.ingestion.pptx_to_pdf import PptxConversionError, convert_pptx_to_pdf, slides_pdf_path


def test_slides_pdf_path_mapping(tmp_path):
    assert slides_pdf_path(tmp_path, "S1", "pdf") == tmp_path / "S1.pdf"
    assert slides_pdf_path(tmp_path, "S1", "pptx") == tmp_path / "S1.slides.pdf"
    assert slides_pdf_path(tmp_path, "S1", "markdown") is None


def _install_fake_com(monkeypatch, *, saveas_raises=False, writes_pdf=True):
    fake_pres = MagicMock()
    fake_app = MagicMock()
    fake_app.Presentations.Open.return_value = fake_pres
    created = {}

    def _save_as(dst, fmt):
        if saveas_raises:
            raise RuntimeError("COM failure")
        if writes_pdf:
            Path(dst).write_bytes(b"%PDF-1.4 converted")
        created["fmt"] = fmt

    fake_pres.SaveAs.side_effect = _save_as
    fake_client = MagicMock()
    fake_client.Dispatch.return_value = fake_app
    monkeypatch.setattr(mod, "_com_client", lambda: fake_client)
    monkeypatch.setattr(mod, "_co_initialize", lambda: None)
    monkeypatch.setattr(mod, "_co_uninitialize", lambda: None)
    return fake_app, fake_pres, created


def test_convert_success_closes_and_quits(tmp_path, monkeypatch):
    fake_app, fake_pres, created = _install_fake_com(monkeypatch)
    src = tmp_path / "in.pptx"
    src.write_bytes(b"pptx")
    dst = tmp_path / "out.slides.pdf"

    convert_pptx_to_pdf(src, dst)

    assert dst.exists()
    assert created["fmt"] == 32  # ppSaveAsPDF
    fake_pres.Close.assert_called_once()
    fake_app.Quit.assert_called_once()


def test_convert_failure_raises_and_still_cleans_up(tmp_path, monkeypatch):
    fake_app, fake_pres, _ = _install_fake_com(monkeypatch, saveas_raises=True)
    src = tmp_path / "in.pptx"
    src.write_bytes(b"pptx")

    with pytest.raises(PptxConversionError):
        convert_pptx_to_pdf(src, tmp_path / "out.pdf")

    fake_pres.Close.assert_called_once()
    fake_app.Quit.assert_called_once()


def test_convert_missing_output_raises(tmp_path, monkeypatch):
    _install_fake_com(monkeypatch, writes_pdf=False)
    src = tmp_path / "in.pptx"
    src.write_bytes(b"pptx")
    with pytest.raises(PptxConversionError):
        convert_pptx_to_pdf(src, tmp_path / "out.pdf")

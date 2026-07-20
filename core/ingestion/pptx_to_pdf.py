"""PPTX→PDF 変換(PowerPoint COM、spec §5 / ADRドラフト pptx-render-powerpoint-com)。

取込時に一度だけ `<id>.slides.pdf` を併産する。COM は対話ユーザーセッション
前提のため、失敗しても取込自体は継続する(呼び出し側が best-effort で包む)。
テスト容易性のため COM への入口(_com_client/_co_initialize)を関数に切り出し、
テストは monkeypatch で差し替える。
"""
from __future__ import annotations

import sys
from pathlib import Path

from core.logging import get_logger

log = get_logger("pptx_to_pdf")

_PP_SAVE_AS_PDF = 32  # PowerPoint ppSaveAsPDF


class PptxConversionError(Exception):
    pass


def slides_pdf_path(sources_dir: Path, source_id: str, kind: str) -> Path | None:
    """スライド表示に使う PDF のパス。pdf は原本、pptx は COM 併産物。"""
    if kind == "pdf":
        return sources_dir / f"{source_id}.pdf"
    if kind == "pptx":
        return sources_dir / f"{source_id}.slides.pdf"
    return None


def _com_client():
    import win32com.client
    return win32com.client


def _co_initialize() -> None:
    import pythoncom
    pythoncom.CoInitialize()


def _co_uninitialize() -> None:
    import pythoncom
    pythoncom.CoUninitialize()


def is_powerpoint_available() -> bool:
    """COM 経由の PowerPoint が使えそうかの軽量判定。"""
    if sys.platform != "win32":
        return False
    try:
        _com_client()
        return True
    except Exception:
        return False


def convert_pptx_to_pdf(pptx_path: Path, pdf_path: Path, *, timeout_s: float = 120.0) -> None:
    """PPTX を PDF に変換する(同期・ブロッキング。呼び出し側が thread で包む)。

    timeout_s は将来 COM 呼び出しの watchdog に使う予約引数(v1 では
    PowerPoint の SaveAs がハングした場合に備え、呼び出し側の
    asyncio.wait_for(asyncio.to_thread(...)) で外側から制限する)。
    """
    client = None
    app = None
    pres = None
    _co_initialize()
    try:
        client = _com_client()
        app = client.Dispatch("PowerPoint.Application")
        pres = app.Presentations.Open(str(pptx_path), ReadOnly=True,
                                      Untitled=False, WithWindow=False)
        pres.SaveAs(str(pdf_path), _PP_SAVE_AS_PDF)
        if not pdf_path.exists():
            raise PptxConversionError(f"conversion produced no output: {pdf_path}")
    except PptxConversionError:
        raise
    except Exception as exc:
        raise PptxConversionError(f"PowerPoint COM conversion failed: {exc}") from exc
    finally:
        # プロセスを残さない(spec §8)。Close/Quit 自体の失敗は握りつぶす。
        try:
            if pres is not None:
                pres.Close()
        except Exception:
            log.warning("pptx_close_failed")
        try:
            if app is not None:
                app.Quit()
        except Exception:
            log.warning("powerpoint_quit_failed")
        _co_uninitialize()

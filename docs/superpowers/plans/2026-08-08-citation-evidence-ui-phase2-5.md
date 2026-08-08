# 出典表示の刷新 — Phase 2〜5 実装計画(原本ページ矩形 / quote モードβ / 選択範囲翻訳)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 出典パネルに「原本ページ＋根拠箇所の矩形」タブを足し、言語跨ぎ用の quote モード(β)と選択範囲の翻訳を実装する。

**Architecture:** 原本ページは**リクエスト時に PyMuPDF で描画してディスクにキャッシュ**する(事前生成なし)。矩形は、表・図チャンクは**取込済みアセットの bbox を流用**し、通常テキストのみ `page.search_for(quote)` を使う。quote モードは既存のベータフラグレジストリに載せ、既定 OFF のままプロンプトを変えない。翻訳は既存 Ollama ゲートウェイの `chat_stream` を SSE で中継する。

**Tech Stack:** Python 3 / FastAPI / PyMuPDF (`pymupdf`) / pytest、SvelteKit + Svelte 5 runes / vitest

**前提:** Phase 1 / 1.5 は実装・実機ゲート通過済み(`docs/superpowers/plans/2026-08-07-citation-evidence-ui-phase1.md`)。設計は `docs/specs/2026-08-07-citation-evidence-ui-design.md` の §3.4 / §3.5 / §3.6。

## Global Constraints

- 索引サイズ・ingest 時間を増やさない。**ページ画像は事前生成しない**(リクエスト時描画＋ディスクキャッシュ)。
- `dpi` は **150 / 300 の許可リスト**に限定する(自由入力はディスクを無制限に消費する)。
- 表・図チャンクは `page.search_for` を使わない(取込時に Markdown 化され原本に存在しないため原理的に空振りする)。**アセットの bbox を流用**する。
- quote モード(β)は **既定 OFF**。OFF のときプロンプト・生成経路は現行のままバイト単位で不変。
- 翻訳はチャット生成ストリーム実行中は実行しない(VRAM の取り合いを避ける。第2段と同じ扱い)。
- 原本タブは **PDF 由来のソースのみ**(`slides_pdf_path` が解決できるもの)。録音・テキストでは出さない。
- BE テスト: `uv run --no-sync pytest <path> -v`。FE テスト: `cd apps/web && npx vitest run <path>`。
- 作業ブランチは `spec/citation-evidence-ui`。
- コミットは `git-safe commit-paths <メッセージファイル> <path>...` を使う(専用 index 経由。並列作業と衝突しない)。パスは自分が触ったものだけ。

## 既存コードの事実(調査済み・前提にしてよい)

| 事実 | 根拠 |
|---|---|
| sources ルータの prefix は `/api/notebooks` | `apps/api/routers/sources.py:35` |
| PDF 実体は `slides_pdf_path(sources_dir, source_id, kind)` で解決できる(pdf は `{id}.pdf`、pptx は `{id}.slides.pdf`) | `core/ingestion/pptx_to_pdf.py:24-29` |
| アセットは `page`(1起算でない可能性あり→実装時に確認)と `bbox_json` を持つ。bbox は `(x0, y0, x1, y1)` の PDF 座標 | `core/storage/assets_repo.py`, `core/ingestion/pdf_assets.py:74` |
| ベータフラグは `core/features.py` の `REGISTRY` に1エントリ足すだけ。判定は `is_enabled(flag_id, optins)` | `core/features.py:37` |
| 生成は `gateway.chat_stream(model=..., messages=[...], options=..., meta=...)` が `AsyncIterator[str]` | `core/ollama/gateway.py:40` |
| 生成ストリーム実行中かは `is_stream_running(conversation_id)` で判定できる | `core/generation/stream_registry.py` |

## File Structure

| ファイル | 責務 |
|---|---|
| `core/sources/page_render.py` (新規) | PDF ページの PNG 描画とディスクキャッシュ。dpi 許可リスト |
| `core/sources/page_rects.py` (新規) | 矩形の決定。アセット bbox 流用と `search_for` フォールバック |
| `apps/api/routers/sources.py` (変更) | ページ PNG / 矩形の2エンドポイント、ソース削除時のキャッシュ削除 |
| `core/translation/translator.py` (新規) | 翻訳プロンプト組み立てと `chat_stream` 中継 |
| `apps/api/routers/translate.py` (新規) | `POST /api/translate` の SSE |
| `core/features.py` (変更) | `citation-quote-mode` フラグ追加 |
| `core/generation/quote_spans.py` (新規) | 応答から `<q>` を抽出し spans 化(method="quote") |
| `core/generation/prompt.py` (変更) | quote モード ON のときだけ指示文を足す |
| `apps/web/src/lib/api/pages.ts` (新規) | ページ画像 URL と矩形取得 |
| `apps/web/src/lib/components/OriginalPageView.svelte` (新規) | ページ画像＋矩形オーバーレイ＋拡大＋ページ送り |
| `apps/web/src/lib/components/SourceViewer.svelte` (変更) | タブ切替、選択範囲翻訳のポップオーバー |
| `apps/web/src/lib/api/translate.ts` (新規) | 翻訳 SSE クライアント |

---

## Phase 2 — 原本ページと表・図の矩形

### Task 1: ページ PNG 描画とディスクキャッシュ

**Files:**
- Create: `core/sources/page_render.py`
- Test: `tests/unit/test_page_render.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `ALLOWED_DPI: frozenset[int]`(= `{150, 300}`)
  - `class UnsupportedDpiError(ValueError)`
  - `render_page_png(pdf_path: Path, page: int, dpi: int, cache_dir: Path) -> bytes` — `page` は 1 起算
  - `cache_path_for(cache_dir: Path, source_id: str, page: int, dpi: int) -> Path`
  - `purge_source_cache(cache_dir: Path, source_id: str) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_page_render.py
import pytest
import pymupdf

from core.sources.page_render import (
    ALLOWED_DPI,
    UnsupportedDpiError,
    cache_path_for,
    purge_source_cache,
    render_page_png,
)


def _make_pdf(path, pages=2):
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 500, 200), f"page {i + 1}", fontsize=14)
    doc.save(path)
    doc.close()


def test_renders_png_bytes(tmp_path):
    pdf = tmp_path / "s.pdf"
    _make_pdf(pdf)
    out = render_page_png(pdf, page=1, dpi=150, cache_dir=tmp_path / "cache")
    assert out.startswith(b"\x89PNG")


def test_second_call_hits_cache(tmp_path):
    pdf = tmp_path / "s.pdf"
    _make_pdf(pdf)
    cache = tmp_path / "cache"
    first = render_page_png(pdf, page=1, dpi=150, cache_dir=cache)
    cached_file = next(cache.rglob("*.png"))
    cached_file.write_bytes(b"\x89PNG-sentinel")
    second = render_page_png(pdf, page=1, dpi=150, cache_dir=cache)
    assert second == b"\x89PNG-sentinel"
    assert first != second


def test_rejects_dpi_outside_allowlist(tmp_path):
    pdf = tmp_path / "s.pdf"
    _make_pdf(pdf)
    with pytest.raises(UnsupportedDpiError):
        render_page_png(pdf, page=1, dpi=1200, cache_dir=tmp_path / "cache")
    assert ALLOWED_DPI == frozenset({150, 300})


def test_rejects_out_of_range_page(tmp_path):
    pdf = tmp_path / "s.pdf"
    _make_pdf(pdf, pages=2)
    with pytest.raises(IndexError):
        render_page_png(pdf, page=3, dpi=150, cache_dir=tmp_path / "cache")


def test_purge_removes_only_that_source(tmp_path):
    cache = tmp_path / "cache"
    a = cache_path_for(cache, "src-a", 1, 150)
    b = cache_path_for(cache, "src-b", 1, 150)
    for p in (a, b):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    purge_source_cache(cache, "src-a")
    assert not a.exists()
    assert b.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_page_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.sources.page_render'`

- [ ] **Step 3: Write minimal implementation**

`core/sources/__init__.py` が無ければ空ファイルで作る。

```python
# core/sources/page_render.py
"""PDF ページのオンデマンド描画とディスクキャッシュ。

設計: docs/specs/2026-08-07-citation-evidence-ui-design.md §3.4

事前生成はしない(索引サイズと ingest 時間を増やさないため)。押されたページだけ
描画し、`data/cache/pages/{source_id}/{page}@{dpi}.png` に貯める。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pymupdf

# 自由入力を許すと 1 リクエストで数十 MB を生成でき、ディスクを無制限に食う。
ALLOWED_DPI = frozenset({150, 300})


class UnsupportedDpiError(ValueError):
    """許可リスト外の dpi。"""


def cache_path_for(cache_dir: Path, source_id: str, page: int, dpi: int) -> Path:
    return cache_dir / source_id / f"{page}@{dpi}.png"


def purge_source_cache(cache_dir: Path, source_id: str) -> None:
    shutil.rmtree(cache_dir / source_id, ignore_errors=True)


def render_page_png(*, pdf_path: Path, page: int, dpi: int, cache_dir: Path) -> bytes:
    """1 起算のページ番号を PNG バイト列にする。キャッシュがあればそれを返す。"""
    if dpi not in ALLOWED_DPI:
        raise UnsupportedDpiError(f"dpi must be one of {sorted(ALLOWED_DPI)}: {dpi}")

    cached = cache_path_for(cache_dir, pdf_path.stem, page, dpi)
    if cached.exists():
        return cached.read_bytes()

    with pymupdf.open(pdf_path) as doc:
        if page < 1 or page > doc.page_count:
            raise IndexError(f"page out of range: {page} (1..{doc.page_count})")
        data: bytes = doc[page - 1].get_pixmap(dpi=dpi).tobytes("png")

    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return data
```

> テストは `render_page_png(pdf, page=1, ...)` と位置引数で書かれている。実装をキーワード
> 専用にするならテスト側も `pdf_path=pdf` に直すこと(**テストの意図は変えない**)。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/unit/test_page_render.py -v`
Expected: PASS(5件)

- [ ] **Step 5: Commit**

```bash
git-safe commit-paths <msg> core/sources/__init__.py core/sources/page_render.py tests/unit/test_page_render.py
```
メッセージ: `feat(sources): PDFページのオンデマンド描画とディスクキャッシュを追加`

---

### Task 2: 矩形の決定(アセット bbox 流用 / search_for フォールバック)

**Files:**
- Create: `core/sources/page_rects.py`
- Test: `tests/unit/test_page_rects.py`

**Interfaces:**
- Consumes: Task 1 の `ALLOWED_DPI`(スケール換算に dpi を使う)
- Produces:
  - `@dataclass(frozen=True) Rect: x: float; y: float; w: float; h: float`(**PNG ピクセル座標**)
  - `rects_from_asset_bbox(bbox_json: str | None, dpi: int) -> list[Rect]`
  - `rects_from_quote(pdf_path: Path, page: int, quote: str, dpi: int) -> list[Rect]`

**Notes:** PDF 座標は 72dpi 基準。PNG は `dpi` で描画するので、スケールは `dpi / 72`。FE は
PNG の実ピクセルサイズに対して相対配置するので、ここでピクセルへ換算しておく。

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_page_rects.py
import json

import pymupdf

from core.sources.page_rects import Rect, rects_from_asset_bbox, rects_from_quote


def test_asset_bbox_is_scaled_from_points_to_pixels():
    bbox = json.dumps([72.0, 144.0, 144.0, 216.0])  # 1inch,2inch → 2inch,3inch
    got = rects_from_asset_bbox(bbox, dpi=150)
    assert len(got) == 1
    r = got[0]
    assert r == Rect(x=150.0, y=300.0, w=150.0, h=150.0)


def test_asset_bbox_none_returns_empty():
    assert rects_from_asset_bbox(None, dpi=150) == []


def test_asset_bbox_broken_json_returns_empty():
    assert rects_from_asset_bbox("not json", dpi=150) == []


def _make_pdf(path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(
        pymupdf.Rect(50, 100, 500, 200),
        "The process achieves its outcomes.",
        fontsize=12,
        fontname="helv",
    )
    doc.save(path)
    doc.close()


def test_quote_search_finds_rect(tmp_path):
    pdf = tmp_path / "s.pdf"
    _make_pdf(pdf)
    got = rects_from_quote(pdf, page=1, quote="achieves its outcomes", dpi=150)
    assert len(got) >= 1
    assert got[0].w > 0 and got[0].h > 0


def test_quote_not_found_returns_empty(tmp_path):
    pdf = tmp_path / "s.pdf"
    _make_pdf(pdf)
    assert rects_from_quote(pdf, page=1, quote="no such sentence here", dpi=150) == []


def test_quote_falls_back_to_word_pieces(tmp_path):
    """行末ハイフネーション等で全体一致しない場合、単語単位の部分一致で拾う。"""
    pdf = tmp_path / "s.pdf"
    _make_pdf(pdf)
    got = rects_from_quote(
        pdf, page=1, quote="The process ZZZ achieves its outcomes", dpi=150
    )
    assert len(got) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_page_rects.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.sources.page_rects'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/sources/page_rects.py
"""原本ページ上の矩形の決定。

設計: docs/specs/2026-08-07-citation-evidence-ui-design.md §3.4

表・図チャンクは取込時に Markdown 化されて原本に存在しないため、search_for は
原理的に空振りする。取込済みアセットの bbox を流用する方が精度も高い。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pymupdf

_POINTS_PER_INCH = 72.0
# 単語単位フォールバックで、この長さ未満の語は無視する(前置詞等でページ中が光るのを防ぐ)。
_MIN_WORD_CHARS = 4


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float


def _scale(dpi: int) -> float:
    return dpi / _POINTS_PER_INCH


def rects_from_asset_bbox(bbox_json: str | None, dpi: int) -> list[Rect]:
    if not bbox_json:
        return []
    try:
        raw = json.loads(bbox_json)
    except (TypeError, ValueError):
        return []
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return []
    x0, y0, x1, y1 = (float(v) for v in raw)
    s = _scale(dpi)
    return [Rect(x=x0 * s, y=y0 * s, w=(x1 - x0) * s, h=(y1 - y0) * s)]


def _to_rects(found: list, dpi: int) -> list[Rect]:
    s = _scale(dpi)
    return [
        Rect(x=r.x0 * s, y=r.y0 * s, w=(r.x1 - r.x0) * s, h=(r.y1 - r.y0) * s)
        for r in found
    ]


def rects_from_quote(pdf_path: Path, page: int, quote: str, dpi: int) -> list[Rect]:
    """quote に対応する矩形。全体一致 → 単語単位の順に試し、駄目なら空。"""
    text = " ".join(quote.split())
    if not text:
        return []
    with pymupdf.open(pdf_path) as doc:
        if page < 1 or page > doc.page_count:
            return []
        pg = doc[page - 1]
        found = pg.search_for(text)
        if found:
            return _to_rects(found, dpi)
        # 行末ハイフネーションや抽出順のズレで全体一致しないことがある。
        # 単語単位で拾って和を取る(一段だけのフォールバック)。
        pieces: list = []
        for word in text.split(" "):
            if len(word) < _MIN_WORD_CHARS:
                continue
            pieces.extend(pg.search_for(word))
        return _to_rects(pieces, dpi)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/unit/test_page_rects.py -v`
Expected: PASS(6件)

- [ ] **Step 5: Commit**

メッセージ: `feat(sources): 原本ページ矩形の決定(アセットbbox流用とsearch_forフォールバック)`

---

### Task 3: ページ画像と矩形の API

**Files:**
- Modify: `apps/api/routers/sources.py`
- Test: `tests/integration/test_page_endpoints.py`

**Interfaces:**
- Consumes: Task 1 の `render_page_png` / `UnsupportedDpiError`、Task 2 の `rects_from_asset_bbox` / `rects_from_quote`
- Produces:
  - `GET /api/notebooks/{notebook_id}/sources/{source_id}/pages/{page}?dpi=150` → `image/png`
  - `POST /api/notebooks/{notebook_id}/sources/{source_id}/pages/{page}/rects` `{chunk_id, quote, dpi}` → `{"rects": [{"x":..,"y":..,"w":..,"h":..}], "source": "asset"|"quote"|"none"}`

**Notes:** 矩形は「そのチャンクに表・図アセットがあるか」で分岐する。あれば bbox 流用
(`source="asset"`)、無ければ `search_for`(`source="quote"`)。どちらも取れなければ
`rects=[]`, `source="none"` を返す(FE は「枠は特定できません」と出す)。

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_page_endpoints.py
"""ページ画像・矩形エンドポイントの契約。

セットアップは tests/integration/test_api/ 配下の既存テストに倣うこと
(app 構築とテンポラリ data_dir の作り方はそこにある)。
"""


def test_page_png_returns_image(client, seeded_pdf_source):
    nb, src = seeded_pdf_source
    res = client.get(f"/api/notebooks/{nb}/sources/{src}/pages/1?dpi=150")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.content.startswith(b"\x89PNG")


def test_page_png_rejects_dpi_outside_allowlist(client, seeded_pdf_source):
    nb, src = seeded_pdf_source
    res = client.get(f"/api/notebooks/{nb}/sources/{src}/pages/1?dpi=1200")
    assert res.status_code == 400


def test_page_png_404_for_out_of_range_page(client, seeded_pdf_source):
    nb, src = seeded_pdf_source
    res = client.get(f"/api/notebooks/{nb}/sources/{src}/pages/999?dpi=150")
    assert res.status_code == 404


def test_page_png_404_for_non_pdf_source(client, seeded_text_source):
    nb, src = seeded_text_source
    res = client.get(f"/api/notebooks/{nb}/sources/{src}/pages/1?dpi=150")
    assert res.status_code == 404


def test_rects_uses_asset_bbox_when_chunk_has_asset(client, seeded_pdf_source_with_table_asset):
    nb, src, chunk_id = seeded_pdf_source_with_table_asset
    res = client.post(
        f"/api/notebooks/{nb}/sources/{src}/pages/1/rects",
        json={"chunk_id": chunk_id, "quote": "この文字列は原本に存在しない", "dpi": 150},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["source"] == "asset"
    assert len(body["rects"]) == 1


def test_rects_falls_back_to_quote_search(client, seeded_pdf_source):
    nb, src = seeded_pdf_source
    res = client.post(
        f"/api/notebooks/{nb}/sources/{src}/pages/1/rects",
        json={"chunk_id": "no-such-chunk", "quote": "no such sentence", "dpi": 150},
    )
    assert res.status_code == 200
    assert res.json()["source"] in ("quote", "none")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/integration/test_page_endpoints.py -v`
Expected: FAIL — ルート未定義(404 ではなく `AssertionError` / フィクスチャ未整備)。既存テストに倣ってフィクスチャを用意し、**エンドポイント未実装が理由で落ちる状態**にしてから進む。

- [ ] **Step 3: Write minimal implementation**

`apps/api/schemas/source.py` に追記:

```python
class PageRectsRequest(BaseModel):
    chunk_id: str
    quote: str
    dpi: int = 150


class PageRect(BaseModel):
    x: float
    y: float
    w: float
    h: float


class PageRectsResponse(BaseModel):
    rects: list[PageRect]
    source: str  # "asset" | "quote" | "none"
```

`apps/api/routers/sources.py` に追記:

```python
from fastapi import Response

from core.ingestion.pptx_to_pdf import slides_pdf_path
from core.sources.page_render import UnsupportedDpiError, render_page_png
from core.sources.page_rects import rects_from_asset_bbox, rects_from_quote


def _pdf_path_for(ctx, rec) -> Path | None:
    path = slides_pdf_path(ctx.config.sources_dir, rec.id, rec.kind)
    return path if path is not None and path.exists() else None


def _pages_cache_dir(ctx) -> Path:
    return ctx.config.data_dir / "cache" / "pages"


@router.get("/{notebook_id}/sources/{source_id}/pages/{page}")
def get_source_page(notebook_id: str, source_id: str, page: int, dpi: int = 150, ...):
    rec = sources_repo.get_source(conn, source_id)
    if rec is None or rec.notebook_id != notebook_id:
        raise HTTPException(status_code=404, detail="source not found")
    pdf = _pdf_path_for(ctx, rec)
    if pdf is None:
        raise HTTPException(status_code=404, detail="source has no original PDF")
    try:
        data = render_page_png(
            pdf_path=pdf, page=page, dpi=dpi, cache_dir=_pages_cache_dir(ctx)
        )
    except UnsupportedDpiError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except IndexError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return Response(content=data, media_type="image/png")


@router.post(
    "/{notebook_id}/sources/{source_id}/pages/{page}/rects",
    response_model=PageRectsResponse,
)
def get_source_page_rects(
    notebook_id: str, source_id: str, page: int, body: PageRectsRequest, ...
):
    rec = sources_repo.get_source(conn, source_id)
    if rec is None or rec.notebook_id != notebook_id:
        raise HTTPException(status_code=404, detail="source not found")
    pdf = _pdf_path_for(ctx, rec)
    if pdf is None:
        raise HTTPException(status_code=404, detail="source has no original PDF")

    # 表・図チャンクは取込時に Markdown 化され原本に存在しないので search_for は
    # 原理的に当たらない。アセットの bbox を使う。
    for asset in assets_repo.list_assets(conn, source_id):
        if asset.chunk_id == body.chunk_id and asset.bbox_json:
            rects = rects_from_asset_bbox(asset.bbox_json, body.dpi)
            if rects:
                return PageRectsResponse(rects=rects, source="asset")

    rects = rects_from_quote(pdf, page=page, quote=body.quote, dpi=body.dpi)
    return PageRectsResponse(rects=rects, source="quote" if rects else "none")
```

> 依存注入(`conn` / `ctx`)の受け取り方と `sources_repo` / `assets_repo` の正確な関数名は、
> 同ファイルの既存エンドポイントに厳密に倣うこと。`Path` の import 漏れに注意。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/integration/test_page_endpoints.py -v && uv run --no-sync pytest -q`
Expected: 新規 PASS、既存の回帰なし

- [ ] **Step 5: Commit**

メッセージ: `feat(api): 原本ページ画像と矩形のエンドポイントを追加`

---

### Task 4: ソース削除時のページキャッシュ削除

**Files:**
- Modify: `apps/api/routers/sources.py`(削除エンドポイント)
- Test: `tests/integration/test_page_cache_purge.py`

**Interfaces:**
- Consumes: Task 1 の `purge_source_cache`
- Produces: なし(副作用のみ)

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_page_cache_purge.py
def test_deleting_source_removes_page_cache(client, seeded_pdf_source, data_dir):
    nb, src = seeded_pdf_source
    assert client.get(f"/api/notebooks/{nb}/sources/{src}/pages/1?dpi=150").status_code == 200
    cache_dir = data_dir / "cache" / "pages" / src
    assert cache_dir.exists()

    assert client.delete(f"/api/notebooks/{nb}/sources/{src}").status_code in (200, 204)
    assert not cache_dir.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/integration/test_page_cache_purge.py -v`
Expected: FAIL — 削除後もキャッシュディレクトリが残る

- [ ] **Step 3: Write minimal implementation**

削除エンドポイントの本体(ソース行を消している箇所)に1行足す。

```python
from core.sources.page_render import purge_source_cache

    # ソースを消したらページ画像キャッシュも消す(残すとディスクを食い続ける)
    purge_source_cache(ctx.config.data_dir / "cache" / "pages", source_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/integration/test_page_cache_purge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

メッセージ: `fix(api): ソース削除時に原本ページキャッシュも削除する`

---

### Task 5: FE — ページ API クライアント

**Files:**
- Create: `apps/web/src/lib/api/pages.ts`
- Test: `apps/web/tests/unit/pagesApi.test.ts`

**Interfaces:**
- Consumes: Task 3 のエンドポイント
- Produces:
  - `pageImageUrl(notebookId: string, sourceId: string, page: number, dpi?: number): string`
  - `interface PageRect { x: number; y: number; w: number; h: number }`
  - `fetchPageRects(notebookId, sourceId, page, chunkId, quote, dpi?): Promise<{ rects: PageRect[]; source: 'asset' | 'quote' | 'none' }>`

- [ ] **Step 1: Write the failing test**

```ts
// apps/web/tests/unit/pagesApi.test.ts
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchPageRects, pageImageUrl } from '../../src/lib/api/pages';

afterEach(() => vi.unstubAllGlobals());

describe('pages api', () => {
  it('画像URLを組み立てる', () => {
    expect(pageImageUrl('nb', 'src', 3)).toBe('/api/notebooks/nb/sources/src/pages/3?dpi=150');
    expect(pageImageUrl('nb', 'src', 3, 300)).toContain('dpi=300');
  });

  it('矩形を取得する', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        json: async () => ({ rects: [{ x: 1, y: 2, w: 3, h: 4 }], source: 'asset' }),
      })),
    );
    const got = await fetchPageRects('nb', 'src', 1, 'c1', 'quote');
    expect(got.source).toBe('asset');
    expect(got.rects).toHaveLength(1);
  });

  it('失敗しても例外を投げず空を返す(閲覧を妨げない)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500 })));
    await expect(fetchPageRects('nb', 'src', 1, 'c1', 'q')).resolves.toEqual({
      rects: [],
      source: 'none',
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && npx vitest run tests/unit/pagesApi.test.ts`
Expected: FAIL — モジュールが存在しない

- [ ] **Step 3: Write minimal implementation**

```ts
// apps/web/src/lib/api/pages.ts
export interface PageRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface PageRectsResult {
  rects: PageRect[];
  source: 'asset' | 'quote' | 'none';
}

/** 原本ページ画像の URL。dpi はサーバ側で 150/300 に限定されている。 */
export function pageImageUrl(
  notebookId: string,
  sourceId: string,
  page: number,
  dpi = 150,
): string {
  return `/api/notebooks/${notebookId}/sources/${sourceId}/pages/${page}?dpi=${dpi}`;
}

/** 根拠箇所の矩形。取れなくても閲覧を妨げないよう、失敗時は空を返す。 */
export async function fetchPageRects(
  notebookId: string,
  sourceId: string,
  page: number,
  chunkId: string,
  quote: string,
  dpi = 150,
): Promise<PageRectsResult> {
  try {
    const res = await fetch(
      `/api/notebooks/${notebookId}/sources/${sourceId}/pages/${page}/rects`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ chunk_id: chunkId, quote, dpi }),
      },
    );
    if (!res.ok) return { rects: [], source: 'none' };
    return await res.json();
  } catch {
    return { rects: [], source: 'none' };
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/web && npx vitest run tests/unit/pagesApi.test.ts`
Expected: PASS(3件)

- [ ] **Step 5: Commit**

メッセージ: `feat(web): 原本ページ画像と矩形のAPIクライアントを追加`

---

### Task 6: FE — 原本ページ表示コンポーネント

**Files:**
- Create: `apps/web/src/lib/components/OriginalPageView.svelte`
- Test: `apps/web/tests/unit/originalPageGeometry.test.ts`
- Create: `apps/web/src/lib/utils/pageGeometry.ts`

**Interfaces:**
- Consumes: Task 5 の `pageImageUrl` / `fetchPageRects` / `PageRect`
- Produces:
  - `pageGeometry.ts`: `toPercentBox(rect: PageRect, naturalWidth: number, naturalHeight: number): { left: string; top: string; width: string; height: string }`
  - `OriginalPageView.svelte` の props: `{ notebookId, sourceId, page, chunkId, quote }`

**Notes:** 画像は `width: 100%` で縮小表示するので、矩形は**パーセント指定**で重ねる。
ピクセル固定だと拡大時にズレる。幾何計算だけを純関数に切り出してテストする
(コンポーネント全体は実機スクリーンショットで担保する)。

- [ ] **Step 1: Write the failing test**

```ts
// apps/web/tests/unit/originalPageGeometry.test.ts
import { describe, expect, it } from 'vitest';
import { toPercentBox } from '../../src/lib/utils/pageGeometry';

describe('toPercentBox', () => {
  it('自然サイズに対する百分率へ変換する', () => {
    const got = toPercentBox({ x: 50, y: 100, w: 200, h: 40 }, 1000, 2000);
    expect(got).toEqual({ left: '5%', top: '5%', width: '20%', height: '2%' });
  });

  it('自然サイズが未確定(0)なら 0% を返して壊れない', () => {
    const got = toPercentBox({ x: 10, y: 10, w: 10, h: 10 }, 0, 0);
    expect(got).toEqual({ left: '0%', top: '0%', width: '0%', height: '0%' });
  });

  it('はみ出す矩形は 100% に丸める', () => {
    const got = toPercentBox({ x: 900, y: 0, w: 500, h: 10 }, 1000, 1000);
    expect(got.left).toBe('90%');
    expect(got.width).toBe('10%');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && npx vitest run tests/unit/originalPageGeometry.test.ts`
Expected: FAIL — モジュールが存在しない

- [ ] **Step 3: Write minimal implementation**

```ts
// apps/web/src/lib/utils/pageGeometry.ts
import type { PageRect } from '$lib/api/pages';

/**
 * 矩形を画像の自然サイズに対する百分率へ変換する。
 * 画像は width:100% で縮小表示するため、ピクセル固定だと拡大時にズレる。
 */
export function toPercentBox(
  rect: PageRect,
  naturalWidth: number,
  naturalHeight: number,
): { left: string; top: string; width: string; height: string } {
  if (!naturalWidth || !naturalHeight) {
    return { left: '0%', top: '0%', width: '0%', height: '0%' };
  }
  const pct = (v: number, total: number) => Math.max(0, Math.min(100, (v / total) * 100));
  const left = pct(rect.x, naturalWidth);
  const top = pct(rect.y, naturalHeight);
  return {
    left: `${left}%`,
    top: `${top}%`,
    width: `${Math.min(100 - left, pct(rect.w, naturalWidth))}%`,
    height: `${Math.min(100 - top, pct(rect.h, naturalHeight))}%`,
  };
}
```

```svelte
<!-- apps/web/src/lib/components/OriginalPageView.svelte -->
<script lang="ts">
  import { fetchPageRects, pageImageUrl, type PageRect } from '$lib/api/pages';
  import { toPercentBox } from '$lib/utils/pageGeometry';

  interface Props {
    notebookId: string;
    sourceId: string;
    page: number;
    chunkId: string;
    quote: string;
  }
  let { notebookId, sourceId, page, chunkId, quote }: Props = $props();

  let current = $state(page);
  let rects = $state<PageRect[]>([]);
  let rectSource = $state<'asset' | 'quote' | 'none'>('none');
  let natural = $state({ w: 0, h: 0 });
  let zoomed = $state(false);
  let fetchSeq = 0;

  $effect(() => {
    current = page; // 引用が変わったら該当ページへ戻す
  });

  $effect(() => {
    const nb = notebookId;
    const sid = sourceId;
    const p = current;
    const seq = ++fetchSeq; // in-flight の古い応答で上書きされないようにする
    rects = [];
    fetchPageRects(nb, sid, p, chunkId, quote).then((r) => {
      if (seq !== fetchSeq) return;
      rects = r.rects;
      rectSource = r.source;
    });
  });

  function onImageLoad(e: Event) {
    const img = e.currentTarget as HTMLImageElement;
    natural = { w: img.naturalWidth, h: img.naturalHeight };
  }
</script>

<div class="wrap" class:zoomed>
  <div class="page">
    <img src={pageImageUrl(notebookId, sourceId, current, zoomed ? 300 : 150)}
         alt={`原本 p.${current}`} onload={onImageLoad} />
    {#each rects as r}
      {@const box = toPercentBox(r, natural.w, natural.h)}
      <span class="box" style:left={box.left} style:top={box.top}
            style:width={box.width} style:height={box.height}></span>
    {/each}
  </div>
  <div class="bar">
    <button onclick={() => (current = Math.max(1, current - 1))}>◀ p.{Math.max(1, current - 1)}</button>
    <button onclick={() => (zoomed = !zoomed)}>{zoomed ? '縮小' : '拡大'}</button>
    <button onclick={() => (current = current + 1)}>p.{current + 1} ▶</button>
  </div>
  {#if rectSource === 'none'}
    <p class="note">枠は特定できません(原本上で該当箇所を見つけられませんでした)</p>
  {/if}
</div>

<style>
  .page { position: relative; line-height: 0; }
  .page img { width: 100%; border: 1px solid var(--color-border); border-radius: var(--radius-sm); }
  .box {
    position: absolute;
    border: 2px solid var(--color-evidence);
    background: var(--color-evidence-faint);
    border-radius: 2px;
    pointer-events: none;
  }
  .bar { display: flex; gap: var(--space-2); margin-top: var(--space-2); }
  .bar button {
    border: 1px solid var(--color-border);
    background: var(--color-bg);
    border-radius: var(--radius-sm);
    padding: 2px 8px;
    font-size: 11px;
  }
  .note { font-size: 11px; color: var(--color-fg-muted); margin: var(--space-2) 0 0; }
  .wrap.zoomed { position: fixed; inset: 5%; background: var(--color-bg); z-index: 50;
    overflow: auto; padding: var(--space-4); box-shadow: 0 10px 40px rgba(0,0,0,.3); }
</style>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/web && npx vitest run tests/unit/originalPageGeometry.test.ts && npm run build`
Expected: PASS(3件)、ビルド成功

- [ ] **Step 5: Commit**

メッセージ: `feat(web): 原本ページ表示コンポーネント(矩形オーバーレイ付き)を追加`

---

### Task 7: FE — 出典パネルのタブ切替

**Files:**
- Modify: `apps/web/src/lib/components/SourceViewer.svelte`
- Test: `apps/web/tests/unit/sourceViewerTabs.test.ts`
- Create: `apps/web/src/lib/utils/originalTab.ts`

**Interfaces:**
- Consumes: Task 6 の `OriginalPageView`
- Produces: `originalTab.ts`: `canShowOriginal(kind: string | undefined, page: number | null | undefined): boolean`

**Notes:** 原本タブは **PDF / PPTX 由来のみ**、かつチャンクがページ番号を持つときだけ出す。
録音・テキスト・Web 取り込みでは**タブ自体を出さない**(spec §3.4)。

- [ ] **Step 1: Write the failing test**

```ts
// apps/web/tests/unit/sourceViewerTabs.test.ts
import { describe, expect, it } from 'vitest';
import { canShowOriginal } from '../../src/lib/utils/originalTab';

describe('canShowOriginal', () => {
  it('PDFでページがあれば出す', () => {
    expect(canShowOriginal('pdf', 3)).toBe(true);
  });
  it('PPTXでも出す(COMでPDF併産している)', () => {
    expect(canShowOriginal('pptx', 1)).toBe(true);
  });
  it('録音では出さない', () => {
    expect(canShowOriginal('recording', 1)).toBe(false);
  });
  it('テキストでは出さない', () => {
    expect(canShowOriginal('text', 1)).toBe(false);
  });
  it('ページ番号が無ければ出さない', () => {
    expect(canShowOriginal('pdf', null)).toBe(false);
    expect(canShowOriginal('pdf', undefined)).toBe(false);
  });
  it('kind 不明なら出さない', () => {
    expect(canShowOriginal(undefined, 1)).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && npx vitest run tests/unit/sourceViewerTabs.test.ts`
Expected: FAIL — モジュールが存在しない

- [ ] **Step 3: Write minimal implementation**

```ts
// apps/web/src/lib/utils/originalTab.ts
const ORIGINAL_KINDS = new Set(['pdf', 'pptx']);

/** 原本タブを出してよいか。PDF 由来かつページ番号を持つチャンクのときだけ。 */
export function canShowOriginal(
  kind: string | undefined,
  page: number | null | undefined,
): boolean {
  if (!kind || !ORIGINAL_KINDS.has(kind)) return false;
  return typeof page === 'number' && page > 0;
}
```

`SourceViewer.svelte` に追記(既存のチャンク表示を `{#if tab === 'text'}` で包む):

```svelte
  import OriginalPageView from './OriginalPageView.svelte';
  import { canShowOriginal } from '$lib/utils/originalTab';

  let tab = $state<'text' | 'original'>('text');
  const showOriginal = $derived(canShowOriginal(sourceMeta?.kind, chunk?.page));
  const activeQuote = $derived(activeSpans[0]?.quote ?? '');

  // 別チャンクへ移ったらテキストタブへ戻す(原本タブのまま無関係なページが残らないように)
  $effect(() => {
    selectedChunkId;
    tab = 'text';
  });
```

```svelte
{#if showOriginal}
  <div class="tabs">
    <button class:on={tab === 'text'} onclick={() => (tab = 'text')}>テキスト</button>
    <button class:on={tab === 'original'} onclick={() => (tab = 'original')}>原本 p.{chunk?.page}</button>
  </div>
{/if}

{#if tab === 'original' && showOriginal && chunk}
  <OriginalPageView
    {notebookId}
    sourceId={resolvedSourceId ?? ''}
    page={chunk.page ?? 1}
    chunkId={chunk.id}
    quote={activeQuote}
  />
{:else}
  <!-- 既存のテキスト表示(ハイライト込み) -->
{/if}
```

```css
  .tabs { display: flex; border-bottom: 1px solid var(--color-border); margin-bottom: var(--space-2); }
  .tabs button {
    border: none; background: none; padding: 6px 12px;
    font-size: 11px; color: var(--color-fg-muted); cursor: pointer;
  }
  .tabs button.on { color: var(--color-fg); font-weight: 600; box-shadow: inset 0 -2px 0 var(--color-evidence); }
```

> `chunk.id` の実プロパティ名は `ChunkDetail` の定義に合わせること(`apps/web/src/lib/api/` 配下)。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/web && npx vitest run tests/unit/sourceViewerTabs.test.ts && npm run test:unit && npm run build`
Expected: すべて PASS、ビルド成功

- [ ] **Step 5: Commit**

メッセージ: `feat(web): 出典パネルにテキスト/原本のタブ切替を追加`

---

### Task 8: Phase 2 実機検証ゲート(コード変更なし)

**Files:** なし(検証のみ)

- [ ] **Step 1: 隔離環境で起動**

```bash
NOTEBOOK_OLLAMA_DATA_DIR=./.gate-data uv run --no-sync uvicorn apps.api.main:app --port 8801
cd apps/web && VITE_API_TARGET=http://localhost:8801 npx vite dev --port 5198
```
起動ログの `data_dir` が `.gate-data` を指すことを確認する。本番(8765)には触れない。

- [ ] **Step 2: Playwright は FIFO ロックを取得してから使う**

```bash
TICKET=$(python <scratchpad>/fifo_lock.py acquire --name playwright --holder phase2-gate --timeout 900)
# ... 検証 ...
python <scratchpad>/fifo_lock.py release --name playwright --ticket "$TICKET"
```

- [ ] **Step 3: 3点を撮影する**

1. 原本タブに切り替えた状態(ページ画像＋青枠)
2. 表チャンクでの矩形(アセット bbox 由来。`source: "asset"` になること)
3. 「枠は特定できません」の注記(quote が当たらないケース)

- [ ] **Step 4: 判定**

矩形が本文と明らかにズレている場合は座標変換(`_POINTS_PER_INCH` スケール)を疑う。
**自動テストの GREEN だけで PASS としない**(CLAUDE.md の視覚検証ゲート)。

---

## Phase 3 — β quote モード

### Task 9: フラグ登録と quote 抽出

**Files:**
- Modify: `core/features.py`
- Create: `core/generation/quote_spans.py`
- Test: `tests/unit/test_quote_spans.py`

**Interfaces:**
- Consumes: `core.generation.evidence_spans.iter_claim_occurrences`
- Produces:
  - `core/features.py`: `citation-quote-mode` フラグ
  - `strip_quote_tags(answer: str) -> str` — 表示用に `<q>…</q>` を取り除く
  - `attach_quote_spans(*, answer: str, citations: list[dict], chunk_texts: dict[str, str]) -> list[dict]` — `<q>` の中身をチャンク本文で完全一致検索し spans(`method="quote"`)を付ける。見つからない出現は spans を付けない(呼び出し側が第1段へフォールバックする)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_quote_spans.py
from core.generation.quote_spans import attach_quote_spans, strip_quote_tags

CHUNK = "Level 1 indicates outcome achievement. Level 2 requires work product management."
CITATIONS = [{"n": 1, "chunk_id": "c1"}]
TEXTS = {"c1": CHUNK}


def test_strip_quote_tags_removes_markup_only():
    got = strip_quote_tags("レベル2では管理される<q>Level 2 requires work product management.</q>[^1]。")
    assert "<q>" not in got and "</q>" not in got
    assert "Level 2 requires work product management." in got


def test_attaches_span_from_quote():
    answer = "レベル2では管理される<q>Level 2 requires work product management.</q>[^1]。"
    got = attach_quote_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    spans = got[0]["spans"]
    assert len(spans) == 1
    assert spans[0]["method"] == "quote"
    assert spans[0]["ordinal"] == 1
    assert CHUNK[spans[0]["start"] : spans[0]["end"]] == "Level 2 requires work product management."


def test_quote_not_in_chunk_yields_no_span():
    answer = "でたらめ<q>This sentence is not in the chunk.</q>[^1]。"
    got = attach_quote_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    assert got[0]["spans"] == []


def test_multiple_quotes_get_sequential_ordinals():
    answer = (
        "A<q>Level 1 indicates outcome achievement.</q>[^1]。"
        "B<q>Level 2 requires work product management.</q>[^1]。"
    )
    got = attach_quote_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    spans = got[0]["spans"]
    assert [s["ordinal"] for s in spans] == [1, 2]
    assert [s["answer_occurrence"] for s in spans] == [0, 1]


def test_answer_without_quotes_is_unchanged():
    answer = "根拠なし[^1]。"
    got = attach_quote_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    assert got[0]["spans"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_quote_spans.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.generation.quote_spans'`

- [ ] **Step 3: Write minimal implementation**

`core/features.py` の `REGISTRY` に追記:

```python
    FeatureFlag(
        id="citation-quote-mode",
        name="引用の根拠原文を併記(β)",
        description=(
            "回答に根拠原文を併記させ、根拠箇所を確実に特定する。言語跨ぎ(英語ソースへの"
            "日本語回答)でも根拠を示せるが、出力トークンが増え応答が遅くなる。"
        ),
        stage="beta",
        since="2026-08-08",
        spec="docs/specs/2026-08-07-citation-evidence-ui-design.md",
    ),
```

```python
# core/generation/quote_spans.py
"""β: LLM に併記させた根拠原文(<q>…</q>)からスパンを作る。

設計: docs/specs/2026-08-07-citation-evidence-ui-design.md §3.6

言語跨ぎでは字句照合(第1段)が原理的に効かないため、これが「根拠」を示せる唯一の経路。
既定 OFF。OFF のときこのモジュールは呼ばれない。
"""

from __future__ import annotations

import re
from typing import Any

from core.generation.evidence_spans import iter_claim_occurrences

_QUOTE_RE = re.compile(r"<q>(.*?)</q>", re.DOTALL)


def strip_quote_tags(answer: str) -> str:
    """表示用にタグだけ落とす(中身は残す)。"""
    return _QUOTE_RE.sub(lambda m: m.group(1), answer)


def attach_quote_spans(
    *,
    answer: str,
    citations: list[dict[str, Any]],
    chunk_texts: dict[str, str],
) -> list[dict[str, Any]]:
    """各 [^n] の直前にある <q> の中身をチャンク本文で完全一致検索して spans を付ける。"""
    quotes_by_occurrence: dict[int, str] = {}
    for occ in iter_claim_occurrences(answer):
        head = answer[: _nth_marker_end(answer, occ.answer_occurrence)]
        found = _QUOTE_RE.findall(head)
        if found:
            quotes_by_occurrence[occ.answer_occurrence] = found[-1].strip()

    spans_by_n: dict[int, list[dict[str, Any]]] = {}
    for occ in iter_claim_occurrences(answer):
        quote = quotes_by_occurrence.get(occ.answer_occurrence)
        if not quote:
            continue
        citation = next((c for c in citations if c.get("n") == occ.n), None)
        if citation is None:
            continue
        text = chunk_texts.get(citation.get("chunk_id", ""))
        if not text:
            continue
        start = text.find(quote)
        if start < 0:
            continue
        bucket = spans_by_n.setdefault(occ.n, [])
        bucket.append(
            {
                "answer_occurrence": occ.answer_occurrence,
                "ordinal": len(bucket) + 1,
                "start": start,
                "end": start + len(quote),
                "quote": quote,
                "method": "quote",
            }
        )
    return [{**c, "spans": spans_by_n.get(c.get("n"), [])} for c in citations]


def _nth_marker_end(answer: str, occurrence: int) -> int:
    """occurrence 番目(0起算)の [^n] の終端位置。"""
    positions = [m.end() for m in re.finditer(r"\[\^\d+\]", answer)]
    if occurrence < len(positions):
        return positions[occurrence]
    return len(answer)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/unit/test_quote_spans.py -v`
Expected: PASS(5件)

- [ ] **Step 5: Commit**

メッセージ: `feat(citations): β quote モードのフラグと根拠原文抽出を追加`

---

### Task 10: 生成経路への組み込み(OFF時は完全不変)

**Files:**
- Modify: `core/generation/prompt.py`(システムプロンプト)
- Modify: `core/generation/stream.py`
- Test: `tests/unit/test_quote_mode_wiring.py`

**Interfaces:**
- Consumes: Task 9 の `attach_quote_spans` / `strip_quote_tags`、`core.features.is_enabled`
- Produces: `quote_mode_instruction() -> str`(`core/generation/prompt.py`)

**Notes:** **OFF のとき、プロンプト文字列も生成経路もバイト単位で不変**であることをテストで固定する。
ON のときは、`attach_quote_spans` を先に適用し、spans が空の出現だけ第1段(字句照合)へフォールバックする。

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_quote_mode_wiring.py
from core.generation.prompt import SYSTEM_PROMPT, build_system_prompt, quote_mode_instruction


def test_off_keeps_system_prompt_byte_identical():
    assert build_system_prompt(quote_mode=False) == SYSTEM_PROMPT


def test_on_appends_instruction():
    got = build_system_prompt(quote_mode=True)
    assert got.startswith(SYSTEM_PROMPT)
    assert quote_mode_instruction() in got


def test_instruction_mentions_the_tag():
    assert "<q>" in quote_mode_instruction()
```

```python
# tests/unit/test_quote_mode_fallback.py
from core.generation.evidence_spans import attach_evidence_spans
from core.generation.quote_spans import attach_quote_spans

CHUNK = "レベル2では作業成果物が適切に管理される。監視及び調整が求められる。"
CITATIONS = [{"n": 1, "chunk_id": "c1"}]
TEXTS = {"c1": CHUNK}


def test_quote_span_wins_when_present():
    answer = "説明<q>レベル2では作業成果物が適切に管理される。</q>[^1]。"
    quoted = attach_quote_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    assert quoted[0]["spans"][0]["method"] == "quote"


def test_falls_back_to_lexical_when_quote_missing():
    answer = "レベル2では作業成果物が適切に管理される[^1]。"
    quoted = attach_quote_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    assert quoted[0]["spans"] == []
    lexical = attach_evidence_spans(answer=answer, citations=quoted, chunk_texts=TEXTS)
    assert lexical[0]["spans"][0]["method"] == "lexical"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_quote_mode_wiring.py tests/unit/test_quote_mode_fallback.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_system_prompt'`

- [ ] **Step 3: Write minimal implementation**

`core/generation/prompt.py` に追記(既存の `SYSTEM_PROMPT` はそのまま残す):

```python
def quote_mode_instruction() -> str:
    return (
        "\n\n各 [^n] の直前に、その主張の根拠となる原文を "
        "<q>原文</q> の形で1文だけそのまま引用せよ。"
        "原文は与えられた資料から一字一句変えずに写すこと。"
    )


def build_system_prompt(*, quote_mode: bool) -> str:
    """quote_mode が False のときは既存のプロンプトと完全に同一の文字列を返す。"""
    if not quote_mode:
        return SYSTEM_PROMPT
    return SYSTEM_PROMPT + quote_mode_instruction()
```

`core/generation/stream.py`(システムプロンプト選択箇所と citations 確定箇所):

```python
from core.features import is_enabled
from core.generation.prompt import build_system_prompt
from core.generation.quote_spans import attach_quote_spans, strip_quote_tags

        quote_mode = is_enabled("citation-quote-mode", optins)
        system_prompt = build_system_prompt(quote_mode=quote_mode) if not is_pixel_native else SYSTEM_PROMPT_PIXEL_NATIVE

        # ...生成後...
        answer = "".join(answer_parts)
        chunk_texts = {h.chunk_id: h.text for h in hits}
        if quote_mode:
            citations = attach_quote_spans(
                answer=answer, citations=citations, chunk_texts=chunk_texts
            )
            answer = strip_quote_tags(answer)  # 表示にはタグを出さない
        citations = await asyncio.to_thread(
            attach_evidence_spans, answer=answer, citations=citations, chunk_texts=chunk_texts
        )
```

> `optins` の取り回しは、同ファイルで `table-figure-rag` を判定している箇所に厳密に倣うこと。
> `attach_evidence_spans` は spans が既にある citation を上書きしない実装であることを確認し、
> そうでなければ「spans が空のものだけ処理する」ガードを足す(**quote の結果を消さない**)。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/unit/test_quote_mode_wiring.py tests/unit/test_quote_mode_fallback.py -v && uv run --no-sync pytest -q`
Expected: 新規 PASS、既存の回帰なし

- [ ] **Step 5: Commit**

メッセージ: `feat(citations): quote モードを生成経路へ組み込む(既定OFFでは完全不変)`

---

## Phase 4 — 通常テキストの矩形(Phase 2 の Task 2/3 に内包済み)

`rects_from_quote` と `source: "quote"` 分岐は Task 2・Task 3 で実装済み。Phase 4 として
独立した作業は残っていない。**Task 8 のゲートで「quote 由来の矩形」が実際に出ることを
確認する**ことで完了とする。

---

## Phase 5 — 選択範囲翻訳

### Task 11: 翻訳のドメインロジック

**Files:**
- Create: `core/translation/translator.py`
- Test: `tests/unit/test_translator.py`

**Interfaces:**
- Consumes: `core.ollama.gateway` の `chat_stream`
- Produces:
  - `MAX_TRANSLATE_CHARS: int`(= 4000)
  - `class TextTooLongError(ValueError)`
  - `build_messages(text: str, target_lang: str) -> list[dict[str, str]]`
  - `async translate_stream(*, text: str, target_lang: str, model: str, gateway) -> AsyncIterator[str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_translator.py
import pytest

from core.translation.translator import (
    MAX_TRANSLATE_CHARS,
    TextTooLongError,
    build_messages,
    translate_stream,
)


class FakeGateway:
    def __init__(self):
        self.calls: list[dict] = []

    async def chat_stream(self, *, model, messages, options=None, meta=None):
        self.calls.append({"model": model, "messages": messages})
        for tok in ["これは", "訳文", "です"]:
            yield tok


def test_build_messages_states_target_language():
    msgs = build_messages("Hello world", "ja")
    assert msgs[0]["role"] == "system"
    assert "日本語" in msgs[0]["content"]
    assert msgs[-1]["content"].endswith("Hello world")


def test_build_messages_forbids_commentary():
    msgs = build_messages("Hello", "ja")
    joined = " ".join(m["content"] for m in msgs)
    assert "訳文のみ" in joined


@pytest.mark.asyncio
async def test_translate_stream_yields_tokens():
    gw = FakeGateway()
    out = [tok async for tok in translate_stream(
        text="Hello", target_lang="ja", model="m", gateway=gw
    )]
    assert "".join(out) == "これは訳文です"
    assert gw.calls[0]["model"] == "m"


@pytest.mark.asyncio
async def test_empty_text_yields_nothing_and_calls_nothing():
    gw = FakeGateway()
    out = [tok async for tok in translate_stream(
        text="   ", target_lang="ja", model="m", gateway=gw
    )]
    assert out == []
    assert gw.calls == []


@pytest.mark.asyncio
async def test_too_long_text_is_rejected():
    gw = FakeGateway()
    with pytest.raises(TextTooLongError):
        [tok async for tok in translate_stream(
            text="x" * (MAX_TRANSLATE_CHARS + 1), target_lang="ja", model="m", gateway=gw
        )]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_translator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.translation.translator'`

- [ ] **Step 3: Write minimal implementation**

`core/translation/__init__.py` を空で作る。

```python
# core/translation/translator.py
"""選択範囲翻訳。既存の Ollama ゲートウェイをそのまま使う。

設計: docs/specs/2026-08-07-citation-evidence-ui-design.md §3.5
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Protocol

# 出典パネルでの選択範囲が対象。長すぎる入力はモデルの文脈を圧迫するので弾く。
MAX_TRANSLATE_CHARS = 4000

_LANG_NAMES = {"ja": "日本語", "en": "英語"}


class TextTooLongError(ValueError):
    """翻訳対象が長すぎる。"""


class ChatGateway(Protocol):
    def chat_stream(
        self, *, model: str, messages: list[dict[str, Any]], options: dict | None = ..., meta: dict | None = ...
    ) -> AsyncIterator[str]: ...


def build_messages(text: str, target_lang: str) -> list[dict[str, str]]:
    lang = _LANG_NAMES.get(target_lang, target_lang)
    system = (
        f"あなたは技術文書の翻訳者です。与えられたテキストを{lang}に翻訳してください。"
        "訳文のみを出力し、前置き・注釈・原文の再掲はしないこと。"
        "専門用語と固有名詞は原語を括弧で併記してよい。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ]


async def translate_stream(
    *, text: str, target_lang: str, model: str, gateway: ChatGateway
) -> AsyncIterator[str]:
    stripped = text.strip()
    if not stripped:
        return
    if len(stripped) > MAX_TRANSLATE_CHARS:
        raise TextTooLongError(f"text too long: {len(stripped)} > {MAX_TRANSLATE_CHARS}")
    async for tok in gateway.chat_stream(
        model=model, messages=build_messages(stripped, target_lang)
    ):
        yield tok
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/unit/test_translator.py -v`
Expected: PASS(5件)

- [ ] **Step 5: Commit**

メッセージ: `feat(translation): 選択範囲翻訳のドメインロジックを追加`

---

### Task 12: 翻訳 API(SSE)と設定

**Files:**
- Create: `apps/api/routers/translate.py`
- Modify: `apps/api/main.py`(ルータ登録)
- Modify: `apps/api/schemas/settings.py`(翻訳専用モデル)
- Test: `tests/integration/test_translate_endpoint.py`

**Interfaces:**
- Consumes: Task 11 の `translate_stream` / `TextTooLongError`
- Produces: `POST /api/translate` `{text, target_lang, model?, conversation_id?}` → SSE(`data: {"text": "..."}` の連続、最後に `data: {"done": true}`)

**Notes:** `conversation_id` が渡され、その会話が生成ストリーム実行中なら **409**(VRAM の
取り合いを避ける。第2段と同じ扱い)。`model` 未指定時は設定の翻訳専用モデル →
既定チャットモデルの順に解決する。

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_translate_endpoint.py
def test_translate_streams_sse(client):
    res = client.post("/api/translate", json={"text": "Hello", "target_lang": "ja"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    assert "data:" in res.text


def test_translate_rejects_too_long_text(client):
    res = client.post("/api/translate", json={"text": "x" * 5000, "target_lang": "ja"})
    assert res.status_code == 400


def test_translate_conflicts_while_stream_running(client, seeded_conversation_id):
    from core.generation.stream_registry import mark_running

    with mark_running(seeded_conversation_id):
        res = client.post(
            "/api/translate",
            json={"text": "Hello", "target_lang": "ja", "conversation_id": seeded_conversation_id},
        )
    assert res.status_code == 409
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/integration/test_translate_endpoint.py -v`
Expected: FAIL — 404(ルート未定義)

- [ ] **Step 3: Write minimal implementation**

`apps/api/schemas/settings.py` の Ollama 設定に追記:

```python
    # 未指定ならノートブックの現在のチャットモデルを流用する。
    # 別モデルを指定すると 11GB 環境ではモデル切替の待ちが発生する。
    translation_model: str | None = None
```

```python
# apps/api/routers/translate.py
"""選択範囲翻訳の SSE エンドポイント。"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.generation.stream_registry import is_stream_running
from core.translation.translator import TextTooLongError, translate_stream

router = APIRouter(prefix="/api/translate", tags=["translate"])


class TranslateRequest(BaseModel):
    text: str
    target_lang: str = "ja"
    model: str | None = None
    conversation_id: str | None = None


@router.post("")
async def translate(body: TranslateRequest, ...):
    if body.conversation_id and is_stream_running(body.conversation_id):
        # 生成中はVRAMを取り合うため実行しない(第2段と同じ扱い)
        raise HTTPException(status_code=409, detail="generation in progress")

    model = (
        body.model
        or ctx.settings.ollama.translation_model
        or ctx.settings.ollama.default_model
    )

    async def gen():
        try:
            async for tok in translate_stream(
                text=body.text,
                target_lang=body.target_lang,
                model=model,
                gateway=ctx.ollama_gateway,
            ):
                yield f"data: {json.dumps({'text': tok}, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001 - クライアントへ理由を返して閲覧を続けさせる
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    try:
        # 長さ超過は開始前に弾く(ストリームに乗せると FE 側で扱いにくい)
        translate_stream(text=body.text, target_lang=body.target_lang, model=model, gateway=ctx.ollama_gateway)
        if len(body.text.strip()) > 4000:
            raise TextTooLongError("too long")
    except TextTooLongError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return StreamingResponse(gen(), media_type="text/event-stream")
```

> 依存注入(`ctx`)の受け取り方は他のルータに倣うこと。`apps/api/main.py` の `create_app` に
> `app.include_router(translate.router)` を足すのを忘れない(忘れると全テストが 404 のまま)。
> 長さチェックは `core.translation.translator.MAX_TRANSLATE_CHARS` を import して使うこと
> (上のスニペットの `4000` 直書きは避ける)。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/integration/test_translate_endpoint.py -v && uv run --no-sync pytest -q`
Expected: 新規 PASS、既存の回帰なし

- [ ] **Step 5: Commit**

メッセージ: `feat(api): 選択範囲翻訳のSSEエンドポイントを追加`

---

### Task 13: FE — 選択範囲翻訳 UI

**Files:**
- Create: `apps/web/src/lib/api/translate.ts`
- Modify: `apps/web/src/lib/components/SourceViewer.svelte`
- Test: `apps/web/tests/unit/translateApi.test.ts`

**Interfaces:**
- Consumes: Task 12 のエンドポイント
- Produces: `translateStream(text: string, onToken: (t: string) => void, opts?: { conversationId?: string }): Promise<void>`

**Notes:** テキストタブで選択すると選択範囲の近傍に「訳」ボタンが浮き、押すと**選択箇所の
直下に訳文をインラインで差し込む**(原文は消さない)。再クリックで畳む。原本タブ表示中と
選択が無いときはボタンを出さない。

- [ ] **Step 1: Write the failing test**

```ts
// apps/web/tests/unit/translateApi.test.ts
import { afterEach, describe, expect, it, vi } from 'vitest';
import { translateStream } from '../../src/lib/api/translate';

afterEach(() => vi.unstubAllGlobals());

function sseResponse(lines: string[]) {
  const body = lines.map((l) => `data: ${l}\n\n`).join('');
  return {
    ok: true,
    body: {
      getReader() {
        let sent = false;
        return {
          read: async () => {
            if (sent) return { done: true, value: undefined };
            sent = true;
            return { done: false, value: new TextEncoder().encode(body) };
          },
        };
      },
    },
  };
}

describe('translateStream', () => {
  it('トークンを順に渡す', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => sseResponse([
      JSON.stringify({ text: 'これは' }),
      JSON.stringify({ text: '訳文' }),
      JSON.stringify({ done: true }),
    ])));
    const got: string[] = [];
    await translateStream('Hello', (t) => got.push(t));
    expect(got.join('')).toBe('これは訳文');
  });

  it('409(生成中)では例外を投げずに終わる', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 409 })));
    const got: string[] = [];
    await expect(translateStream('Hello', (t) => got.push(t))).resolves.toBeUndefined();
    expect(got).toEqual([]);
  });

  it('error イベントはトークンとして渡さない', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => sseResponse([
      JSON.stringify({ error: 'boom' }),
      JSON.stringify({ done: true }),
    ])));
    const got: string[] = [];
    await translateStream('Hello', (t) => got.push(t));
    expect(got).toEqual([]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && npx vitest run tests/unit/translateApi.test.ts`
Expected: FAIL — モジュールが存在しない

- [ ] **Step 3: Write minimal implementation**

```ts
// apps/web/src/lib/api/translate.ts
/**
 * 選択範囲翻訳の SSE クライアント。
 * 失敗しても閲覧を妨げないよう、例外を投げずに黙って終わる(呼び出し側はトークン0で判断)。
 */
export async function translateStream(
  text: string,
  onToken: (t: string) => void,
  opts: { conversationId?: string; targetLang?: string } = {},
): Promise<void> {
  let res: Response;
  try {
    res = await fetch('/api/translate', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        text,
        target_lang: opts.targetLang ?? 'ja',
        conversation_id: opts.conversationId ?? null,
      }),
    });
  } catch {
    return;
  }
  if (!res.ok || !res.body) return;

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split('\n\n');
    buf = parts.pop() ?? '';
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith('data:')) continue;
      try {
        const payload = JSON.parse(line.slice(5).trim());
        if (typeof payload.text === 'string') onToken(payload.text);
      } catch {
        // 壊れた行は無視する
      }
    }
  }
}
```

`SourceViewer.svelte` に追記(テキストタブのみ):

```svelte
  import { translateStream } from '$lib/api/translate';

  let selection = $state<{ text: string; top: number; left: number } | null>(null);
  let translation = $state<string | null>(null);
  let translating = $state(false);

  function onTextSelect(e: MouseEvent) {
    if (tab !== 'text') return;
    const sel = window.getSelection();
    const text = sel?.toString().trim() ?? '';
    if (!text) {
      selection = null;
      return;
    }
    const rect = sel!.getRangeAt(0).getBoundingClientRect();
    selection = { text, top: rect.bottom, left: rect.left };
  }

  async function runTranslate() {
    if (!selection) return;
    if (translation !== null) {
      translation = null; // 再クリックで畳む
      return;
    }
    translating = true;
    translation = '';
    await translateStream(selection.text, (t) => (translation = (translation ?? '') + t));
    translating = false;
  }
```

```svelte
<div role="presentation" onmouseup={onTextSelect}>
  <!-- 既存のテキスト表示 -->
</div>

{#if selection && tab === 'text'}
  <button class="translate-fab" style:top={`${selection.top}px`} style:left={`${selection.left}px`}
          onclick={runTranslate}>訳</button>
{/if}
{#if translation !== null}
  <div class="translation">
    {#if translating && !translation}翻訳中…{:else}{translation}{/if}
  </div>
{/if}
```

```css
  .translate-fab {
    position: fixed;
    z-index: 20;
    border: 1px solid var(--color-evidence);
    background: var(--color-bg);
    color: var(--color-evidence);
    border-radius: var(--radius-sm);
    padding: 1px 8px;
    font-size: 11px;
  }
  .translation {
    margin-top: var(--space-2);
    padding: var(--space-2);
    border-left: 2px solid var(--color-evidence);
    background: var(--color-bg-elevated);
    font-size: 12px;
    line-height: 1.7;
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/web && npx vitest run tests/unit/translateApi.test.ts && npm run test:unit && npm run build`
Expected: すべて PASS、ビルド成功

- [ ] **Step 5: Commit**

メッセージ: `feat(web): 出典パネルに選択範囲翻訳を追加`

---

### Task 14: Phase 5 実機検証ゲート(コード変更なし)

**Files:** なし(検証のみ)

- [ ] **Step 1: 隔離環境で起動**(Task 8 と同じ手順、`NOTEBOOK_OLLAMA_DATA_DIR=./.gate-data` / `:8801` / vite `:5198`)

- [ ] **Step 2: Playwright FIFO ロックを取得する**

- [ ] **Step 3: 英語チャンクを含む出典を開き、英文を選択して「訳」を押す**

`.gate-shots/en-capability.pdf` を取り込んだノートブックを使う(Phase 1.5 で作成済み)。

- [ ] **Step 4: 3点を撮影する**

1. 選択直後に「訳」ボタンが浮いている状態
2. 訳文がインラインで差し込まれた状態(原文が消えていないこと)
3. 再クリックで畳んだ状態

- [ ] **Step 5: モデル切替の待ちを計測する**

設定で翻訳専用モデルをチャットモデルと別のものに変え、初回翻訳の待ち時間を測る。
体感が許容外なら、設定画面の注記(「モデル切替の待ちが発生します」)が実態に合っているか見直す。

- [ ] **Step 6: FIFO ロックを解放し、dev サーバーを停止する**

---

## 完了条件

- Task 1〜14 がすべてコミットされている
- `uv run --no-sync pytest -q` と `cd apps/web && npm run test:unit && npm run build` が緑
- Task 8 / Task 14 の実機スクリーンショットが取得されている(自動テストの GREEN だけで PASS としない)
- 設計書 §3.4 / §3.5 / §3.6 の要件に、対応するタスクが存在する

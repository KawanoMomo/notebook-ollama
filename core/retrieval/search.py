from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from core.logging import get_logger
from core.storage.chunks_repo import get_chunks_by_ids
from core.storage.sources_repo import get_source
from core.storage.vector_store import VectorStore

log = get_logger("retrieval")


class _GatewayLike(Protocol):
    async def embed(self, *, model: str, text: str) -> list[float]: ...


@dataclass
class RetrievedChunk:
    chunk_id: str
    source_id: str
    source_title: str
    source_kind: str
    page: int | None
    heading_path: str | None
    ord: int
    text: str
    token_count: int
    score: float
    start_ms: int | None = None
    end_ms: int | None = None
    speaker: str | None = None
    channel: str | None = None
    via_visual: bool = False
    # 視覚検索(タイル単位)でヒットしたタイルの 0 始まり通し番号。
    # ページ単位・テキスト経路では None。引用表記とタイル画像の投入に使う。
    tile_index: int | None = None


@dataclass
class VisualSearchDeps:
    """視覚検索の依存束 (Stage 3 → Stage 4 で単位と戦略を追加)。

    enabled は「設定ON かつ ベータON かつ extra導入済み」の合成getterを
    配線側(apps/api/dependencies.py)が渡す。
    """

    stores: dict[str, Any]  # {"page": VisualUnitStore, "tile": VisualUnitStore}
    encoder: Any  # VisualEncoder プロトコル
    enabled: Callable[[], bool]
    meta_lookup: Callable[[str, str], Any]  # (notebook_id, unit) -> VisualIndexMeta | None
    model_name_getter: Callable[[], str]
    # --- Stage 4 ---
    unit_getter: Callable[[], str]  # "page" | "tile"
    strategy_getter: Callable[[], str]  # "hybrid_rrf" | "visual_only" | "pixel_native"
    tile_grid_getter: Callable[[], tuple[int, int]]  # (rows, cols)。over-fetch 倍率
    max_images_getter: Callable[[], int]  # pixel_native の件数上限


class RetrievalService:
    def __init__(
        self,
        *,
        conn: sqlite3.Connection,
        vector_store: VectorStore,
        ollama: _GatewayLike,
        embedding_model: str,
        embedding_model_getter: Callable[[], str] | None = None,
        figure_desc_enabled: Callable[[], bool] | None = None,
        visual: VisualSearchDeps | None = None,
    ) -> None:
        self._conn = conn
        self._vs = vector_store
        self._ollama = ollama
        self._embedding_model = embedding_model
        self._embedding_model_getter = embedding_model_getter
        self._figure_desc_enabled = figure_desc_enabled
        self._visual = visual

    def _resolve_embedding_model(self) -> str:
        if self._embedding_model_getter is not None:
            return self._embedding_model_getter()
        return self._embedding_model

    def _source_title(self, source_id: str, cache: dict[str, str]) -> str:
        if source_id not in cache:
            src = get_source(self._conn, source_id)
            cache[source_id] = src.title or (src.origin or "untitled")
        return cache[source_id]

    async def search(
        self,
        *,
        notebook_id: str,
        query: str,
        limit: int,
        source_ids: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        if not query.strip():
            return []

        strategy = self._strategy()
        # pixel_native だけは件数上限が limit ではなく max_images(spec §7.3:
        # タイルはページ全体より軽いので limit より多く積める運用が前提)。
        # ここで先に cap を決め、_visual_hits() の over-fetch/切り出しの基準を
        # これに揃える — でないと max_images > limit の設定が limit に丸め
        # られて無視される(レビュー Important 1)。
        cap = self._max_images() if strategy == "pixel_native" else limit
        # cache source titles to avoid N+1 (この search() 呼び出し内のみ有効)。
        # テキスト検索を後からフォールバック実行する場合も同じキャッシュを使う。
        title_cache: dict[str, str] = {}
        if strategy == "hybrid_rrf":
            text_results = await self._text_hits(
                notebook_id=notebook_id, query=query, limit=limit,
                source_ids=source_ids, title_cache=title_cache,
            )
        else:
            # visual_only / pixel_native はテキスト埋め込み検索を実行しない。
            # 「テキスト検索と視覚検索のどちらが当てているか」を混ぜずに
            # 比較するのがこの2戦略の目的(spec §7.1)。
            text_results = []

        visual_available, visual_results = await self._visual_hits(
            notebook_id=notebook_id, query=query, text_results=text_results,
            visual_limit=cap, source_ids=source_ids, title_cache=title_cache,
        )

        if strategy != "hybrid_rrf" and not visual_available:
            if strategy == "pixel_native":
                # pixel_native は視覚検索が使えなくてもテキストへ縮退しない。
                # 生成側(GenerationService)が明示エラーとして扱う(spec §7.1)。
                return []
            # visual_only は「視覚検索そのものが使えない」場合だけテキスト検索
            # に縮退する(視覚索引が未構築/モデル不一致/エンコーダ障害時の
            # セーフティネット)。視覚検索が実行できて真に0件だった場合は
            # visual_available=True なのでここには来ない — テキストを混ぜると
            # spec §7.1 の「テキストと視覚のどちらが当てているか混ぜずに比較
            # する」目的が壊れる(レビュー Important 2)。
            return await self._text_hits(
                notebook_id=notebook_id, query=query, limit=limit,
                source_ids=source_ids, title_cache=title_cache,
            )

        if not visual_results:
            return text_results
        merged = text_results + visual_results
        # RRFスコア降順に整列して cap で切る。text_results/visual_results の
        # score には既にRRFスコアが入っている(_visual_hits 参照)。
        merged.sort(key=lambda h: h.score, reverse=True)
        return merged[:cap]

    def _strategy(self) -> str:
        v = self._visual
        if v is None or v.strategy_getter is None:
            return "hybrid_rrf"
        return v.strategy_getter()

    def _max_images(self) -> int:
        v = self._visual
        return v.max_images_getter() if v is not None else 4

    async def _text_hits(
        self,
        *,
        notebook_id: str,
        query: str,
        limit: int,
        source_ids: list[str] | None,
        title_cache: dict[str, str],
    ) -> list[RetrievedChunk]:
        """テキスト埋め込み検索 → チャンク取得 → RetrievedChunk 構築。

        Stage 3 までの search() 本体をそのまま切り出したもの(ロジック不変)。
        """
        qvec = await self._ollama.embed(model=self._resolve_embedding_model(), text=query)
        hits = self._vs.search(
            query=qvec, notebook_id=notebook_id, limit=limit, source_ids=source_ids
        )
        # 早期return はしない: テキストヒットが0件でも視覚検索側だけで結果が
        # 得られる場合がある(視覚インデックスのみのページ等、spec §6)。
        records = get_chunks_by_ids(self._conn, [h.id for h in hits])
        if self._figure_desc_enabled is not None and not self._figure_desc_enabled():
            # ベータOFF時は図説明チャンクを検索から除外する(spec: 2026-07-20-
            # vlm-figure-ocr-design.md §提供形態。データ・ベクトルは保持し、
            # ONに戻せば再び検索に乗る)。
            records = [r for r in records if r.kind != "figure_desc"]
        score_by_id = {h.id: h.score for h in hits}

        kind_by_chunk = {h.id: h.source_kind for h in hits}
        hit_by_id = {h.id: h for h in hits}

        return [
            RetrievedChunk(
                chunk_id=rec.id,
                source_id=rec.source_id,
                source_title=self._source_title(rec.source_id, title_cache),
                source_kind=kind_by_chunk.get(rec.id, ""),
                page=rec.page,
                heading_path=rec.heading_path,
                ord=rec.ord,
                text=rec.text,
                token_count=rec.token_count,
                score=score_by_id.get(rec.id, 0.0),
                start_ms=hit_by_id[rec.id].start_ms,
                end_ms=hit_by_id[rec.id].end_ms,
                # speaker は SQLite を正とする(話者リネームは SQLite を即時更新、
                # Qdrant payload 更新は best-effort なので、payload 由来だと
                # リネーム後に旧名が引用へ残りうる)。text と同じく rec から取る。
                speaker=rec.speaker,
                channel=hit_by_id[rec.id].channel,
            )
            for rec in records
        ]

    # 本文が空だと <source id="n"></source> になり、SYSTEM_PROMPT ルール3
    # (引用できる情報がなければ「該当情報がありません」)に従われてしまう。
    # かつ count_tokens("") == 0 なので予算上ゼロコストで無限に入る。
    # 必ず「画像として添付されている」ことを本文に書く。
    _PIXEL_NATIVE_TEXT = (
        "(このソースはページ画像として添付されています。"
        "添付画像を読み取って回答の根拠にしてください)"
    )
    _PIXEL_NATIVE_TILE_TEXT = (
        "(このソースはページ画像の一部(タイル)として添付されています。"
        "添付画像を読み取って回答の根拠にしてください)"
    )

    def _pixel_native_chunk(self, hit, rrf_score: float, title: str, unit: str) -> RetrievedChunk:
        """本文を持たないページ/タイルの合成チャンク。

        chunk_id は SQLite に実体行が無い擬似ID。FE は
        apps/web/src/routes/notebooks/[id]/+page.svelte で 'vp:' / 'vt:' の
        prefix を見て全文ビューへフォールバックする。
        """
        if unit == "tile" and hit.tile_index is not None:
            chunk_id = f"vt:{hit.source_id}:{hit.page}:{hit.tile_index}"
            text = self._PIXEL_NATIVE_TILE_TEXT
        else:
            chunk_id = f"vp:{hit.source_id}:{hit.page}"
            text = self._PIXEL_NATIVE_TEXT
        return RetrievedChunk(
            chunk_id=chunk_id, source_id=hit.source_id, source_title=title,
            source_kind="pdf", page=hit.page, heading_path=None, ord=0,
            text=text, token_count=30, score=rrf_score,
            via_visual=True, tile_index=hit.tile_index,
        )

    async def _visual_hits(
        self,
        *,
        notebook_id: str,
        query: str,
        text_results: list[RetrievedChunk],
        visual_limit: int,
        source_ids: list[str] | None = None,
        title_cache: dict[str, str],
    ) -> tuple[bool, list[RetrievedChunk]]:
        """視覚検索(単位はconfig依存)→RRF→展開。

        戻り値は (available, hits)。`available=False` は「視覚検索そのものが
        使えない」場合だけに限る: v is None / enabled()==False / 該当単位の
        store が無い / meta 不在・モデル不一致 / 例外(エンコーダ障害等)。
        これらのときだけ呼び出し側 search() はテキストへの縮退を検討してよい。

        視覚検索が実行できて結果が真に0件だった場合(unit_hits が空、または
        RRF融合後に surviving_pages が空)は `available=True, hits=[]` を返す
        — 「視覚が使えない」と「視覚は健全だが今回のクエリで0件」を区別する
        (spec §7.1: visual_only はテキストと視覚のどちらが当てているかを
        混ぜずに比較する目的があり、健全な0件にテキストを混ぜてはならない)。

        戻り値の score はRRFスコア。text_results の score もRRFスコアに
        書き換える(融合順位はRRF基準、spec §6)。visual_limit は over-fetch
        と切り出し件数の基準(hybrid_rrf/visual_only は limit、pixel_native は
        max_images。呼び出し側 search() が strategy から決めて渡す)。"""
        from core.retrieval.fusion import collapse_to_best_per_page, rrf_fuse
        from core.storage.chunks_repo import list_text_chunks_for_page

        v = self._visual
        if v is None or not v.enabled():
            return False, []
        unit = v.unit_getter()
        strategy = v.strategy_getter()
        try:
            store = v.stores.get(unit)
            if store is None:
                return False, []
            meta = v.meta_lookup(notebook_id, unit)
            if meta is None or meta.embedding_model != v.model_name_getter():
                return False, []
            qvec = await v.encoder.embed_text(text=query)
            # タイル単位は1ページから複数タイルが上位に入りうる。over-fetch して
            # からページ単位に畳まないと、visual_limit の枠を1ページが食い潰す。
            rows, cols = v.tile_grid_getter()
            over = max(1, rows * cols) if unit == "tile" else 1
            raw_hits = store.search(
                query=qvec, notebook_id=notebook_id, limit=visual_limit * over,
                source_ids=source_ids,
            )
            unit_hits = collapse_to_best_per_page(raw_hits)[:visual_limit]
            if not unit_hits:
                # 視覚検索は実行できたが真に0件(spec §7.1: available扱い)
                return True, []

            fused = rrf_fuse(text_hits=text_results, visual_hits=unit_hits)
            # テキスト側のscoreをRRFスコアへ書き換え(融合ソートの物差しを揃える)
            for chunk, rrf_score in fused.ordered_text:
                chunk.score = rrf_score
            seen_ids = {c.chunk_id for c in text_results}

            out: list[RetrievedChunk] = []
            for hit, rrf_score in fused.surviving_pages:
                title = self._source_title(hit.source_id, title_cache)
                if strategy == "pixel_native":
                    # pixel_native は本文を展開しない(spec §7.1)。
                    out.append(self._pixel_native_chunk(hit, rrf_score, title, unit))
                    continue
                chunks = list_text_chunks_for_page(self._conn, hit.source_id, hit.page, 2)
                if chunks:
                    for rec in chunks:
                        if rec.id in seen_ids:
                            continue
                        seen_ids.add(rec.id)
                        out.append(
                            RetrievedChunk(
                                chunk_id=rec.id, source_id=hit.source_id,
                                source_title=title, source_kind="pdf",
                                page=rec.page, heading_path=rec.heading_path,
                                ord=rec.ord, text=rec.text,
                                token_count=rec.token_count, score=rrf_score,
                                via_visual=True, tile_index=hit.tile_index,
                            )
                        )
                else:
                    # スキャン未OCRページ/タイル: 本文なし(spec §6)
                    out.append(self._pixel_native_chunk(hit, rrf_score, title, unit))
            # ここに到達した時点で視覚検索は正常に実行できている。out が空
            # (=全ページがテキスト側に吸収された)でも available=True。
            return True, out
        except Exception:
            log.warning("visual_search_failed", notebook_id=notebook_id, exc_info=True)
            return False, []

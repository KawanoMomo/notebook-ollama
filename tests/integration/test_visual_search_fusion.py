import pytest

from core.retrieval.search import RetrievalService, VisualSearchDeps
from core.storage.chunks_repo import ChunkRecord, insert_chunks
from core.storage.database import connect, migrate
from core.storage.notebooks_repo import create_notebook
from core.storage.sources_repo import create_source
from core.storage.vector_store import ChunkVector, VectorStore
from core.storage.visual_index_repo import VisualIndexMeta, upsert_meta
from core.storage.visual_store import PageVector, UnitVector, VisualPageStore, VisualUnitStore

pytestmark = pytest.mark.qdrant


class FakeGateway:
    async def embed(self, *, model: str, text: str) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0]


class FakeVisualEncoder:
    def __init__(self, vec=None, boom=False):
        self._vec = vec or [1.0, 0.0, 0.0, 0.0]
        self._boom = boom

    async def embed_text(self, *, text: str) -> list[float]:
        if self._boom:
            raise RuntimeError("encoder down")
        return self._vec

    async def embed_image(self, *, png: bytes) -> list[float]:
        return self._vec

    def unload(self) -> None:
        pass


def _setup(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    src = create_source(conn, notebook_id=nb.id, kind="pdf", title="Doc", content_hash="h")
    vs = VectorStore(path=tmp_path / "q", dim=4)
    vs.ensure_collection()
    ps = VisualPageStore(client=vs.client)
    ps.ensure_collection(dim=4)
    return conn, nb, src, vs, ps


def _add_text_chunk(conn, vs, nb, src, *, cid, page, ord_, vec, text="本文"):
    insert_chunks(conn, [ChunkRecord(
        id=cid, source_id=src.id, notebook_id=nb.id, ord=ord_, page=page,
        heading_path=None, text=text, token_count=3,
    )])
    vs.upsert([ChunkVector(
        id=cid, vector=vec, notebook_id=nb.id, source_id=src.id,
        source_kind="pdf", page=page, heading_path=None, ord=ord_,
    )])


def _add_visual_page(ps, nb, src, *, page, vec):
    ps.upsert_pages([PageVector(
        source_id=src.id, page=page, vector=vec, notebook_id=nb.id,
        embedding_model="vm", built_at="t",
    )])


def _svc(
    conn, vs, ps, *, encoder=None, enabled=True, model="vm",
    unit="page", strategy="hybrid_rrf", tile_grid=(3, 1), max_images=4, tile_store=None,
):
    from core.storage.visual_index_repo import get_meta
    return RetrievalService(
        conn=conn, vector_store=vs, ollama=FakeGateway(), embedding_model="bge-m3",
        visual=VisualSearchDeps(
            stores={"page": ps, "tile": tile_store or ps},
            encoder=encoder or FakeVisualEncoder(),
            enabled=lambda: enabled,
            meta_lookup=lambda nb_id, u: get_meta(conn, nb_id, u),
            model_name_getter=lambda: model,
            unit_getter=lambda: unit,
            strategy_getter=lambda: strategy,
            tile_grid_getter=lambda: tile_grid,
            max_images_getter=lambda: max_images,
        ),
    )


def _add_text_chunks_sqlite_only(conn, nb, src, *, page, ids):
    """SQLite にのみチャンクを入れる(Qdrant には入れない)。

    Qdrant local mode はスコア閾値なしの top-K 検索なので、もし vs.upsert
    していたら他に候補が無いfixtureでは低スコアでも hits に混入し、
    fusion.py の「同一ページ吸収」規則により視覚ページが吸収されてしまう。
    テキスト検索に当てたくないチャンクはこの手口で SQLite だけに入れる。
    """
    for i, cid in enumerate(ids):
        insert_chunks(conn, [ChunkRecord(
            id=cid, source_id=src.id, notebook_id=nb.id, ord=i, page=page,
            heading_path=None, text=f"p{page}本文{i}", token_count=3,
        )])


def _tile_store(vs):
    ts = VisualUnitStore(client=vs.client, unit="tile")
    ts.ensure_collection(dim=4)
    return ts


def _add_visual_tile(tile_store, nb, src, *, page, tile, vec=None):
    tile_store.upsert_units([UnitVector(
        source_id=src.id, page=page, vector=vec or [1.0, 0.0, 0.0, 0.0],
        notebook_id=nb.id, embedding_model="vm", built_at="t", tile_index=tile,
    )])


async def test_visual_page_hit_expands_to_first_two_text_chunks(tmp_path):
    conn, nb, src, vs, ps = _setup(tmp_path)
    # テキスト検索では当たらない: ベクトルストアには索引しない(SQLiteのみ)。
    # Qdrant local mode はスコア閾値なしの top-K 検索なので、もし vs.upsert
    # していたら他に候補が無い this fixture では低スコアでも hits に混入し、
    # fusion.py の「同一ページ吸収」規則(spec §6, test_same_page_visual_hit_
    # absorbed_by_text で担保)により視覚ページが吸収されてしまう。
    for i, cid in enumerate(["p3c1", "p3c2", "p3c3"]):
        insert_chunks(conn, [ChunkRecord(
            id=cid, source_id=src.id, notebook_id=nb.id, ord=i, page=3,
            heading_path=None, text=f"p3本文{i}", token_count=3,
        )])
    _add_visual_page(ps, nb, src, page=3, vec=[1.0, 0.0, 0.0, 0.0])
    upsert_meta(conn, VisualIndexMeta(notebook_id=nb.id, embedding_model="vm", built_at="t"))

    hits = await _svc(conn, vs, ps).search(notebook_id=nb.id, query="q", limit=10)
    via = [h for h in hits if h.via_visual]
    assert [h.chunk_id for h in via] == ["p3c1", "p3c2"]  # 先頭2チャンクのみ(ord順)
    assert all(h.page == 3 for h in via)


async def test_chunkless_page_yields_synthetic_chunk(tmp_path):
    conn, nb, src, vs, ps = _setup(tmp_path)
    _add_visual_page(ps, nb, src, page=7, vec=[1.0, 0.0, 0.0, 0.0])
    upsert_meta(conn, VisualIndexMeta(notebook_id=nb.id, embedding_model="vm", built_at="t"))

    hits = await _svc(conn, vs, ps).search(notebook_id=nb.id, query="q", limit=10)
    assert len(hits) == 1
    h = hits[0]
    assert h.chunk_id == f"vp:{src.id}:7" and h.via_visual and h.page == 7


async def test_duplicate_chunk_not_added_twice(tmp_path):
    """テキスト検索で既に含まれるチャンクはページ展開で重複させない。"""
    conn, nb, src, vs, ps = _setup(tmp_path)
    _add_text_chunk(conn, vs, nb, src, cid="c1", page=3, ord_=0,
                    vec=[1.0, 0.0, 0.0, 0.0])  # テキストでもヒットする
    _add_visual_page(ps, nb, src, page=3, vec=[1.0, 0.0, 0.0, 0.0])
    upsert_meta(conn, VisualIndexMeta(notebook_id=nb.id, embedding_model="vm", built_at="t"))

    hits = await _svc(conn, vs, ps).search(notebook_id=nb.id, query="q", limit=10)
    # p3 はテキストヒット済み → 視覚側は吸収され、c1 は1回だけ
    assert [h.chunk_id for h in hits].count("c1") == 1
    assert not hits[0].via_visual


async def test_visual_skipped_when_meta_model_mismatch(tmp_path):
    conn, nb, src, vs, ps = _setup(tmp_path)
    _add_visual_page(ps, nb, src, page=7, vec=[1.0, 0.0, 0.0, 0.0])
    upsert_meta(conn, VisualIndexMeta(notebook_id=nb.id, embedding_model="OLD", built_at="t"))
    hits = await _svc(conn, vs, ps, model="NEW").search(notebook_id=nb.id, query="q", limit=10)
    assert hits == []  # モデル不一致 → 視覚スキップ(テキストも0件)


async def test_visual_skipped_when_disabled_or_no_meta(tmp_path):
    conn, nb, src, vs, ps = _setup(tmp_path)
    _add_visual_page(ps, nb, src, page=7, vec=[1.0, 0.0, 0.0, 0.0])
    # メタ無し
    assert await _svc(conn, vs, ps).search(notebook_id=nb.id, query="q", limit=10) == []
    # メタありでも enabled=False
    upsert_meta(conn, VisualIndexMeta(notebook_id=nb.id, embedding_model="vm", built_at="t"))
    assert await _svc(conn, vs, ps, enabled=False).search(
        notebook_id=nb.id, query="q", limit=10) == []


async def test_encoder_failure_degrades_to_text_only(tmp_path):
    """クエリ時のモデルロード失敗 → テキストのみで応答(spec §9)。"""
    conn, nb, src, vs, ps = _setup(tmp_path)
    _add_text_chunk(conn, vs, nb, src, cid="c1", page=1, ord_=0, vec=[1.0, 0.0, 0.0, 0.0])
    _add_visual_page(ps, nb, src, page=7, vec=[1.0, 0.0, 0.0, 0.0])
    upsert_meta(conn, VisualIndexMeta(notebook_id=nb.id, embedding_model="vm", built_at="t"))
    hits = await _svc(conn, vs, ps, encoder=FakeVisualEncoder(boom=True)).search(
        notebook_id=nb.id, query="q", limit=10)
    assert [h.chunk_id for h in hits] == ["c1"]  # エラーにせずテキストのみ


# --- Stage 4: 検索戦略3分岐 (hybrid_rrf / visual_only / pixel_native) ---


async def test_hybrid_rrf_is_unchanged_from_stage3(tmp_path):
    """既定戦略は Stage 3 と同じ結果(テキスト+視覚のRRF融合)。"""
    conn, nb, src, vs, ps = _setup(tmp_path)
    _add_text_chunk(conn, vs, nb, src, cid="c1", page=1, ord_=0, vec=[1.0, 0.0, 0.0, 0.0])
    _add_visual_page(ps, nb, src, page=3, vec=[1.0, 0.0, 0.0, 0.0])
    upsert_meta(conn, VisualIndexMeta(notebook_id=nb.id, embedding_model="vm", built_at="t"))
    svc = _svc(conn, vs, ps, strategy="hybrid_rrf")
    hits = await svc.search(notebook_id=nb.id, query="q", limit=5)
    assert "c1" in [h.chunk_id for h in hits]
    assert any(h.via_visual for h in hits)


async def test_visual_only_does_not_run_text_search(tmp_path):
    """テキストのみに当たるチャンクは結果に出ない。"""
    conn, nb, src, vs, ps = _setup(tmp_path)
    _add_text_chunk(conn, vs, nb, src, cid="c1", page=1, ord_=0,
                     vec=[1.0, 0.0, 0.0, 0.0])   # SQLite + Qdrant 両方
    _add_visual_page(ps, nb, src, page=3, vec=[1.0, 0.0, 0.0, 0.0])
    _add_text_chunks_sqlite_only(conn, nb, src, page=3, ids=["p3c1", "p3c2"])
    upsert_meta(conn, VisualIndexMeta(notebook_id=nb.id, embedding_model="vm", built_at="t"))
    svc = _svc(conn, vs, ps, strategy="visual_only")
    hits = await svc.search(notebook_id=nb.id, query="q", limit=5)
    ids = [h.chunk_id for h in hits]
    assert ids == ["p3c1", "p3c2"]        # 視覚ヒットのページ展開のみ
    assert "c1" not in ids                # テキスト検索は走っていない
    assert all(h.via_visual for h in hits)


async def test_pixel_native_produces_placeholder_chunks_without_expansion(tmp_path):
    conn, nb, src, vs, ps = _setup(tmp_path)
    _add_text_chunks_sqlite_only(conn, nb, src, page=3, ids=["p3c1", "p3c2"])
    _add_visual_page(ps, nb, src, page=3, vec=[1.0, 0.0, 0.0, 0.0])
    upsert_meta(conn, VisualIndexMeta(notebook_id=nb.id, embedding_model="vm", built_at="t"))
    svc = _svc(conn, vs, ps, strategy="pixel_native")
    hits = await svc.search(notebook_id=nb.id, query="q", limit=5)
    assert len(hits) == 1
    h = hits[0]
    assert h.chunk_id == f"vp:{src.id}:3"
    assert h.via_visual is True
    assert h.page == 3
    # 本文は空ではなくプレースホルダ(空だと SYSTEM_PROMPT ルール3で
    # 「該当情報がありません」と答えられてしまう)
    assert h.text != ""
    assert "画像" in h.text
    # ページ展開はしない
    assert "p3c1" not in [x.chunk_id for x in hits]


async def test_pixel_native_caps_hits_at_max_images(tmp_path):
    conn, nb, src, vs, ps = _setup(tmp_path)
    for page in range(1, 8):
        _add_visual_page(ps, nb, src, page=page, vec=[1.0, 0.0, 0.0, 0.0])
    upsert_meta(conn, VisualIndexMeta(notebook_id=nb.id, embedding_model="vm", built_at="t"))
    svc = _svc(conn, vs, ps, strategy="pixel_native", max_images=3)
    hits = await svc.search(notebook_id=nb.id, query="q", limit=10)
    assert len(hits) == 3


async def test_pixel_native_can_exceed_limit_with_larger_max_images(tmp_path):
    """max_images > limit の設定で、limit に丸められないこと。

    spec §7.3「タイルはページ全体より小さくトークン消費が少ないため
    pixel_native ではより多く積める」が成立する条件。
    """
    conn, nb, src, vs, ps = _setup(tmp_path)
    for page in range(1, 8):
        _add_visual_page(ps, nb, src, page=page, vec=[1.0, 0.0, 0.0, 0.0])
    upsert_meta(conn, VisualIndexMeta(notebook_id=nb.id, embedding_model="vm", built_at="t"))
    svc = _svc(conn, vs, ps, strategy="pixel_native", max_images=6)
    hits = await svc.search(notebook_id=nb.id, query="q", limit=3)
    assert len(hits) == 6


async def test_tile_unit_collapses_to_one_hit_per_page(tmp_path):
    conn, nb, src, vs, ps_page = _setup(tmp_path)
    tile_store = _tile_store(vs)          # VisualUnitStore(client=vs.client, unit="tile")
    _add_visual_tile(tile_store, nb, src, page=3, tile=0, vec=[1.0, 0.0, 0.0, 0.0])
    _add_visual_tile(tile_store, nb, src, page=3, tile=1, vec=[0.9, 0.1, 0.0, 0.0])
    _add_visual_tile(tile_store, nb, src, page=5, tile=2, vec=[0.8, 0.2, 0.0, 0.0])
    _add_text_chunks_sqlite_only(conn, nb, src, page=3, ids=["p3c1"])
    _add_text_chunks_sqlite_only(conn, nb, src, page=5, ids=["p5c1"])
    upsert_meta(conn, VisualIndexMeta(
        notebook_id=nb.id, embedding_model="vm", built_at="t", unit="tile"))

    svc = _svc(conn, vs, ps_page, unit="tile", strategy="visual_only",
               tile_store=tile_store, tile_grid=(3, 1))
    hits = await svc.search(notebook_id=nb.id, query="q", limit=5)
    pages = [h.page for h in hits]
    assert pages == [3, 5]                      # p.3 のタイルは1件に畳まれる
    assert hits[0].tile_index == 0              # 最上位タイルが残る
    assert hits[1].tile_index == 2


async def test_tile_unit_pixel_native_uses_vt_chunk_id(tmp_path):
    conn, nb, src, vs, ps_page = _setup(tmp_path)
    tile_store = _tile_store(vs)
    _add_visual_tile(tile_store, nb, src, page=4, tile=1)
    upsert_meta(conn, VisualIndexMeta(
        notebook_id=nb.id, embedding_model="vm", built_at="t", unit="tile"))
    svc = _svc(conn, vs, ps_page, unit="tile", strategy="pixel_native",
               tile_store=tile_store)
    hits = await svc.search(notebook_id=nb.id, query="q", limit=5)
    assert hits[0].chunk_id == f"vt:{src.id}:4:1"
    assert hits[0].tile_index == 1


async def test_strategy_falls_back_to_text_when_visual_unavailable(tmp_path):
    """visual_only でも視覚が使えなければテキスト検索に縮退する(pixel_native を除く)。"""
    conn, nb, src, vs, ps = _setup(tmp_path)
    _add_text_chunk(conn, vs, nb, src, cid="c1", page=1, ord_=0, vec=[1.0, 0.0, 0.0, 0.0])
    svc = _svc(conn, vs, ps, strategy="visual_only", enabled=False)
    hits = await svc.search(notebook_id=nb.id, query="q", limit=5)
    assert [h.chunk_id for h in hits] == ["c1"]


async def test_pixel_native_returns_empty_when_visual_unavailable(tmp_path):
    """pixel_native はテキストに縮退しない(生成側が明示エラーにする)。"""
    conn, nb, src, vs, ps = _setup(tmp_path)
    _add_text_chunk(conn, vs, nb, src, cid="c1", page=1, ord_=0, vec=[1.0, 0.0, 0.0, 0.0])
    svc = _svc(conn, vs, ps, strategy="pixel_native", enabled=False)
    hits = await svc.search(notebook_id=nb.id, query="q", limit=5)
    assert hits == []


async def test_visual_only_does_not_fall_back_when_visual_is_healthy_but_empty(tmp_path):
    """視覚索引が健全で今回のクエリに0件だった場合、テキストを混ぜない。

    spec §7.1「テキスト検索と視覚検索のどちらが当てているかを混ぜずに比較する」。
    """
    conn, nb, src, vs, ps = _setup(tmp_path)
    _add_text_chunk(conn, vs, nb, src, cid="c1", page=1, ord_=0, vec=[1.0, 0.0, 0.0, 0.0])
    # 視覚索引は「構築済み」(meta あり)だが、ページベクタは1件も入っていない
    upsert_meta(conn, VisualIndexMeta(notebook_id=nb.id, embedding_model="vm", built_at="t"))
    svc = _svc(conn, vs, ps, strategy="visual_only")
    hits = await svc.search(notebook_id=nb.id, query="q", limit=10)
    assert hits == []

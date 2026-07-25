import pytest

from core.retrieval.search import RetrievalService, VisualSearchDeps
from core.storage.chunks_repo import ChunkRecord, insert_chunks
from core.storage.database import connect, migrate
from core.storage.notebooks_repo import create_notebook
from core.storage.sources_repo import create_source
from core.storage.vector_store import ChunkVector, VectorStore
from core.storage.visual_index_repo import VisualIndexMeta, upsert_meta
from core.storage.visual_store import PageVector, VisualPageStore

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


def _svc(conn, vs, ps, *, encoder=None, enabled=True, model="vm"):
    from core.storage.visual_index_repo import get_meta
    return RetrievalService(
        conn=conn, vector_store=vs, ollama=FakeGateway(), embedding_model="bge-m3",
        visual=VisualSearchDeps(
            store=ps,
            encoder=encoder or FakeVisualEncoder(),
            enabled=lambda: enabled,
            meta_lookup=lambda nb_id: get_meta(conn, nb_id),
            model_name_getter=lambda: model,
        ),
    )


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

from __future__ import annotations

import pytest

pymupdf = pytest.importorskip("pymupdf")
pytestmark = pytest.mark.pdf

from core.ingestion.pipeline import IngestionPipeline, PipelineDeps  # noqa: E402
from core.storage.assets_repo import list_assets_for_source  # noqa: E402
from core.storage.chunks_repo import list_chunks_for_source  # noqa: E402
from core.storage.database import connect, migrate  # noqa: E402
from core.storage.notebooks_repo import create_notebook  # noqa: E402
from core.storage.sources_repo import SourceStatus, create_source, get_source  # noqa: E402
from core.storage.vector_store import VectorStore  # noqa: E402
from tests.unit.fixtures_pdf import build_pdf_with_image  # noqa: E402


class FakeGateway:
    async def embed(self, *, model: str, text: str) -> list[float]:
        return [float(len(text)), 0.0, 0.0, 0.0]


class FakeDescriber:
    def __init__(self, text: str | None = "図の説明: サンプル画像です。"):
        self._text = text
        self.calls = 0

    async def describe(self, *, image_png: bytes) -> str | None:
        self.calls += 1
        return self._text


def _setup(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    src = create_source(conn, notebook_id=nb.id, kind="pdf", origin="t.pdf", content_hash="h")
    vs = VectorStore(path=tmp_path / "qdrant", dim=4)
    vs.ensure_collection()
    return conn, src, vs


class RecordingBroker:
    """publish されたペイロードを順に記録するだけの broker。"""

    def __init__(self) -> None:
        self.published: list[dict] = []

    async def publish(self, topic: str, payload: dict) -> None:
        self.published.append(payload)


def _pipeline(conn, vs, *, assets_dir, describer, describe_enabled, broker=None):
    return IngestionPipeline(
        deps=PipelineDeps(
            conn=conn,
            vector_store=vs,
            ollama=FakeGateway(),
            embedding_model="bge-m3",
            broker=broker,
            assets_dir=assets_dir,
            assets_enabled=lambda: True,
            figure_describer=describer,
            figure_describe_enabled=describe_enabled,
        )
    )


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_figure_gets_described_and_creates_independent_chunk(tmp_path):
    conn, src, vs = _setup(tmp_path)
    describer = FakeDescriber("これは配置図です。")
    pipeline = _pipeline(
        conn, vs, assets_dir=tmp_path / "assets", describer=describer,
        describe_enabled=lambda: True,
    )

    await pipeline.run(source_id=src.id, kind="pdf", data=build_pdf_with_image())

    assert get_source(conn, src.id).status == SourceStatus.READY
    assert describer.calls == 1

    chunks = list_chunks_for_source(conn, src.id)
    desc_chunks = [c for c in chunks if c.kind == "figure_desc"]
    assert len(desc_chunks) == 1
    assert desc_chunks[0].text == "これは配置図です。"

    assets = list_assets_for_source(conn, src.id)
    fig = next(a for a in assets if a.kind == "figure")
    assert fig.desc_chunk_id == desc_chunks[0].id


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_figure_describe_publishes_progress(tmp_path):
    """実機FB 2026-07-26: 図が多いPDFでは図解析フェーズだけで数時間かかるが、
    status も chunk_count も動かないため「ハングした」ようにしか見えなかった。
    figure 1 件ごとに figures_done/figures_total を配信すること。"""
    conn, src, vs = _setup(tmp_path)
    broker = RecordingBroker()
    pipeline = _pipeline(
        conn, vs, assets_dir=tmp_path / "assets", describer=FakeDescriber("説明"),
        describe_enabled=lambda: True, broker=broker,
    )

    await pipeline.run(source_id=src.id, kind="pdf", data=build_pdf_with_image())

    figure_events = [p for p in broker.published if "figures_total" in p]
    # 開始時の 0/N と、figure ごとの done/N
    assert [(p["figures_done"], p["figures_total"]) for p in figure_events] == [(0, 1), (1, 1)]
    assert {p["source_id"] for p in figure_events} == {src.id}
    # 図解析中は chunking のまま(専用ステータスは増やさない)
    assert {p["status"] for p in figure_events} == {"chunking"}


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_figure_progress_advances_even_when_description_fails(tmp_path):
    """説明失敗(空応答)でも進捗は進む。失敗した図で進捗が止まると、
    ユーザーからは再びハングと区別できなくなる。"""
    conn, src, vs = _setup(tmp_path)
    broker = RecordingBroker()
    pipeline = _pipeline(
        conn, vs, assets_dir=tmp_path / "assets", describer=FakeDescriber(None),
        describe_enabled=lambda: True, broker=broker,
    )

    await pipeline.run(source_id=src.id, kind="pdf", data=build_pdf_with_image())

    figure_events = [p for p in broker.published if "figures_total" in p]
    assert (figure_events[-1]["figures_done"], figure_events[-1]["figures_total"]) == (1, 1)


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_describe_disabled_publishes_no_figure_progress(tmp_path):
    """ベータ無効時は図解析自体が走らないので進捗イベントも出ない。"""
    conn, src, vs = _setup(tmp_path)
    broker = RecordingBroker()
    pipeline = _pipeline(
        conn, vs, assets_dir=tmp_path / "assets", describer=FakeDescriber("x"),
        describe_enabled=lambda: False, broker=broker,
    )
    await pipeline.run(source_id=src.id, kind="pdf", data=build_pdf_with_image())
    assert [p for p in broker.published if "figures_total" in p] == []


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_progress_publish_failure_does_not_abort_figure_description(tmp_path):
    """進捗配信は表示のための副作用にすぎない。broker が壊れても図解析と
    取込は完走すること(表示都合で本処理を落とさない)。"""

    class FigureProgressBrokenBroker:
        """図進捗の配信だけが失敗する broker。

        全 publish を失敗させると、取込パイプライン共通の状態配信まで壊れて
        別の既存挙動(ERROR ハンドラ内の publish 再送)を測ってしまうため、
        検証対象である figures_* の配信のみを落とす。
        """

        def __init__(self) -> None:
            self.published: list[dict] = []

        async def publish(self, topic: str, payload: dict) -> None:
            if "figures_total" in payload:
                raise RuntimeError("progress publish down")
            self.published.append(payload)

    conn, src, vs = _setup(tmp_path)
    pipeline = _pipeline(
        conn, vs, assets_dir=tmp_path / "assets", describer=FakeDescriber("説明"),
        describe_enabled=lambda: True, broker=FigureProgressBrokenBroker(),
    )

    await pipeline.run(source_id=src.id, kind="pdf", data=build_pdf_with_image())

    assert get_source(conn, src.id).status == SourceStatus.READY
    assert [c for c in list_chunks_for_source(conn, src.id) if c.kind == "figure_desc"]


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_manual_describe_existing_figures_publishes_progress(tmp_path):
    """手動「図を解析」も同じ進捗契約で配信する(取込時と同じく長時間かかる)。"""
    conn, src, vs = _setup(tmp_path)
    broker = RecordingBroker()
    assets_dir = tmp_path / "assets"
    # まずベータ無効で取り込み、説明なしの figure アセットだけを作る
    await _pipeline(
        conn, vs, assets_dir=assets_dir, describer=FakeDescriber("x"),
        describe_enabled=lambda: False, broker=broker,
    ).run(source_id=src.id, kind="pdf", data=build_pdf_with_image())
    broker.published.clear()

    await _pipeline(
        conn, vs, assets_dir=assets_dir, describer=FakeDescriber("後から付けた説明"),
        describe_enabled=lambda: True, broker=broker,
    ).describe_existing_figures(source_id=src.id)

    figure_events = [p for p in broker.published if "figures_total" in p]
    assert [(p["figures_done"], p["figures_total"]) for p in figure_events] == [(0, 1), (1, 1)]
    # 既に READY のソースなので status は据え置きで配信される
    assert {p["status"] for p in figure_events} == {"ready"}


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_describe_disabled_creates_no_figure_desc_chunk(tmp_path):
    conn, src, vs = _setup(tmp_path)
    describer = FakeDescriber("使われないはず")
    pipeline = _pipeline(
        conn, vs, assets_dir=tmp_path / "assets", describer=describer,
        describe_enabled=lambda: False,
    )
    await pipeline.run(source_id=src.id, kind="pdf", data=build_pdf_with_image())
    assert get_source(conn, src.id).status == SourceStatus.READY
    assert describer.calls == 0
    chunks = list_chunks_for_source(conn, src.id)
    assert not [c for c in chunks if c.kind == "figure_desc"]


@pytest.mark.qdrant
@pytest.mark.asyncio
async def test_describe_failure_is_graceful_and_does_not_fail_ingestion(tmp_path):
    conn, src, vs = _setup(tmp_path)
    describer = FakeDescriber(None)  # 常に説明失敗
    pipeline = _pipeline(
        conn, vs, assets_dir=tmp_path / "assets", describer=describer,
        describe_enabled=lambda: True,
    )
    await pipeline.run(source_id=src.id, kind="pdf", data=build_pdf_with_image())
    assert get_source(conn, src.id).status == SourceStatus.READY
    chunks = list_chunks_for_source(conn, src.id)
    assert not [c for c in chunks if c.kind == "figure_desc"]
    # 図アセット自体は残る(未解析のまま、後で「図を解析」で再試行可能)
    assets = list_assets_for_source(conn, src.id)
    fig = next(a for a in assets if a.kind == "figure")
    assert fig.desc_chunk_id is None

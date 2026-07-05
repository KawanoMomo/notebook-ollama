"""SummaryJob のユニットテスト(リトライ・トランケーション・SSE publish)。

設計仕様: docs/specs/2026-06-25-source-guide-design.md §5.1
"""
from __future__ import annotations

import sqlite3

import pytest

from core.storage import notebooks_repo, sources_repo
from core.storage.chunks_repo import ChunkRecord, insert_chunks
from core.storage.database import migrate
from core.storage.sources_repo import SummaryStatus
from core.summary.summarizer import SummaryDeps, SummaryJob


class _FakeLLM:
    """generate を逐次的に成功/失敗させるダブル。

    `outputs` の各要素は文字列(成功時のテキスト)または Exception(失敗注入)。
    """

    def __init__(self, outputs: list):
        self.outputs = list(outputs)
        self.calls: list[dict] = []

    async def generate(self, *, model: str, prompt: str, options=None) -> str:
        self.calls.append({"model": model, "prompt": prompt, "options": options})
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


class _FakeBroker:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def publish(self, topic: str, payload: dict) -> None:
        self.events.append((topic, payload))


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    return c


def _make_source_with_chunks(
    conn: sqlite3.Connection, *, chunks: list[str]
) -> sources_repo.SourceRecord:
    nb = notebooks_repo.create_notebook(conn, name="N")
    src = sources_repo.create_source(conn, notebook_id=nb.id, kind="markdown")
    records = [
        ChunkRecord(
            id=f"c{i}",
            source_id=src.id,
            notebook_id=nb.id,
            ord=i,
            page=None,
            heading_path=None,
            text=t,
            token_count=len(t.split()),
        )
        for i, t in enumerate(chunks)
    ]
    insert_chunks(conn, records)
    return src


@pytest.mark.asyncio
async def test_success_sets_summary_and_publishes_sse(conn):
    src = _make_source_with_chunks(conn, chunks=["aaa bbb", "ccc ddd"])
    llm = _FakeLLM(["これは3行で要約された内容です。"])
    broker = _FakeBroker()
    job = SummaryJob(deps=SummaryDeps(conn=conn, llm=llm, model="llm", broker=broker))

    await job.run(source_id=src.id)

    after = sources_repo.get_source(conn, src.id)
    assert after.summary_status == SummaryStatus.READY
    assert after.summary == "これは3行で要約された内容です。"
    assert len(llm.calls) == 1

    statuses = [p["summary_status"] for (_t, p) in broker.events if "summary_status" in p]
    assert "generating" in statuses
    assert "ready" in statuses


@pytest.mark.asyncio
async def test_retries_up_to_three_times_on_transient_failure(conn):
    src = _make_source_with_chunks(conn, chunks=["aaa"])
    llm = _FakeLLM(
        [RuntimeError("transient 1"), RuntimeError("transient 2"), "成功した要約"]
    )
    job = SummaryJob(deps=SummaryDeps(conn=conn, llm=llm, model="llm", sleep=_no_sleep))

    await job.run(source_id=src.id)

    after = sources_repo.get_source(conn, src.id)
    assert after.summary == "成功した要約"
    assert after.summary_status == SummaryStatus.READY
    assert len(llm.calls) == 3


@pytest.mark.asyncio
async def test_three_failures_marks_status_error(conn):
    src = _make_source_with_chunks(conn, chunks=["aaa"])
    llm = _FakeLLM(
        [RuntimeError("e1"), RuntimeError("e2"), RuntimeError("e3")]
    )
    broker = _FakeBroker()
    job = SummaryJob(
        deps=SummaryDeps(conn=conn, llm=llm, model="llm", broker=broker, sleep=_no_sleep)
    )

    await job.run(source_id=src.id)

    after = sources_repo.get_source(conn, src.id)
    assert after.summary is None
    assert after.summary_status == SummaryStatus.ERROR
    assert len(llm.calls) == 3
    # 「3 回目の失敗で初めてユーザーにエラー通知」: SSE に error が含まれる
    statuses = [p.get("summary_status") for (_t, p) in broker.events]
    assert statuses[-1] == "error"


@pytest.mark.asyncio
async def test_no_chunks_marks_error_without_calling_llm(conn):
    nb = notebooks_repo.create_notebook(conn, name="N")
    src = sources_repo.create_source(conn, notebook_id=nb.id, kind="markdown")
    llm = _FakeLLM([])
    job = SummaryJob(deps=SummaryDeps(conn=conn, llm=llm, model="llm"))

    await job.run(source_id=src.id)

    after = sources_repo.get_source(conn, src.id)
    assert after.summary_status == SummaryStatus.ERROR
    assert llm.calls == []


@pytest.mark.asyncio
async def test_chunk_text_is_truncated_to_token_limit(conn):
    long_chunk = "ぁ" * 8000
    src = _make_source_with_chunks(conn, chunks=[long_chunk])
    llm = _FakeLLM(["ok"])
    job = SummaryJob(
        deps=SummaryDeps(conn=conn, llm=llm, model="llm", max_input_tokens=200)
    )

    await job.run(source_id=src.id)

    sent_prompt = llm.calls[0]["prompt"]
    # 上限 200 トークン以内に縮められている(プロンプト全体ではなくチャンク部分が対象だが、
    # 厳密値は実装依存なので「投入文字数 < 元チャンク文字数」をチェック)
    assert len(sent_prompt) < len(long_chunk)


# --- プロンプト設計の検証(deep-research §案A+B ハイブリッド) ---


@pytest.mark.asyncio
async def test_prompt_enforces_faithful_compression_and_format(conn):
    """プロンプトに『資料外補完禁止』『箇条書き禁止』『思考過程出力禁止』
    『3〜5 文』が含まれる。faithfulness と一貫性の両側面。"""
    src = _make_source_with_chunks(conn, chunks=["本文 A", "本文 B"])
    llm = _FakeLLM(["要約。"])
    job = SummaryJob(deps=SummaryDeps(conn=conn, llm=llm, model="llm"))

    await job.run(source_id=src.id)
    prompt = llm.calls[0]["prompt"]

    # 忠実性指示(資料外補完の禁止)
    assert "資料" in prompt
    assert "推測" in prompt or "補完" in prompt
    # 出力フォーマット制約
    assert "3" in prompt and "5" in prompt  # 3〜5 文
    assert "箇条書き" in prompt
    # 思考過程の漏出抑制
    assert "思考過程" in prompt or "推論過程" in prompt
    # 重要エンティティ(案 B 由来の網羅性指示)
    assert "固有" in prompt or "エンティティ" in prompt or "数値" in prompt


@pytest.mark.asyncio
async def test_prompt_marks_truncation_when_max_tokens_reached(conn):
    """切り詰めが発生したとき、プロンプトに『資料は途中までです』旨の注釈が
    入り、欠落部分を推測で補わない指示が残る(deep-research の長文対処)。"""
    long_chunk = "ぁ" * 8000
    src = _make_source_with_chunks(conn, chunks=[long_chunk])
    llm = _FakeLLM(["ok"])
    job = SummaryJob(
        deps=SummaryDeps(conn=conn, llm=llm, model="llm", max_input_tokens=200)
    )

    await job.run(source_id=src.id)
    prompt = llm.calls[0]["prompt"]
    # 切り詰め注釈が存在する
    assert "切り詰" in prompt or "途中" in prompt or "抜粋" in prompt


@pytest.mark.asyncio
async def test_prompt_not_marked_when_no_truncation(conn):
    """切り詰めが起きていないときに余計な注釈が混入しない。"""
    src = _make_source_with_chunks(conn, chunks=["短い本文。"])
    llm = _FakeLLM(["ok"])
    job = SummaryJob(deps=SummaryDeps(conn=conn, llm=llm, model="llm"))
    await job.run(source_id=src.id)
    prompt = llm.calls[0]["prompt"]
    assert "切り詰" not in prompt
    assert "抜粋" not in prompt


@pytest.mark.asyncio
async def test_ready_publish_includes_summary_text(conn):
    """READY の SSE payload に要約本文が載る(FE が再取得なしで即時表示する契約)。

    不具合: summary_complete 後も SSE に本文が無く、FE は
    「要約はまだ生成されていません」を表示し続けた(2026-07-04 実機報告)。
    """
    src = _make_source_with_chunks(conn, chunks=["aaa bbb"])
    llm = _FakeLLM(["要約本文です。"])
    broker = _FakeBroker()
    job = SummaryJob(deps=SummaryDeps(conn=conn, llm=llm, model="llm", broker=broker))

    await job.run(source_id=src.id)

    ready = [p for (_t, p) in broker.events if p.get("summary_status") == "ready"]
    assert ready, "ready イベントが publish されていない"
    assert ready[-1].get("summary") == "要約本文です。"


@pytest.mark.asyncio
async def test_model_getter_overrides_static_model(conn):
    """model_getter があれば実行時のモデル名を使う(起動時キャプチャの固定を回避)。"""
    src = _make_source_with_chunks(conn, chunks=["aaa"])
    llm = _FakeLLM(["ok"])
    job = SummaryJob(
        deps=SummaryDeps(
            conn=conn,
            llm=llm,
            model="stale-model",
            model_getter=lambda: "fresh-model",
        )
    )
    await job.run(source_id=src.id)
    assert llm.calls[0]["model"] == "fresh-model"


async def _no_sleep(_seconds: float) -> None:
    return None

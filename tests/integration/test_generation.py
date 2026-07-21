import pytest

from core.generation.stream import GenerationDeps, GenerationEvent, GenerationService
from core.retrieval.search import RetrievedChunk
from core.storage.assets_repo import AssetRecord


class FakeRetrieval:
    async def search(self, *, notebook_id, query, limit, source_ids=None):
        return [
            RetrievedChunk(
                chunk_id="c1",
                source_id="s1",
                source_title="ARM",
                source_kind="pdf",
                page=42,
                heading_path="§3",
                ord=0,
                text="Cortex content [...]",
                token_count=10,
                score=0.9,
            ),
        ]


class FakeGateway:
    async def chat_stream(self, *, model, messages, options=None, meta=None):
        for tok in ["回", "答", "[^1]"]:
            yield tok
        if meta is not None:
            meta["done_reason"] = "stop"


@pytest.mark.asyncio
async def test_generation_emits_retrieval_then_tokens_then_done():
    svc = GenerationService(
        deps=GenerationDeps(
            retrieval=FakeRetrieval(),
            ollama=FakeGateway(),
        )
    )
    events: list[GenerationEvent] = []
    async for ev in svc.run(
        notebook_id="nb",
        model="qwen2.5:14b",
        question="質問",
        history=[],
        num_ctx=8192,
        context_budget_ratio=0.8,
        response_budget_tokens=1024,
        retrieval_top_k=8,
        min_history_turns=1,
    ):
        events.append(ev)
    kinds = [e.kind for e in events]
    assert kinds[0] == "retrieval"
    assert "token" in kinds
    assert kinds[-1] == "done"
    final = next(e for e in events if e.kind == "done")
    assert "回答" in final.data["answer"]
    assert final.data["citations"]
    assert final.data["model_used"] == "qwen2.5:14b"


class RecordingRetrieval:
    def __init__(self):
        self.received_source_ids = "UNSET"

    async def search(self, *, notebook_id, query, limit, source_ids=None):
        self.received_source_ids = source_ids
        return [
            RetrievedChunk(
                chunk_id="c1",
                source_id="s1",
                source_title="ARM",
                source_kind="pdf",
                page=42,
                heading_path="§3",
                ord=0,
                text="Cortex content [...]",
                token_count=10,
                score=0.9,
            ),
        ]


@pytest.mark.asyncio
async def test_generation_forwards_source_ids_to_retrieval():
    retrieval = RecordingRetrieval()
    svc = GenerationService(deps=GenerationDeps(retrieval=retrieval, ollama=FakeGateway()))
    async for _ in svc.run(
        notebook_id="nb",
        model="qwen2.5:14b",
        question="質問",
        history=[],
        num_ctx=8192,
        context_budget_ratio=0.8,
        response_budget_tokens=1024,
        retrieval_top_k=8,
        min_history_turns=1,
        source_ids=["SRC_X"],
    ):
        pass
    assert retrieval.received_source_ids == ["SRC_X"]


class TruncatingGateway:
    """num_predict 上限で打ち切られた Ollama 応答(done_reason=length)を模す。"""

    async def chat_stream(self, *, model, messages, options=None, meta=None):
        for tok in ["回答の", "途中"]:
            yield tok
        if meta is not None:
            meta["done_reason"] = "length"


def _run_args(**overrides):
    base = dict(
        notebook_id="nb",
        model="qwen3:1.7b",
        question="質問",
        history=[],
        num_ctx=8192,
        context_budget_ratio=0.8,
        response_budget_tokens=1024,
        retrieval_top_k=8,
        min_history_turns=1,
    )
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_generation_marks_truncated_answer_with_visible_note():
    """done_reason=length の打ち切りを無言にしない(2026-07-05 実機FB:
    要約プロンプトの回答が文の途中で止まり、原因が見えなかった)。"""
    svc = GenerationService(
        deps=GenerationDeps(retrieval=FakeRetrieval(), ollama=TruncatingGateway())
    )
    events: list[GenerationEvent] = []
    async for ev in svc.run(**_run_args()):
        events.append(ev)

    final = next(e for e in events if e.kind == "done")
    assert final.data["truncated"] is True
    assert "上限" in final.data["answer"]
    # 注記は token イベントとしても流れる(FE 変更なしで画面と履歴に残る)
    token_texts = [e.data.get("text", "") for e in events if e.kind == "token"]
    assert any("上限" in t for t in token_texts)


@pytest.mark.asyncio
async def test_generation_no_note_when_completed_normally():
    svc = GenerationService(
        deps=GenerationDeps(retrieval=FakeRetrieval(), ollama=FakeGateway())
    )
    events: list[GenerationEvent] = []
    async for ev in svc.run(**_run_args()):
        events.append(ev)

    final = next(e for e in events if e.kind == "done")
    assert final.data["truncated"] is False
    assert "上限" not in final.data["answer"]


class ThinkingGateway:
    async def chat_stream(self, *, model, messages, options=None, meta=None):
        from core.ollama.client import ThinkingChunk

        yield ThinkingChunk("思考中の独り言")
        yield "回答"
        if meta is not None:
            meta["done_reason"] = "stop"


@pytest.mark.asyncio
async def test_generation_emits_thinking_events_but_excludes_from_answer():
    """thinking はイベントとして流れ、本文・保存内容には含めない(2026-07-05)。"""
    svc = GenerationService(
        deps=GenerationDeps(retrieval=FakeRetrieval(), ollama=ThinkingGateway())
    )
    events: list[GenerationEvent] = []
    async for ev in svc.run(**_run_args()):
        events.append(ev)

    kinds = [e.kind for e in events]
    assert "thinking" in kinds
    assert kinds.index("thinking") < kinds.index("token")
    final = next(e for e in events if e.kind == "done")
    assert final.data["answer"] == "回答"
    assert "思考中の独り言" not in final.data["answer"]


MERGED_MD = "| A | B |\n| --- | --- |\n| 1 |  |"
MERGED_HTML = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td></tr></table>"


class TableRetrieval:
    async def search(self, *, notebook_id, query, limit, source_ids=None):
        return [
            RetrievedChunk(
                chunk_id="c1",
                source_id="s1",
                source_title="ARM",
                source_kind="pdf",
                page=42,
                heading_path="§3",
                ord=0,
                text=f"前文\n\n{MERGED_MD}\n\n後文",
                token_count=10,
                score=0.9,
            ),
        ]


class RecordingGateway:
    """chat_stream に渡された messages を観測用に保持する fake gateway。"""

    def __init__(self):
        self.received_messages: list[dict[str, str]] | None = None

    async def chat_stream(self, *, model, messages, options=None, meta=None):
        self.received_messages = messages
        for tok in ["回", "答", "[^1]"]:
            yield tok
        if meta is not None:
            meta["done_reason"] = "stop"


def _table_asset() -> AssetRecord:
    return AssetRecord(
        id="a1", source_id="s1", chunk_id="c1", kind="table", page=42,
        bbox_json=None, html=MERGED_HTML, md_snippet=MERGED_MD, image_path=None,
        created_at="",
    )


@pytest.mark.asyncio
async def test_generation_substitutes_table_html_in_prompt_but_not_citation_snippet():
    """結合セル表はLLMへのプロンプトのみHTML化され、引用スニペットは元のMarkdown
    のまま(200文字切り詰めでHTMLタグが分断されるのを防ぐ設計、Task 9)。"""
    gateway = RecordingGateway()
    svc = GenerationService(
        deps=GenerationDeps(
            retrieval=TableRetrieval(),
            ollama=gateway,
            assets_lookup=lambda chunk_ids: {"c1": [_table_asset()]},
        )
    )
    events: list[GenerationEvent] = []
    async for ev in svc.run(**_run_args()):
        events.append(ev)

    assert gateway.received_messages is not None
    user_content = gateway.received_messages[-1]["content"]
    assert MERGED_HTML in user_content
    assert MERGED_MD not in user_content

    final = next(e for e in events if e.kind == "done")
    citations = final.data["citations"]
    assert citations
    snippet = citations[0]["snippet"]
    assert "<table" not in snippet
    assert MERGED_MD in snippet


@pytest.mark.asyncio
async def test_generation_without_assets_lookup_leaves_text_unchanged():
    """assets_lookup が None(既定)なら従来どおり素通り。"""
    gateway = RecordingGateway()
    svc = GenerationService(deps=GenerationDeps(retrieval=TableRetrieval(), ollama=gateway))
    async for _ in svc.run(**_run_args()):
        pass
    assert gateway.received_messages is not None
    user_content = gateway.received_messages[-1]["content"]
    assert MERGED_MD in user_content
    assert MERGED_HTML not in user_content

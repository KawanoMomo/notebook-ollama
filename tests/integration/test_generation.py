import pytest

from core.generation.stream import GenerationService, GenerationDeps, GenerationEvent
from core.retrieval.search import RetrievedChunk

class FakeRetrieval:
    async def search(self, *, notebook_id, query, limit):
        return [
            RetrievedChunk(
                chunk_id="c1", source_id="s1", source_title="ARM",
                source_kind="pdf", page=42, heading_path="§3",
                ord=0, text="Cortex content [...]", token_count=10, score=0.9,
            ),
        ]

class FakeGateway:
    async def chat_stream(self, *, model, messages, options=None):
        for tok in ["回", "答", "[^1]"]:
            yield tok

@pytest.mark.asyncio
async def test_generation_emits_retrieval_then_tokens_then_done():
    svc = GenerationService(deps=GenerationDeps(
        retrieval=FakeRetrieval(),
        ollama=FakeGateway(),
    ))
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

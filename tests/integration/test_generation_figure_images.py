import base64

import pytest

from core.generation.stream import GenerationDeps, GenerationService
from core.retrieval.search import RetrievedChunk

FIGURE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10


class FigureRetrieval:
    async def search(self, *, notebook_id, query, limit, source_ids=None):
        return [
            RetrievedChunk(
                chunk_id="fc1", source_id="s1", source_title="ARM", source_kind="pdf",
                page=5, heading_path=None, ord=0,
                text="これは配置図です。ネジが4本描かれています。",
                token_count=10, score=0.9,
            ),
        ]


class RecordingGateway:
    def __init__(self):
        self.received_messages = None

    async def chat_stream(self, *, model, messages, options=None, meta=None):
        self.received_messages = messages
        for tok in ["回", "答"]:
            yield tok
        if meta is not None:
            meta["done_reason"] = "stop"


def _run_args(**overrides):
    base = dict(
        notebook_id="nb", model="qwen3-vl", question="質問", history=[],
        num_ctx=8192, context_budget_ratio=0.8, response_budget_tokens=1024,
        retrieval_top_k=8, min_history_turns=1,
    )
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_vision_model_gets_figure_image_injected():
    gateway = RecordingGateway()
    svc = GenerationService(
        deps=GenerationDeps(
            retrieval=FigureRetrieval(),
            ollama=gateway,
            vision_check=lambda: _async_true(),
            figure_images_lookup=lambda chunk_ids: {"fc1": FIGURE_PNG},
        )
    )
    async for _ in svc.run(**_run_args()):
        pass
    assert gateway.received_messages is not None
    last = gateway.received_messages[-1]
    assert "images" in last
    assert last["images"][0] == base64.b64encode(FIGURE_PNG).decode("ascii")


@pytest.mark.asyncio
async def test_non_vision_model_gets_text_only():
    gateway = RecordingGateway()
    svc = GenerationService(
        deps=GenerationDeps(
            retrieval=FigureRetrieval(),
            ollama=gateway,
            vision_check=lambda: _async_false(),
            figure_images_lookup=lambda chunk_ids: {"fc1": FIGURE_PNG},
        )
    )
    async for _ in svc.run(**_run_args()):
        pass
    last = gateway.received_messages[-1]
    assert "images" not in last
    assert "配置図" in last["content"]  # 説明文はテキストとして投入される


@pytest.mark.asyncio
async def test_no_vision_check_configured_defaults_to_text_only():
    gateway = RecordingGateway()
    svc = GenerationService(deps=GenerationDeps(retrieval=FigureRetrieval(), ollama=gateway))
    async for _ in svc.run(**_run_args()):
        pass
    assert "images" not in gateway.received_messages[-1]


async def _async_true() -> bool:
    return True


async def _async_false() -> bool:
    return False

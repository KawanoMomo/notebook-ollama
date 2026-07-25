import base64

from core.generation.stream import GenerationDeps, GenerationService
from core.retrieval.search import RetrievedChunk

PAGE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 10
FIGURE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x02" * 10


def _hit(cid, *, page=3, via_visual=True, score=0.9):
    return RetrievedChunk(
        chunk_id=cid, source_id="s1", source_title="Doc", source_kind="pdf",
        page=page, heading_path=None, ord=0, text=f"text-{cid}", token_count=5,
        score=score, via_visual=via_visual,
    )


class Retrieval:
    def __init__(self, hits):
        self._hits = hits

    async def search(self, *, notebook_id, query, limit, source_ids=None):
        return self._hits


class RecordingGateway:
    def __init__(self):
        self.received_messages = None

    async def chat_stream(self, *, model, messages, options=None, meta=None):
        self.received_messages = messages
        yield "回答"
        if meta is not None:
            meta["done_reason"] = "stop"


async def _vision_true():
    return True


def _run_args():
    return dict(
        notebook_id="nb", model="gemma3", question="質問", history=[],
        num_ctx=8192, context_budget_ratio=0.8, response_budget_tokens=1024,
        retrieval_top_k=8, min_history_turns=1,
    )


async def test_visual_hit_page_image_injected():
    gw = RecordingGateway()
    svc = GenerationService(deps=GenerationDeps(
        retrieval=Retrieval([_hit("c1", page=3)]), ollama=gw,
        vision_check=_vision_true,
        page_images_lookup=lambda keys: {("s1", 3): PAGE_PNG},
    ))
    async for _ in svc.run(**_run_args()):
        pass
    last = gw.received_messages[-1]
    assert last["images"] == [base64.b64encode(PAGE_PNG).decode("ascii")]


async def test_total_image_cap_is_two_across_figures_and_pages():
    """図クロップ+ページ画像は合算で最大2枚(ヒット順位優先)。"""
    gw = RecordingGateway()
    hits = [
        _hit("f1", page=1, via_visual=False, score=0.9),   # figure_desc相当
        _hit("p1", page=3, via_visual=True, score=0.8),
        _hit("p2", page=4, via_visual=True, score=0.7),    # 3枚目 → 落ちる
    ]
    svc = GenerationService(deps=GenerationDeps(
        retrieval=Retrieval(hits), ollama=gw,
        vision_check=_vision_true,
        figure_images_lookup=lambda cids: {"f1": FIGURE_PNG},
        page_images_lookup=lambda keys: {("s1", 3): PAGE_PNG, ("s1", 4): PAGE_PNG},
    ))
    async for _ in svc.run(**_run_args()):
        pass
    assert len(gw.received_messages[-1]["images"]) == 2


async def test_visual_citation_location_suffix():
    gw = RecordingGateway()
    svc = GenerationService(deps=GenerationDeps(
        retrieval=Retrieval([_hit("c1", page=3)]), ollama=gw,
    ))
    events = []
    async for ev in svc.run(**_run_args()):
        events.append(ev)
    retrieval_ev = next(e for e in events if e.kind == "retrieval")
    assert retrieval_ev.data["hits"][0]["location"].endswith("(視覚検索)")


async def test_no_page_lookup_configured_keeps_text_only():
    gw = RecordingGateway()
    svc = GenerationService(deps=GenerationDeps(
        retrieval=Retrieval([_hit("c1", page=3)]), ollama=gw,
        vision_check=_vision_true,
    ))
    async for _ in svc.run(**_run_args()):
        pass
    assert "images" not in gw.received_messages[-1]

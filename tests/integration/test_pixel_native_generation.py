"""pixel_native 戦略の生成側の振る舞い (Stage 4, spec §7.3/§7.4)。

本文はプレースホルダのみで、画像が唯一の根拠になる。根拠が届かない構成では
黙って劣化させず AppError で失敗させることを検証する。
"""
from __future__ import annotations

import base64

import pytest

from core.exceptions import AppError, ErrorCode
from core.generation.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_PIXEL_NATIVE
from core.generation.stream import GenerationDeps, GenerationService
from core.retrieval.search import RetrievedChunk


class FakeRetrieval:
    def __init__(self, hits):
        self._hits = hits

    async def search(self, *, notebook_id, query, limit, source_ids=None):
        return list(self._hits)


class CapturingGateway:
    """chat_stream に渡された messages を記録して固定応答を返す。"""

    def __init__(self):
        self.messages = None

    async def chat_stream(self, *, model, messages, options=None, meta=None):
        self.messages = messages
        for ch in "回答です [^1]":
            yield ch
        if meta is not None:
            meta["done_reason"] = "stop"


def _pixel_hit(cid="vp:s1:3", *, page=3, tile_index=None):
    return RetrievedChunk(
        chunk_id=cid, source_id="s1", source_title="資料", source_kind="pdf",
        page=page, heading_path=None, ord=0,
        text="(このソースはページ画像として添付されています。"
             "添付画像を読み取って回答の根拠にしてください)",
        token_count=30, score=0.016, via_visual=True, tile_index=tile_index,
    )


def _deps(*, hits, gateway, vision=True, images=None, strategy="pixel_native", max_images=4):
    return GenerationDeps(
        retrieval=FakeRetrieval(hits),
        ollama=gateway,
        vision_check=_const_async(vision),
        page_images_lookup=(lambda keys: dict(images or {})),
        visual_strategy=lambda: strategy,
        max_images_getter=lambda: max_images,
    )


def _const_async(value):
    # vision_check は実際に応答生成へ使うモデル名を受け取る(不具合B)。
    # この Fake は値を固定で返すだけなので受け取った model は無視するが、
    # 呼び出し側の新シグネチャ vision_check(model) に合わせて引数を持つ。
    async def _f(model):
        return value
    return _f


async def _run(deps):
    svc = GenerationService(deps=deps)
    return [
        e
        async for e in svc.run(
            notebook_id="nb1", model="m", question="これは何?", history=[],
            num_ctx=8192, context_budget_ratio=0.6, response_budget_tokens=1024,
            retrieval_top_k=5, min_history_turns=1,
        )
    ]


async def test_pixel_native_uses_dedicated_system_prompt():
    gw = CapturingGateway()
    deps = _deps(hits=[_pixel_hit()], gateway=gw, images={("s1", 3, None): b"PNG"})
    await _run(deps)
    assert gw.messages[0]["role"] == "system"
    assert gw.messages[0]["content"] == SYSTEM_PROMPT_PIXEL_NATIVE
    assert gw.messages[0]["content"] != SYSTEM_PROMPT


async def test_other_strategies_keep_the_default_system_prompt():
    gw = CapturingGateway()
    deps = _deps(
        hits=[_pixel_hit()], gateway=gw, images={("s1", 3, None): b"PNG"},
        strategy="hybrid_rrf",
    )
    await _run(deps)
    assert gw.messages[0]["content"] == SYSTEM_PROMPT


async def test_pixel_native_raises_when_model_is_not_vision_capable():
    gw = CapturingGateway()
    deps = _deps(hits=[_pixel_hit()], gateway=gw, vision=False,
                 images={("s1", 3, None): b"PNG"})
    with pytest.raises(AppError) as ei:
        await _run(deps)
    assert ei.value.code == ErrorCode.INPUT_INVALID
    assert "視覚対応" in ei.value.message
    assert ei.value.remediation


async def test_pixel_native_raises_when_no_image_was_collected():
    gw = CapturingGateway()
    deps = _deps(hits=[_pixel_hit()], gateway=gw, images={})   # 画像ファイル欠落
    with pytest.raises(AppError) as ei:
        await _run(deps)
    assert ei.value.code == ErrorCode.INPUT_INVALID
    assert "根拠画像" in ei.value.message


async def test_pixel_native_raises_when_retrieval_returned_nothing():
    gw = CapturingGateway()
    deps = _deps(hits=[], gateway=gw, images={})
    with pytest.raises(AppError):
        await _run(deps)


async def test_pixel_native_image_cap_uses_max_images():
    gw = CapturingGateway()
    hits = [_pixel_hit(f"vp:s1:{p}", page=p) for p in range(1, 7)]
    images = {("s1", p, None): f"PNG{p}".encode() for p in range(1, 7)}
    deps = _deps(hits=hits, gateway=gw, images=images, max_images=4)
    await _run(deps)
    user_msg = gw.messages[-1]
    assert len(user_msg["images"]) == 4
    assert user_msg["images"][0] == base64.b64encode(b"PNG1").decode("ascii")


async def test_non_pixel_native_still_caps_at_two_images():
    gw = CapturingGateway()
    hits = [_pixel_hit(f"vp:s1:{p}", page=p) for p in range(1, 7)]
    images = {("s1", p, None): f"PNG{p}".encode() for p in range(1, 7)}
    deps = _deps(hits=hits, gateway=gw, images=images, max_images=4,
                 strategy="hybrid_rrf")
    await _run(deps)
    assert len(gw.messages[-1]["images"]) == 2


async def test_vision_check_failure_degrades_for_non_pixel_native():
    """Ollama 停止時、hybrid_rrf は画像なしで生成を続ける。"""
    class BoomVision:
        async def __call__(self, model):
            raise AppError(ErrorCode.OLLAMA_UNREACHABLE, "down")

    gw = CapturingGateway()
    deps = GenerationDeps(
        retrieval=FakeRetrieval([_pixel_hit()]),
        ollama=gw,
        vision_check=BoomVision(),
        page_images_lookup=lambda keys: {("s1", 3, None): b"PNG"},
        visual_strategy=lambda: "hybrid_rrf",
        max_images_getter=lambda: 4,
    )
    await _run(deps)
    assert "images" not in gw.messages[-1]


async def test_vision_check_failure_propagates_for_pixel_native():
    """pixel_native は画像が唯一の根拠なので握り潰さない。"""
    class BoomVision:
        async def __call__(self, model):
            raise AppError(ErrorCode.OLLAMA_UNREACHABLE, "down")

    gw = CapturingGateway()
    deps = GenerationDeps(
        retrieval=FakeRetrieval([_pixel_hit()]),
        ollama=gw,
        vision_check=BoomVision(),
        page_images_lookup=lambda keys: {("s1", 3, None): b"PNG"},
        visual_strategy=lambda: "pixel_native",
        max_images_getter=lambda: 4,
    )
    with pytest.raises(AppError) as ei:
        await _run(deps)
    assert ei.value.code == ErrorCode.OLLAMA_UNREACHABLE


async def test_vision_check_receives_the_model_actually_used_for_generation():
    """回帰テスト(実機検証15b・不具合B): ノートブック単位の default_model 上書き
    (notebooks.default_model)を無視しないよう、run() に渡された実際の model
    引数がそのまま vision_check に渡ることを検証する。グローバル既定
    (config.ollama.default_model)ではなく、chat.py が解決済みの値を見るのが
    正しい(実機で誤判定を確認済み)。"""
    gw = CapturingGateway()
    received_models: list[str] = []

    async def vision_check(model):
        received_models.append(model)
        return True

    deps = GenerationDeps(
        retrieval=FakeRetrieval([_pixel_hit()]),
        ollama=gw,
        vision_check=vision_check,
        page_images_lookup=lambda keys: {("s1", 3, None): b"PNG"},
        visual_strategy=lambda: "pixel_native",
        max_images_getter=lambda: 4,
    )
    svc = GenerationService(deps=deps)
    events = [
        e
        async for e in svc.run(
            notebook_id="nb1", model="qwen3-vl:notebook-override", question="これは何?",
            history=[], num_ctx=8192, context_budget_ratio=0.6,
            response_budget_tokens=1024, retrieval_top_k=5, min_history_turns=1,
        )
    ]
    assert received_models == ["qwen3-vl:notebook-override"]
    assert events[-1].data["model_used"] == "qwen3-vl:notebook-override"

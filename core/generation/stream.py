from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from core.exceptions import AppError, ErrorCode
from core.generation.citations import (
    CitationSpec,
    build_citations,
)
from core.generation.evidence_spans import attach_evidence_spans
from core.generation.quote_spans import attach_quote_spans, strip_quote_tags
from core.generation.sentence_ids import (
    annotate_chunk_texts,
    attach_sentence_id_spans,
    normalize_tagged_citations,
)
from core.generation.locations import format_location
from core.generation.prompts import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_PIXEL_NATIVE,
    build_system_prompt,
    PromptChunk,
    build_user_prompt,
)
from core.generation.table_assets import substitute_table_html
from core.logging import get_logger
from core.ollama.messages import build_image_message
from core.retrieval.budgeter import (
    BudgetInput,
    HistoryTurn,
    allocate_budget,
)
from core.retrieval.search import RetrievedChunk
from core.storage.assets_repo import AssetRecord

log = get_logger("generation")

TRUNCATION_NOTE_PREFIX = "\n\n---\n⚠️ 応答が出力トークン上限"


def strip_truncation_note(text: str) -> str:
    """本文末尾の打ち切り注記を取り除く(手動継続の prefill 用)。"""
    idx = text.rfind(TRUNCATION_NOTE_PREFIX)
    return text[:idx] if idx >= 0 else text


class _RetrievalLike(Protocol):
    async def search(
        self,
        *,
        notebook_id: str,
        query: str,
        limit: int,
        source_ids: list[str] | None = None,
    ) -> list[RetrievedChunk]: ...


class _GatewayLike(Protocol):
    def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        options: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]: ...


@dataclass
class GenerationDeps:
    retrieval: _RetrievalLike
    ollama: _GatewayLike
    assets_lookup: Callable[[list[str]], dict[str, list[AssetRecord]]] | None = None
    # 実際に応答生成に使うモデル名を受け取る。ノートブック単位の
    # default_model 上書き(notebooks.default_model)があるため、
    # グローバル既定を見ると誤判定する(実機検証で確認)。
    vision_check: Callable[[str], Any] | None = None  # (model) -> Awaitable[bool]
    figure_images_lookup: Callable[[list[str]], dict[str, bytes]] | None = None
    page_images_lookup: (
        Callable[
            [list[tuple[str, int, int | None]]],
            dict[tuple[str, int, int | None], bytes],
        ]
        | None
    ) = None
    # Stage 4: 検索戦略。pixel_native のときシステムプロンプトと画像上限を
    # 切り替え、根拠画像が無ければ明示エラーにする。
    visual_strategy: Callable[[], str] | None = None
    max_images_getter: Callable[[], int] | None = None


@dataclass
class GenerationEvent:
    kind: str  # "retrieval" | "token" | "done" | "error"
    data: dict[str, Any] = field(default_factory=dict)


class GenerationService:
    def __init__(self, *, deps: GenerationDeps) -> None:
        self._deps = deps

    async def run(
        self,
        *,
        notebook_id: str,
        model: str,
        question: str,
        history: list[HistoryTurn],
        num_ctx: int,
        context_budget_ratio: float,
        response_budget_tokens: int,
        retrieval_top_k: int,
        min_history_turns: int,
        source_ids: list[str] | None = None,
        auto_continue_max: int = 0,
        prefill_answer: str | None = None,
        quote_mode: bool = False,
        sentence_id_mode: bool = False,
    ) -> AsyncIterator[GenerationEvent]:
        hits = await self._deps.retrieval.search(
            notebook_id=notebook_id,
            query=question,
            limit=retrieval_top_k,
            source_ids=source_ids,
        )
        strategy = (
            self._deps.visual_strategy() if self._deps.visual_strategy is not None
            else "hybrid_rrf"
        )
        is_pixel_native = strategy == "pixel_native"
        assets_by_chunk: dict[str, list[AssetRecord]] = {}
        if self._deps.assets_lookup is not None and hits:
            assets_by_chunk = self._deps.assets_lookup([h.chunk_id for h in hits])
        def _hit_location(h: RetrievedChunk) -> str:
            location = format_location(
                page=h.page,
                heading_path=h.heading_path,
                start_ms=h.start_ms,
                speaker=h.speaker,
                tile_index=getattr(h, "tile_index", None),
            )
            if getattr(h, "via_visual", False):
                location = f"{location}(視覚検索)" if location else "(視覚検索)"
            return location

        yield GenerationEvent(
            kind="retrieval",
            data={
                "hits": [
                    {
                        "chunk_id": h.chunk_id,
                        "source_title": h.source_title,
                        "location": _hit_location(h),
                        "score": h.score,
                    }
                    for h in hits
                ]
            },
        )

        prompt_chunks: list[PromptChunk] = []
        spec_by_n: dict[int, CitationSpec] = {}
        # β: 文ID方式。プロンプト本文に <C1> を差し込み、モデルにはその番号で
        # 引用させる。refs は「文ID → チャンク上のオフセット」の対応表。
        sentence_refs: dict[int, Any] = {}
        annotated_by_chunk: dict[str, str] = {}
        if sentence_id_mode:
            annotated, sentence_refs = annotate_chunk_texts(
                [(h.chunk_id, h.text) for h in hits]
            )
            annotated_by_chunk = {h.chunk_id: a for h, a in zip(hits, annotated, strict=True)}

        for idx, hit in enumerate(hits, start=1):
            location = _hit_location(hit)
            prompt_text = hit.text
            chunk_assets = assets_by_chunk.get(hit.chunk_id)
            if chunk_assets:
                prompt_text = substitute_table_html(hit.text, chunk_assets)
            elif sentence_id_mode and hit.chunk_id in annotated_by_chunk:
                # 表 HTML 置換とは併用しない(タグとHTMLが混ざると読みにくく、
                # オフセットも合わなくなる)。表のあるチャンクは注釈しない。
                prompt_text = annotated_by_chunk[hit.chunk_id]
            prompt_chunks.append(
                PromptChunk(n=idx, title=hit.source_title, location=location, text=prompt_text)
            )
            spec_by_n[idx] = CitationSpec(
                chunk_id=hit.chunk_id,
                source_id=hit.source_id,
                source_title=hit.source_title,
                location=location,
                url_or_path=None,
                snippet=hit.text[:200],
                audio_source_id=hit.source_id if hit.start_ms is not None else None,
                audio_start_ms=hit.start_ms,
                audio_channel=hit.channel,
            )

        # quote_mode(β)は既定 OFF。OFF のとき build_system_prompt は SYSTEM_PROMPT を
        # そのまま返すので、プロンプト文字列はバイト単位で従来と同一になる。
        system_prompt = (
            SYSTEM_PROMPT_PIXEL_NATIVE
            if is_pixel_native
            else build_system_prompt(quote_mode=quote_mode, sentence_id_mode=sentence_id_mode)
        )
        budget = allocate_budget(
            BudgetInput(
                num_ctx=num_ctx,
                context_budget_ratio=context_budget_ratio,
                response_budget_tokens=response_budget_tokens,
                system_prompt=system_prompt,
                question=question,
                chunks_text=[c.text for c in prompt_chunks],
                history=history,
                min_history_turns=min_history_turns,
            )
        )
        prompt_chunks = prompt_chunks[: budget.included_chunks]
        spec_by_n = {n: s for n, s in spec_by_n.items() if n <= budget.included_chunks}

        user_prompt = build_user_prompt(chunks=prompt_chunks, question=question)
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        for turn in budget.included_history:
            messages.append({"role": "user", "content": turn.user})
            messages.append({"role": "assistant", "content": turn.assistant})

        images_b64: list[str] = []
        image_cap = (
            self._deps.max_images_getter()
            if is_pixel_native and self._deps.max_images_getter is not None
            else 2
        )
        has_figure_lookup = self._deps.figure_images_lookup is not None
        has_page_lookup = self._deps.page_images_lookup is not None
        if self._deps.vision_check is not None and (has_figure_lookup or has_page_lookup):
            try:
                is_vision = await self._deps.vision_check(model)
            except Exception:
                # pixel_native は画像が唯一の根拠なので握り潰さない。
                # 他の戦略は画像なしで生成を続ける(Ollama 停止で生成全体を
                # 落とさない — 従来は try の外で毎回落ちていた)。
                if is_pixel_native:
                    raise
                log.warning("vision_check_failed", exc_info=True)
                is_vision = False
            if is_pixel_native and not is_vision:
                raise AppError(
                    ErrorCode.INPUT_INVALID,
                    "pixel-native 検索には視覚対応のチャットモデルが必要です",
                    remediation=(
                        "設定画面でチャットモデルを vision 対応のもの(qwen3-vl 系など)に"
                        "変更するか、検索戦略を「視覚のみ」または「RRF融合」に戻してください。"
                    ),
                )
            if is_vision:
                included = hits[: budget.included_chunks]
                figure_images = (
                    self._deps.figure_images_lookup([h.chunk_id for h in included])
                    if has_figure_lookup else {}
                )
                page_keys = [
                    (h.source_id, h.page, getattr(h, "tile_index", None))
                    for h in included
                    if getattr(h, "via_visual", False) and h.page is not None
                ]
                page_images = (
                    self._deps.page_images_lookup(page_keys) if has_page_lookup else {}
                )
                # ヒット順位優先で、図クロップ+ページ/タイル画像の合算最大 image_cap 枚。
                # pixel_native は max_images_getter、他戦略は固定2枚(上で確定済み)。
                for h in included:
                    if len(images_b64) >= image_cap:
                        break
                    if h.chunk_id in figure_images:
                        images_b64.append(
                            base64.b64encode(figure_images[h.chunk_id]).decode("ascii"))
                        continue
                    key = (h.source_id, h.page, getattr(h, "tile_index", None))
                    if (
                        getattr(h, "via_visual", False)
                        and h.page is not None
                        and key in page_images
                    ):
                        images_b64.append(
                            base64.b64encode(page_images[key]).decode("ascii"))

        if is_pixel_native and not images_b64:
            raise AppError(
                ErrorCode.INPUT_INVALID,
                "pixel-native 検索の根拠画像が見つかりません",
                detail=f"hits={len(hits)}",
                remediation=(
                    "視覚インデックスを構築してください(ソース一覧の「視覚インデックス」から"
                    "構築できます)。設定の索引単位と、構築済みの単位が一致しているかも"
                    "確認してください。"
                ),
            )

        if images_b64:
            messages.append(
                build_image_message(role="user", content=user_prompt, images_b64=images_b64)
            )
        else:
            messages.append({"role": "user", "content": user_prompt})

        from core.ollama.client import ThinkingChunk

        answer_parts: list[str] = [prefill_answer] if prefill_answer else []
        continued_rounds = 0
        length_hits = 0  # done_reason=="length" だった回数。通常打ち切り文言の回数表示に使う
        continuation_failed = False  # 継続ラウンド(round>0)がAppErrorで失敗したか
        truncated = False
        for round_idx in range(1 + auto_continue_max):
            req_messages = list(messages)
            if answer_parts:
                # Ollama は末尾 assistant メッセージの続きから生成する(prefill)
                req_messages.append({"role": "assistant", "content": "".join(answer_parts)})
            stream_meta: dict[str, Any] = {}
            round_parts: list[str] = []
            try:
                async for tok in self._deps.ollama.chat_stream(
                    model=model,
                    messages=req_messages,
                    options={"num_ctx": num_ctx, "num_predict": response_budget_tokens},
                    meta=stream_meta,
                ):
                    if isinstance(tok, ThinkingChunk):
                        # 思考モデルの thinking フェーズ。本文には含めず、FE が
                        # 「思考中…」を表示できるよう別イベントで流す(2026-07-05 実機FB:
                        # 重いモデルでは思考が数分続き、無言に見えていた)。
                        yield GenerationEvent(kind="thinking", data={"text": str(tok)})
                        continue
                    round_parts.append(tok)
                    yield GenerationEvent(kind="token", data={"text": tok})
            except AppError:
                if round_idx == 0:
                    raise
                # 継続ラウンドの失敗は途中本文を失わない(graceful degradation)。
                # truncated のまま完了させ、手動ボタンで再試行できる。この回は
                # 1トークンも生成できていないため length_hits には数えない
                # (誤って「上限到達」を打ち切り理由に含めない — レビュー指摘)。
                log.warning("continuation_failed", model=model, round=round_idx)
                answer_parts.extend(round_parts)
                truncated = True
                continuation_failed = True
                break
            answer_parts.extend(round_parts)
            if stream_meta.get("done_reason") != "length":
                truncated = False
                break
            truncated = True
            length_hits += 1
            if round_idx < auto_continue_max:
                continued_rounds += 1
                yield GenerationEvent(
                    kind="continuing",
                    data={"round": continued_rounds, "max": auto_continue_max},
                )

        # num_predict 上限による打ち切りを無言にしない。思考モデル(qwen3 等)は
        # thinking トークンも予算を消費するため、見かけの回答が短くても到達しうる。
        # continuation_failed の場合は「上限到達」ではなく「継続失敗」が打ち切りの
        # 真因なので文言を分岐する(length_hits はどちらの文言でも実際に上限へ
        # 到達した回数をそのまま表す)。
        if truncated:
            if continuation_failed:
                note = (
                    f"{TRUNCATION_NOTE_PREFIX}"
                    f"({response_budget_tokens}×{length_hits}回)に達したのち、"
                    "続きの生成に失敗したため途中までの応答を表示しています。"
                )
            else:
                note = (
                    f"{TRUNCATION_NOTE_PREFIX}"
                    f"({response_budget_tokens}×{length_hits}回)に達したため打ち切られました。"
                )
            answer_parts.append(note)
            yield GenerationEvent(kind="token", data={"text": note})
            log.warning(
                "generation_truncated",
                model=model,
                response_budget_tokens=response_budget_tokens,
                continued_rounds=continued_rounds,
                continuation_failed=continuation_failed,
            )

        answer = "".join(answer_parts)
        tagged: list[tuple[int, int, int]] = []
        if sentence_id_mode:
            # `[^1:C12]` を `[^1]` に戻してから既存パイプラインへ渡す
            # (build_citations も表示も [^n] を前提にしている)。
            answer, tagged = normalize_tagged_citations(answer)
        citations = build_citations(answer=answer, specs=spec_by_n)
        chunk_texts = {h.chunk_id: h.text for h in hits}
        if sentence_id_mode and tagged:
            citations = attach_sentence_id_spans(
                citations=citations, tagged=tagged, refs=sentence_refs
            )
        if quote_mode:
            # β: LLM が併記した根拠原文を優先スパンにする。言語跨ぎで「根拠」を
            # 示せる唯一の経路。見つからなかった出現は下の第1段が拾う。
            citations = attach_quote_spans(
                answer=answer, citations=citations, chunk_texts=chunk_texts
            )
            answer = strip_quote_tags(answer)  # 表示にタグを出さない
        # 第1段(字句照合)。LLM 呼び出しも IO も無い純 CPU。通常の日本語回答では
        # 数ms だが、上限は「引用出現1件あたり十数ms」の出現数倍(chunk は
        # MAX_CHUNK_CHARS=20,000文字、一致ペアは MAX_MATCH_PAIRS=50,000 で頭打ち。
        # 超えたら特定を諦める)。同期実行するとイベントループ全体を止めるため
        # スレッドへ逃がす。
        citations = await asyncio.to_thread(
            attach_evidence_spans,
            answer=answer,
            citations=citations,
            chunk_texts=chunk_texts,
        )
        yield GenerationEvent(
            kind="done",
            data={
                "answer": answer,
                "citations": citations,
                "model_used": model,
                "dropped_history": budget.dropped_history,
                "truncated": truncated,
                "continued_rounds": continued_rounds,
            },
        )

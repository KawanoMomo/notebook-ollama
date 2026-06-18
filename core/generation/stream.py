from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from core.generation.citations import (
    CitationSpec,
    build_citations,
)
from core.generation.locations import format_location
from core.generation.prompts import SYSTEM_PROMPT, PromptChunk, build_user_prompt
from core.logging import get_logger
from core.retrieval.budgeter import (
    BudgetInput,
    HistoryTurn,
    allocate_budget,
)
from core.retrieval.search import RetrievedChunk

log = get_logger("generation")


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
        self, *, model: str, messages: list[dict[str, str]], options: dict[str, Any] | None = None
    ) -> AsyncIterator[str]: ...


@dataclass
class GenerationDeps:
    retrieval: _RetrievalLike
    ollama: _GatewayLike


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
    ) -> AsyncIterator[GenerationEvent]:
        hits = await self._deps.retrieval.search(
            notebook_id=notebook_id,
            query=question,
            limit=retrieval_top_k,
            source_ids=source_ids,
        )
        yield GenerationEvent(
            kind="retrieval",
            data={
                "hits": [
                    {
                        "chunk_id": h.chunk_id,
                        "source_title": h.source_title,
                        "location": format_location(page=h.page, heading_path=h.heading_path, start_ms=h.start_ms, speaker=h.speaker),
                        "score": h.score,
                    }
                    for h in hits
                ]
            },
        )

        prompt_chunks: list[PromptChunk] = []
        spec_by_n: dict[int, CitationSpec] = {}
        for idx, hit in enumerate(hits, start=1):
            location = format_location(page=hit.page, heading_path=hit.heading_path, start_ms=hit.start_ms, speaker=hit.speaker)
            prompt_chunks.append(
                PromptChunk(n=idx, title=hit.source_title, location=location, text=hit.text)
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

        budget = allocate_budget(
            BudgetInput(
                num_ctx=num_ctx,
                context_budget_ratio=context_budget_ratio,
                response_budget_tokens=response_budget_tokens,
                system_prompt=SYSTEM_PROMPT,
                question=question,
                chunks_text=[c.text for c in prompt_chunks],
                history=history,
                min_history_turns=min_history_turns,
            )
        )
        prompt_chunks = prompt_chunks[: budget.included_chunks]
        spec_by_n = {n: s for n, s in spec_by_n.items() if n <= budget.included_chunks}

        user_prompt = build_user_prompt(chunks=prompt_chunks, question=question)
        messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in budget.included_history:
            messages.append({"role": "user", "content": turn.user})
            messages.append({"role": "assistant", "content": turn.assistant})
        messages.append({"role": "user", "content": user_prompt})

        buffer: list[str] = []
        async for tok in self._deps.ollama.chat_stream(
            model=model,
            messages=messages,
            options={"num_ctx": num_ctx, "num_predict": response_budget_tokens},
        ):
            buffer.append(tok)
            yield GenerationEvent(kind="token", data={"text": tok})

        answer = "".join(buffer)
        citations = build_citations(answer=answer, specs=spec_by_n)
        yield GenerationEvent(
            kind="done",
            data={
                "answer": answer,
                "citations": citations,
                "model_used": model,
                "dropped_history": budget.dropped_history,
            },
        )

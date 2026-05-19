from __future__ import annotations

from typing import Any, Protocol

from core.generation.citations import CitationSpec, build_citations
from core.generation.locations import format_location
from core.generation.prompts import SYSTEM_PROMPT, PromptChunk, build_user_prompt
from core.ollama.models_info import parse_context_window
from core.retrieval.budgeter import BudgetInput, allocate_budget
from core.retrieval.search import RetrievedChunk


class _RetrievalLike(Protocol):
    async def search(self, *, notebook_id: str, query: str, limit: int) -> list[RetrievedChunk]: ...


class _GatewayLike(Protocol):
    def chat_stream(
        self, *, model: str, messages: list[dict[str, str]], options: dict[str, Any] | None = None
    ): ...


class _ClientLike(Protocol):
    async def show(self, model: str) -> dict[str, Any]: ...


_STYLE_HINTS = {
    "concise": "簡潔に回答してください。",
    "detailed": "詳細に、根拠を示して回答してください。",
    "bullet": "箇条書きで構造化して回答してください。",
}


async def ask_tool(
    *,
    notebook_id: str,
    question: str,
    model: str | None,
    style: str,
    retrieval: _RetrievalLike,
    ollama: _GatewayLike,
    client: _ClientLike,
    config: Any,
    notebook_default_model: str | None,
) -> dict[str, Any]:
    chosen_model = model or notebook_default_model or config.ollama.default_model
    show = await client.show(chosen_model)
    num_ctx = parse_context_window(show.get("parameters", "")) or 8192

    hits = await retrieval.search(
        notebook_id=notebook_id,
        query=question,
        limit=config.retrieval.top_k,
    )
    prompt_chunks: list[PromptChunk] = []
    specs: dict[int, CitationSpec] = {}
    for i, h in enumerate(hits, start=1):
        loc = format_location(page=h.page, heading_path=h.heading_path)
        prompt_chunks.append(PromptChunk(n=i, title=h.source_title, location=loc, text=h.text))
        specs[i] = CitationSpec(
            chunk_id=h.chunk_id,
            source_id=h.source_id,
            source_title=h.source_title,
            location=loc,
            url_or_path=None,
            snippet=h.text[:200],
        )

    budget = allocate_budget(
        BudgetInput(
            num_ctx=num_ctx,
            context_budget_ratio=config.generation.context_budget_ratio,
            response_budget_tokens=config.generation.response_budget_tokens,
            system_prompt=SYSTEM_PROMPT,
            question=question,
            chunks_text=[c.text for c in prompt_chunks],
            history=[],
            min_history_turns=config.retrieval.min_history_turns,
        )
    )
    prompt_chunks = prompt_chunks[: budget.included_chunks]
    specs = {n: s for n, s in specs.items() if n <= budget.included_chunks}

    user_prompt = build_user_prompt(chunks=prompt_chunks, question=question)
    style_hint = _STYLE_HINTS.get(style, _STYLE_HINTS["concise"])
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n" + style_hint},
        {"role": "user", "content": user_prompt},
    ]
    buffer: list[str] = []
    async for tok in ollama.chat_stream(
        model=chosen_model,
        messages=messages,
        options={"num_ctx": num_ctx, "num_predict": config.generation.response_budget_tokens},
    ):
        buffer.append(tok)
    answer = "".join(buffer)
    citations = [
        {
            "n": c["n"],
            "source_title": c["source_title"],
            "location": c["location"],
            "url_or_path": c["url_or_path"],
        }
        for c in build_citations(answer=answer, specs=specs)
    ]
    return {"answer": answer, "citations": citations, "model_used": chosen_model}

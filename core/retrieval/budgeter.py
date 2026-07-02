from __future__ import annotations

from dataclasses import dataclass

from core.exceptions import AppError, ErrorCode
from core.tokens import count_tokens


@dataclass
class HistoryTurn:
    user: str
    assistant: str


@dataclass
class BudgetInput:
    num_ctx: int
    context_budget_ratio: float
    response_budget_tokens: int
    system_prompt: str
    question: str
    chunks_text: list[str]
    history: list[HistoryTurn]
    min_history_turns: int


@dataclass
class BudgetOutput:
    included_chunks: int
    included_history: list[HistoryTurn]
    dropped_history: int
    used_tokens: int
    available_tokens: int


def allocate_budget(inp: BudgetInput) -> BudgetOutput:
    available = int(inp.num_ctx * inp.context_budget_ratio) - inp.response_budget_tokens
    sys_tokens = count_tokens(inp.system_prompt)
    q_tokens = count_tokens(inp.question)
    fixed = sys_tokens + q_tokens

    if available <= fixed:
        raise AppError(
            ErrorCode.GENERATION_CONTEXT_OVERFLOW,
            "question alone exceeds context budget",
            detail=f"available={available}, fixed={fixed}",
        )

    chunk_token_counts = [count_tokens(t) for t in inp.chunks_text]
    hist_token_counts = [count_tokens(t.user) + count_tokens(t.assistant) for t in inp.history]

    # Try chunk counts from full down to 0; for each pick history greedily from newest
    available_for_dyn = available - fixed
    best: BudgetOutput | None = None
    for trial_chunks in range(len(inp.chunks_text), -1, -1):
        used_chunks = sum(chunk_token_counts[:trial_chunks])
        budget_for_history = available_for_dyn - used_chunks
        if budget_for_history < 0:
            continue
        # take newest first
        kept: list[HistoryTurn] = []
        used_hist = 0
        for turn, tcount in zip(
            reversed(inp.history), reversed(hist_token_counts), strict=True
        ):
            if used_hist + tcount <= budget_for_history:
                kept.append(turn)
                used_hist += tcount
            else:
                break
        kept.reverse()
        dropped = len(inp.history) - len(kept)
        if len(kept) >= inp.min_history_turns or len(inp.history) < inp.min_history_turns:
            out = BudgetOutput(
                included_chunks=trial_chunks,
                included_history=kept,
                dropped_history=dropped,
                used_tokens=fixed + used_chunks + used_hist,
                available_tokens=available,
            )
            # Prefer max chunks; first successful trial wins because we iterate descending
            best = out
            break
    if best is None:
        # last resort: drop all chunks, all history
        if fixed <= available:
            return BudgetOutput(
                included_chunks=0,
                included_history=[],
                dropped_history=len(inp.history),
                used_tokens=fixed,
                available_tokens=available,
            )
        raise AppError(
            ErrorCode.GENERATION_CONTEXT_OVERFLOW,
            "cannot satisfy minimum context budget",
        )
    return best

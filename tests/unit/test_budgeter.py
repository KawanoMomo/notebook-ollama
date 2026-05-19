from core.retrieval.budgeter import (
    BudgetInput,
    BudgetOutput,
    HistoryTurn,
    allocate_budget,
)


def _turn(user: str, assistant: str) -> HistoryTurn:
    return HistoryTurn(user=user, assistant=assistant)

def test_budget_includes_all_history_when_room_is_plenty():
    out = allocate_budget(BudgetInput(
        num_ctx=32768,
        context_budget_ratio=0.8,
        response_budget_tokens=1024,
        system_prompt="sys",
        question="q",
        chunks_text=["c1"] * 4,
        history=[_turn("u1", "a1"), _turn("u2", "a2"), _turn("u3", "a3")],
        min_history_turns=1,
    ))
    assert len(out.included_history) == 3
    assert out.included_chunks == 4
    assert out.dropped_history == 0

def test_budget_drops_oldest_history_when_over_budget():
    big = "x " * 5000
    out = allocate_budget(BudgetInput(
        num_ctx=2048,
        context_budget_ratio=0.8,
        response_budget_tokens=512,
        system_prompt="sys",
        question="q",
        chunks_text=["short chunk"],
        history=[_turn(big, big), _turn("recent", "recent")],
        min_history_turns=1,
    ))
    assert len(out.included_history) == 1
    assert out.included_history[0].user == "recent"
    assert out.dropped_history >= 1

def test_budget_reduces_chunks_when_history_min_cannot_fit_otherwise():
    out = allocate_budget(BudgetInput(
        num_ctx=512,
        context_budget_ratio=0.8,
        response_budget_tokens=64,
        system_prompt="sys",
        question="q",
        chunks_text=["chunk " * 100, "chunk " * 100, "chunk " * 100, "chunk " * 100,
                     "chunk " * 100, "chunk " * 100, "chunk " * 100, "chunk " * 100],
        history=[_turn("h", "h")],
        min_history_turns=1,
    ))
    assert out.included_chunks < 8

def test_budget_raises_overflow_when_question_too_big():
    import pytest
    from core.exceptions import AppError, ErrorCode
    with pytest.raises(AppError) as exc:
        allocate_budget(BudgetInput(
            num_ctx=64,
            context_budget_ratio=0.8,
            response_budget_tokens=32,
            system_prompt="sys",
            question="too long " * 200,
            chunks_text=[],
            history=[],
            min_history_turns=0,
        ))
    assert exc.value.code == ErrorCode.GENERATION_CONTEXT_OVERFLOW

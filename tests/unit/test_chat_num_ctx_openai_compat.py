"""``_resolve_num_ctx`` は openai-compat 時に Ollama を叩かない。

OpenAI互換サーバーには ``/api/show`` が無い。従来はチャット送信のたびに
Ollama へ事前問い合わせしており、runtime_backend="openai-compat" 運用では
Ollama 停止時にチャット全体が塞がった(/code-review 指摘、2026-08-02)。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.api.routers import chat as chat_mod
from core.exceptions import AppError, ErrorCode


def _ctx(*, runtime_backend: str, response_budget: int = 2048) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(
            ollama=SimpleNamespace(
                runtime_backend=runtime_backend,
                endpoint="http://fake:11434",
                request_timeout_seconds=5.0,
            ),
            generation=SimpleNamespace(
                response_budget_tokens=response_budget,
                context_budget_ratio=0.8,
            ),
        )
    )


@pytest.fixture()
def forbid_ollama_client(monkeypatch):
    """OllamaClient が構築されたらテストを落とす見張り。"""

    def _boom(*a, **kw):
        raise AssertionError(
            "OllamaClient must not be constructed for openai-compat pre-check"
        )

    monkeypatch.setattr(chat_mod, "OllamaClient", _boom)


async def test_openai_compat_skips_ollama_show(forbid_ollama_client):
    ctx = _ctx(runtime_backend="openai-compat")
    num_ctx = await chat_mod._resolve_num_ctx(ctx, "any-model", model_source="global")
    assert num_ctx == 8192


async def test_openai_compat_still_enforces_budget_check(forbid_ollama_client):
    """予算検査自体は openai-compat でも生きている(既定 8192 前提)。"""
    # 8192 * 0.8 - 8000 < _MIN_PROMPT_BUDGET_TOKENS → overflow
    ctx = _ctx(runtime_backend="openai-compat", response_budget=8000)
    with pytest.raises(AppError) as ei:
        await chat_mod._resolve_num_ctx(ctx, "any-model", model_source="global")
    assert ei.value.code == ErrorCode.GENERATION_CONTEXT_OVERFLOW

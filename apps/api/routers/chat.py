from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sse_starlette.event import ServerSentEvent
from sse_starlette.sse import EventSourceResponse

from apps.api.schemas.chat import ContinueInput, Conversation, Message, MessageInput
from core.exceptions import AppError, ErrorCode
from core.generation.stream import strip_truncation_note
from core.generation.stream_registry import mark_running
from core.logging import get_logger
from core.ollama.client import OllamaClient
from core.ollama.models_info import parse_context_window
from core.retrieval.budgeter import HistoryTurn
from core.storage import (
    conversations_repo,
    messages_repo,
    notebooks_repo,
)

log = get_logger("api.chat")

# プロンプト(システム+質問+チャンク+履歴)に最低限確保したいトークン数。
# これを下回る構成は質問内容に関わらず GENERATION_CONTEXT_OVERFLOW で必ず
# 失敗するため、SSE開始前に 400+日本語メッセージで弾く(SSE開始後の例外は
# 「response already started」の500に化けてFEにはネットワークエラーしか
# 見えない — 実機FB 2026-07-26)。
_MIN_PROMPT_BUDGET_TOKENS = 512


# チャットに使うモデルがどの設定から来たか(not found 時に「どこを直せば
# よいか」を特定できないと、別の場所を切り替えても同じエラーが続く理由が
# ユーザーに見えない — 実機FB 2026-07-26 第2報)。
_MODEL_SOURCE_LABELS = {
    "notebook": "このノートブックに設定されたモデル",
    "global": "全体既定モデル",
    "message": "元の応答を生成したモデル",
}
_MODEL_SOURCE_REMEDIATIONS = {
    "notebook": (
        "ノートブック右上の「このノートのモデル」を実在するモデルに"
        "変更するか「既定」に戻してください。"
    ),
    "global": "設定→モデル・Ollama の「既定モデル」を実在するモデルに変更してください。",
    "message": "新しい質問として送信し直すと、現在設定されているモデルで回答します。",
}


def _model_base_name(name: str) -> str:
    """タグ(:以降)・大文字小文字・hf.co/ プレフィックスを無視した比較キー。"""
    return name.split(":", 1)[0].lower().removeprefix("hf.co/")


async def _similar_model_names(raw: OllamaClient, model: str) -> list[str]:
    """Ollama に実在する、タグ違い/大小文字違いの類似モデル名を探す。

    「一覧には表示されているのに not found」という混乱(実機FB 2026-07-26
    第2報)は、保存された名前と実際にpullされた名前がタグ部分だけ違う等で
    起きうる。エラー本文で実在候補を提示できれば自己解決できる。
    best-effort であり、この検索自体の失敗でエラー応答を壊してはならない。
    """
    try:
        tags = await raw.list_tags()
    except Exception:  # ヒント生成の失敗でエラー応答自体を壊さない
        return []
    target = _model_base_name(model)
    return [
        t["name"]
        for t in tags
        if _model_base_name(t["name"]) == target and t["name"] != model
    ]


async def _resolve_num_ctx(ctx, model: str, *, model_source: str) -> int:
    """モデルの num_ctx を解決し、応答予算と両立するか事前検査する。

    vision系(llava等)は Modelfile の num_ctx が小さく(2048/4096)、既定の
    応答予算 2048 と組むと質問内容に関わらず必ず失敗する。SSE開始前に
    弾いて日本語の対処メッセージを返す(send/continue 共通)。
    model_source は "notebook" / "global" / "message" のいずれかで、
    not found 時にどの設定を直せばよいかをメッセージに反映する。
    """
    if ctx.config.ollama.runtime_backend == "openai-compat":
        # OpenAI互換サーバーには /api/show が無く num_ctx をメタデータから
        # 取得できない(Phase 1.5 既知制限: モデルメタ層は Ollama 前提)。
        # ここで Ollama を叩くと compat 運用時にチャット自体が塞がるため、
        # 事前検査は既定 num_ctx=8192 での予算検査のみ行う。実際の打ち切りは
        # done_reason=length 検知(自動継続 issue #22)で救済される。
        return _check_prompt_budget(ctx, model, num_ctx=8192)
    raw = OllamaClient(
        endpoint=ctx.config.ollama.endpoint,
        timeout=ctx.config.ollama.request_timeout_seconds,
    )
    try:
        show = await raw.show(model)
    except AppError as exc:
        if exc.code is not ErrorCode.OLLAMA_MODEL_NOT_FOUND:
            raise
        # 選択済みモデルが Ollama から削除済み/未取得のケース(実機FB
        # 2026-07-26)。低レベルの英語メッセージのまま返すとFEに生JSONが
        # 出るだけで対処が分からないため、直す場所を明示して包み直す。
        similar = await _similar_model_names(raw, model)
        if similar:
            hint = (
                f"Ollama には {'、'.join(similar)} が存在します。"
                "こちらを選択し直してください。"
            )
        else:
            hint = f"このモデルを使う場合は `ollama pull {model}` で取得してください。"
        raise AppError(
            ErrorCode.OLLAMA_MODEL_NOT_FOUND,
            f"{_MODEL_SOURCE_LABELS[model_source]} {model} が Ollama に"
            "見つかりません(削除済みか、まだ取得していない可能性があります)",
            remediation=f"{_MODEL_SOURCE_REMEDIATIONS[model_source]}{hint}",
        ) from exc
    num_ctx = parse_context_window(show.get("parameters", "")) or 8192
    return _check_prompt_budget(ctx, model, num_ctx=num_ctx)


def _check_prompt_budget(ctx, model: str, *, num_ctx: int) -> int:
    """num_ctx と応答予算の両立を検査し、通れば num_ctx を返す。"""
    response_budget = ctx.config.generation.response_budget_tokens
    prompt_budget = (
        int(num_ctx * ctx.config.generation.context_budget_ratio) - response_budget
    )
    if prompt_budget < _MIN_PROMPT_BUDGET_TOKENS:
        raise AppError(
            ErrorCode.GENERATION_CONTEXT_OVERFLOW,
            f"モデル {model} のコンテキスト長(num_ctx={num_ctx})に対して"
            f"応答の長さ上限({response_budget}トークン)が大きすぎます",
            remediation=(
                "設定→生成の「応答の長さ上限」を下げるか、"
                "コンテキスト長の大きいモデルを選択してください。"
            ),
        )
    return num_ctx

router = APIRouter(prefix="/api/notebooks/{notebook_id}/conversations", tags=["chat"])


def _ping_event() -> ServerSentEvent:
    """名前付き ping イベント。

    フロントが lastBeatAt 更新に使う(未知イベントは無視されるため後方互換)。
    """
    return ServerSentEvent(data="{}", event="ping")


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Conversation)
async def create_conv(request: Request, notebook_id: str) -> Conversation:
    ctx = request.app.state.ctx
    notebooks_repo.get_notebook(ctx.conn, notebook_id)
    conv = conversations_repo.create_conversation(ctx.conn, notebook_id=notebook_id)
    return Conversation(
        id=conv.id,
        notebook_id=conv.notebook_id,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


@router.get("", response_model=list[Conversation])
async def list_convs(request: Request, notebook_id: str) -> list[Conversation]:
    ctx = request.app.state.ctx
    notebooks_repo.get_notebook(ctx.conn, notebook_id)
    items = conversations_repo.list_conversations(ctx.conn, notebook_id=notebook_id)
    return [
        Conversation(
            id=c.id,
            notebook_id=c.notebook_id,
            title=c.title,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in items
    ]


@router.get("/{conv_id}/messages", response_model=list[Message])
async def list_messages(request: Request, notebook_id: str, conv_id: str) -> list[Message]:
    ctx = request.app.state.ctx
    msgs = messages_repo.list_messages(ctx.conn, conversation_id=conv_id)
    return [
        Message(
            id=m.id,
            conversation_id=m.conversation_id,
            role=m.role,
            content=m.content,
            citations=m.citations,
            model=m.model,
            truncated=m.truncated,
            created_at=m.created_at,
        )
        for m in msgs
    ]


@router.post("/{conv_id}/messages")
async def send_message(request: Request, notebook_id: str, conv_id: str, body: MessageInput):
    ctx = request.app.state.ctx
    nb = notebooks_repo.get_notebook(ctx.conn, notebook_id)
    conv = conversations_repo.get_conversation(ctx.conn, conv_id)
    if conv.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "conversation not in notebook")

    # source_ids が空 or 未指定の場合は 400(旧「空=全選択」挙動は廃止)。
    # SSE 開始後の例外は 500 化するため、EventSourceResponse を返す前に検査する。
    if not body.source_ids:
        raise AppError(
            ErrorCode.INPUT_INVALID,
            "ソースが選択されていません。1 つ以上選んでください。",
        )

    messages_repo.append_message(
        ctx.conn, conversation_id=conv.id, role="user", content=body.content
    )

    # determine model
    model = nb.default_model or ctx.config.ollama.default_model
    model_source = "notebook" if nb.default_model else "global"

    # resolve num_ctx via Ollama show(応答予算との両立も事前検査)
    num_ctx = await _resolve_num_ctx(ctx, model, model_source=model_source)

    # gather history (exclude the just-stored user turn)
    prior = messages_repo.list_messages(ctx.conn, conversation_id=conv.id)
    history: list[HistoryTurn] = []
    pending_user: str | None = None
    for m in prior[:-1]:  # last item is the new user message
        if m.role == "user":
            pending_user = m.content
        elif m.role == "assistant" and pending_user is not None:
            history.append(HistoryTurn(user=pending_user, assistant=m.content))
            pending_user = None

    async def event_gen() -> AsyncIterator[dict[str, Any]]:
        buffer: list[str] = []
        citations: list[dict[str, Any]] = []
        truncated = False
        # 生成中は第2段(埋め込み)を走らせない。例外・クライアント切断
        # (GeneratorExit)でも finally で必ず解除される。
        with mark_running(conv.id):
            try:
                async for ev in ctx.generation.run(
                    notebook_id=notebook_id,
                    source_ids=body.source_ids,
                    model=model,
                    question=body.content,
                    history=history,
                    num_ctx=num_ctx,
                    context_budget_ratio=ctx.config.generation.context_budget_ratio,
                    response_budget_tokens=ctx.config.generation.response_budget_tokens,
                    auto_continue_max=ctx.config.generation.auto_continue_max,
                    retrieval_top_k=ctx.config.retrieval.top_k,
                    min_history_turns=ctx.config.retrieval.min_history_turns,
                ):
                    if ev.kind == "token":
                        buffer.append(ev.data["text"])
                    yield {
                        "event": ev.kind,
                        "data": json.dumps(ev.data, ensure_ascii=False),
                    }
                    if ev.kind == "done":
                        citations = ev.data["citations"]
                        truncated = ev.data["truncated"]
            except AppError as exc:
                # SSE開始後に例外を投げると "response already started" の500に化けて
                # FEには生のネットワークエラーしか見えない(実機FB 2026-07-26)。
                # error イベントとして流せば conversation store が本文に表示できる。
                log.warning("generation_failed", code=exc.code.value, detail=exc.detail)
                msg = exc.message + (f"\n{exc.remediation}" if exc.remediation else "")
                yield {
                    "event": "error",
                    "data": json.dumps({"message": msg}, ensure_ascii=False),
                }
                return
            # persist assistant message
            messages_repo.append_message(
                ctx.conn,
                conversation_id=conv.id,
                role="assistant",
                content="".join(buffer),
                citations=citations,
                model=model,
                truncated=truncated,
            )

    return EventSourceResponse(
        event_gen(),
        ping=20,
        ping_message_factory=_ping_event,
    )


@router.post("/{conv_id}/continue")
async def continue_message(
    request: Request, notebook_id: str, conv_id: str, body: ContinueInput
):
    """打ち切られた最後の assistant 応答の続きを生成し、同メッセージへ追記する。"""
    ctx = request.app.state.ctx
    nb = notebooks_repo.get_notebook(ctx.conn, notebook_id)
    conv = conversations_repo.get_conversation(ctx.conn, conv_id)
    if conv.notebook_id != notebook_id:
        raise AppError(ErrorCode.STORAGE_NOT_FOUND, "conversation not in notebook")
    if not body.source_ids:
        raise AppError(
            ErrorCode.INPUT_INVALID,
            "ソースが選択されていません。1 つ以上選んでください。",
        )

    msgs = messages_repo.list_messages(ctx.conn, conversation_id=conv_id)
    last = msgs[-1] if msgs else None
    if last is None or last.role != "assistant" or not last.truncated:
        raise HTTPException(
            status_code=409, detail="継続できる打ち切り応答がありません"
        )
    question = next((m.content for m in reversed(msgs) if m.role == "user"), None)
    if question is None:
        raise HTTPException(status_code=409, detail="継続元の質問が見つかりません")

    # 元応答と同じモデルで文体を繋ぐ(欠落時のみ既定へフォールバック)
    model = last.model or nb.default_model or ctx.config.ollama.default_model
    if last.model:
        model_source = "message"
    elif nb.default_model:
        model_source = "notebook"
    else:
        model_source = "global"
    num_ctx = await _resolve_num_ctx(ctx, model, model_source=model_source)

    # 履歴は「最後の user 質問より前」のペアのみ(打ち切り応答自体は prefill で渡す)
    history: list[HistoryTurn] = []
    pending_user: str | None = None
    for m in msgs[:-1]:
        if m.role == "user":
            pending_user = m.content
        elif m.role == "assistant" and pending_user is not None:
            history.append(HistoryTurn(user=pending_user, assistant=m.content))
            pending_user = None

    prefill = strip_truncation_note(last.content)

    async def event_gen() -> AsyncIterator[dict[str, Any]]:
        buffer: list[str] = [prefill]
        citations: list[dict[str, Any]] = []
        truncated = False
        # send_message 側と同じく生成中フラグを立てる。
        with mark_running(conv.id):
            try:
                async for ev in ctx.generation.run(
                    notebook_id=notebook_id,
                    source_ids=body.source_ids,
                    model=model,
                    question=question,
                    history=history,
                    num_ctx=num_ctx,
                    context_budget_ratio=ctx.config.generation.context_budget_ratio,
                    response_budget_tokens=ctx.config.generation.response_budget_tokens,
                    auto_continue_max=ctx.config.generation.auto_continue_max,
                    retrieval_top_k=ctx.config.retrieval.top_k,
                    min_history_turns=ctx.config.retrieval.min_history_turns,
                    prefill_answer=prefill,
                ):
                    if ev.kind == "token":
                        buffer.append(ev.data["text"])
                    yield {
                        "event": ev.kind,
                        "data": json.dumps(ev.data, ensure_ascii=False),
                    }
                    if ev.kind == "done":
                        citations = ev.data["citations"]
                        truncated = ev.data["truncated"]
            except AppError as exc:
                # send_message 側と同じ: SSE開始後の例外は error イベント化する。
                # 元メッセージは prefill のまま温存される(truncated 維持)。
                log.warning(
                    "continuation_failed_sse", code=exc.code.value, detail=exc.detail
                )
                msg = exc.message + (f"\n{exc.remediation}" if exc.remediation else "")
                yield {
                    "event": "error",
                    "data": json.dumps({"message": msg}, ensure_ascii=False),
                }
                return
            messages_repo.update_message_content(
                ctx.conn,
                message_id=last.id,
                content="".join(buffer),
                citations=citations,
                truncated=truncated,
            )

    return EventSourceResponse(event_gen(), ping=20, ping_message_factory=_ping_event)

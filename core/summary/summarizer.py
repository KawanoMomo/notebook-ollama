"""ソース要約ジョブ。

ドキュメント取込・録音変換の最終ステップで呼ばれ、全チャンクテキストを結合
した上で LLM に「3〜5文の日本語要約」を依頼する。最大 3 回まで内部リトライし、
3 回失敗で SummaryStatus.ERROR をセットする。

プロンプトは `source.kind` で自動分岐する:
  - kind == 'recording' → 議事録テンプレ(話者ラベル付き、決定/未解決/次アクション)
  - それ以外          → 汎用ドキュメントテンプレ(Faithful-Compression)

設計仕様:
  - docs/specs/2026-06-25-source-guide-design.md §5
  - docs/specs/2026-06-26-meeting-adr-templates.md
"""
from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from core.logging import get_logger
from core.storage import sources_repo
from core.storage.chunks_repo import list_chunks_for_source
from core.storage.sources_repo import SummaryStatus
from core.summary.prompts import build_document_prompt, build_meeting_prompt

log = get_logger("summary.summarizer")


class _LLMLike(Protocol):
    async def generate(
        self, *, model: str, prompt: str, options: dict | None = None
    ) -> str: ...


class _BrokerLike(Protocol):
    async def publish(self, topic: str, payload: dict[str, Any]) -> None: ...


_DEFAULT_MAX_INPUT_TOKENS = 4000
# 録音は長尺になりやすいので二段階で持つ(議事録は要点抽出に context が要る)。
_DEFAULT_MAX_INPUT_TOKENS_MEETING = 8000
_DEFAULT_MAX_ATTEMPTS = 3


@dataclass
class SummaryDeps:
    conn: sqlite3.Connection
    llm: _LLMLike
    model: str
    broker: _BrokerLike | None = None
    max_input_tokens: int = _DEFAULT_MAX_INPUT_TOKENS
    max_input_tokens_meeting: int = _DEFAULT_MAX_INPUT_TOKENS_MEETING
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


class SummaryJob:
    def __init__(self, *, deps: SummaryDeps) -> None:
        self._deps = deps

    async def run(self, *, source_id: str) -> None:
        conn = self._deps.conn

        async def _publish(status: SummaryStatus, **extra: Any) -> None:
            if self._deps.broker is None:
                return
            src = sources_repo.get_source(conn, source_id)
            await self._deps.broker.publish(
                f"notebook:{src.notebook_id}",
                {
                    "source_id": source_id,
                    "status": src.status.value,
                    "summary_status": status.value,
                    **extra,
                },
            )

        chunks = list_chunks_for_source(conn, source_id)
        if not chunks:
            sources_repo.update_source_summary_status(
                conn, source_id, status=SummaryStatus.ERROR
            )
            await _publish(SummaryStatus.ERROR, error_msg="no chunks")
            log.warning("summary_skip_no_chunks", source_id=source_id)
            return

        sources_repo.update_source_summary_status(
            conn, source_id, status=SummaryStatus.GENERATING
        )
        await _publish(SummaryStatus.GENERATING)

        # kind 分岐は SourceRecord から直接読む(SummaryJob.run のシグネチャは
        # 変えない設計、後方互換のため)。
        src = sources_repo.get_source(conn, source_id)
        prompt = self._build_prompt(src.kind, chunks)

        last_err: Exception | None = None
        for attempt in range(1, self._deps.max_attempts + 1):
            try:
                raw = await self._deps.llm.generate(
                    model=self._deps.model,
                    prompt=prompt,
                    options={"temperature": 0.2},
                )
                text = (raw or "").strip()
                if not text:
                    raise RuntimeError("empty LLM response")
                sources_repo.update_source_summary(conn, source_id, summary=text)
                await _publish(SummaryStatus.READY)
                log.info(
                    "summary_complete",
                    source_id=source_id,
                    attempt=attempt,
                    chars=len(text),
                    template="meeting" if src.kind == "recording" else "document",
                )
                return
            except Exception as exc:
                last_err = exc
                log.warning(
                    "summary_attempt_failed",
                    source_id=source_id,
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt < self._deps.max_attempts:
                    await self._deps.sleep(2 ** (attempt - 1))

        sources_repo.update_source_summary_status(
            conn, source_id, status=SummaryStatus.ERROR
        )
        await _publish(
            SummaryStatus.ERROR,
            error_msg=str(last_err) if last_err is not None else "summary failed",
        )
        log.error(
            "summary_failed",
            source_id=source_id,
            attempts=self._deps.max_attempts,
            error=str(last_err),
        )

    def _build_prompt(self, kind: str, chunks: list) -> str:
        if kind == "recording":
            return build_meeting_prompt(
                chunks, max_tokens=self._deps.max_input_tokens_meeting
            )
        return build_document_prompt(
            chunks, max_tokens=self._deps.max_input_tokens
        )

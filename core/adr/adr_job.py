"""ADR 抽出ジョブ。

ソースの全チャンクテキストを LLM に投げ、

  1. Decision Gate (yes/no + 根拠) で ADR にすべき決定が含まれるか判定
  2. yes なら抽出プロンプトで MADR 形式の Markdown を生成 → ready
  3. no なら adr_status=skipped でスキップ理由を保存

各 LLM 呼び出しに対して最大 3 回までリトライ。3 回失敗で error。

設計仕様: docs/specs/2026-06-26-meeting-adr-templates.md
"""
from __future__ import annotations

import asyncio
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

from core.adr.prompts import build_extract_prompt, build_gate_prompt
from core.logging import get_logger
from core.storage import sources_repo
from core.storage.chunks_repo import list_chunks_for_source
from core.storage.sources_repo import AdrStatus

log = get_logger("adr.adr_job")


class _LLMLike(Protocol):
    async def generate(
        self, *, model: str, prompt: str, options: dict | None = None
    ) -> str: ...


class _BrokerLike(Protocol):
    async def publish(self, topic: str, payload: dict[str, Any]) -> None: ...


_DEFAULT_MAX_INPUT_TOKENS = 6000  # ADR は context が要るので summary より長め
_DEFAULT_MAX_ATTEMPTS = 3


@dataclass
class AdrDeps:
    conn: sqlite3.Connection
    llm: _LLMLike
    model: str
    broker: _BrokerLike | None = None
    max_input_tokens: int = _DEFAULT_MAX_INPUT_TOKENS
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


_GATE_YES_RE = re.compile(r"^\s*(?:#+\s*)?YES\b", re.IGNORECASE | re.MULTILINE)
_GATE_NO_RE = re.compile(r"^\s*(?:#+\s*)?NO\b", re.IGNORECASE | re.MULTILINE)
_FRONT_MATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL | re.MULTILINE
)
_TEMPLATE_RE = re.compile(r"^template\s*:\s*(\w+)", re.IGNORECASE | re.MULTILINE)
_CONFIDENCE_RE = re.compile(
    r"^confidence\s*:\s*(\w+)", re.IGNORECASE | re.MULTILINE
)


class AdrJob:
    def __init__(self, *, deps: AdrDeps) -> None:
        self._deps = deps

    async def run(self, *, source_id: str) -> None:
        conn = self._deps.conn

        async def _publish(status: AdrStatus, **extra: Any) -> None:
            if self._deps.broker is None:
                return
            src = sources_repo.get_source(conn, source_id)
            await self._deps.broker.publish(
                f"notebook:{src.notebook_id}",
                {
                    "source_id": source_id,
                    "status": src.status.value,
                    "adr_status": status.value,
                    **extra,
                },
            )

        chunks = list_chunks_for_source(conn, source_id)
        if not chunks:
            sources_repo.update_source_adr_status(
                conn, source_id, status=AdrStatus.ERROR
            )
            await _publish(AdrStatus.ERROR, error_msg="no chunks")
            log.warning("adr_skip_no_chunks", source_id=source_id)
            return

        sources_repo.update_source_adr_status(
            conn, source_id, status=AdrStatus.GENERATING
        )
        await _publish(AdrStatus.GENERATING)

        # --- Phase 1: Decision Gate ---
        gate_prompt = build_gate_prompt(chunks, self._deps.max_input_tokens)
        try:
            gate_raw = await self._llm_with_retry(gate_prompt)
        except Exception as exc:
            sources_repo.update_source_adr_status(
                conn, source_id, status=AdrStatus.ERROR
            )
            await _publish(AdrStatus.ERROR, error_msg=str(exc))
            log.error("adr_gate_failed", source_id=source_id, error=str(exc))
            return

        gate_text = (gate_raw or "").strip()
        is_yes = bool(_GATE_YES_RE.search(gate_text))
        is_no = bool(_GATE_NO_RE.search(gate_text))
        # YES の表記が無いか、NO のみが先に出てきたらスキップ扱い。
        if (not is_yes) or is_no and gate_text.lstrip().upper().startswith("NO"):
            reason, evidence = _parse_gate_no(gate_text)
            sources_repo.update_source_adr_skipped(
                conn, source_id, reason=reason, evidence=evidence
            )
            await _publish(AdrStatus.SKIPPED, reason=reason)
            log.info("adr_gate_skipped", source_id=source_id, reason=reason)
            return

        # --- Phase 2: Extract MADR ---
        src = sources_repo.get_source(conn, source_id)
        summary_hint = src.summary if src.summary else None
        extract_prompt = build_extract_prompt(
            chunks, self._deps.max_input_tokens, summary_hint=summary_hint
        )
        try:
            adr_raw = await self._llm_with_retry(extract_prompt)
        except Exception as exc:
            sources_repo.update_source_adr_status(
                conn, source_id, status=AdrStatus.ERROR
            )
            await _publish(AdrStatus.ERROR, error_msg=str(exc))
            log.error("adr_extract_failed", source_id=source_id, error=str(exc))
            return

        body = (adr_raw or "").strip()
        if not body:
            sources_repo.update_source_adr_status(
                conn, source_id, status=AdrStatus.ERROR
            )
            await _publish(AdrStatus.ERROR, error_msg="empty extraction")
            return

        template, confidence = _parse_front_matter(body)
        sources_repo.update_source_adr(
            conn,
            source_id,
            draft=body,
            template=template,
            confidence=confidence,
        )
        await _publish(
            AdrStatus.READY, template=template, confidence=confidence
        )
        log.info(
            "adr_complete",
            source_id=source_id,
            template=template,
            confidence=confidence,
            chars=len(body),
        )

    async def _llm_with_retry(self, prompt: str) -> str:
        last_err: Exception | None = None
        for attempt in range(1, self._deps.max_attempts + 1):
            try:
                raw = await self._deps.llm.generate(
                    model=self._deps.model,
                    prompt=prompt,
                    options={"temperature": 0.2},
                )
                return raw
            except Exception as exc:
                last_err = exc
                log.warning(
                    "adr_llm_attempt_failed",
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt < self._deps.max_attempts:
                    await self._deps.sleep(2 ** (attempt - 1))
        assert last_err is not None
        raise last_err


def _parse_gate_no(text: str) -> tuple[str, str | None]:
    """Gate の NO レスポンスから reason / evidence を抽出する。
    雑な実装でも『No decision detected』は最低限返す。"""
    m = re.search(r"根拠[::]\s*(.+)$", text, re.DOTALL)
    evidence = m.group(1).strip() if m else None
    return ("No decision detected", evidence)


def _parse_front_matter(body: str) -> tuple[str, str]:
    """ADR 本文の front-matter から template / confidence を抽出。
    無ければデフォルト madr / medium。"""
    template = "madr"
    confidence = "medium"
    m = _FRONT_MATTER_RE.search(body)
    if m is None:
        return template, confidence
    fm = m.group(1)
    if (mt := _TEMPLATE_RE.search(fm)):
        template = mt.group(1).lower()
    if (mc := _CONFIDENCE_RE.search(fm)):
        confidence = mc.group(1).lower()
    return template, confidence

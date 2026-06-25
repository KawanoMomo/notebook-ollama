"""ソース要約ジョブ。

ドキュメント取込・録音変換の最終ステップで呼ばれ、全チャンクテキストを結合
した上で LLM に「3〜5文の日本語要約」を依頼する。最大 3 回まで内部リトライし、
3 回失敗で SummaryStatus.ERROR をセットする。

設計仕様: docs/specs/2026-06-25-source-guide-design.md §5
"""
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

from core.logging import get_logger
from core.storage import sources_repo
from core.storage.chunks_repo import list_chunks_for_source
from core.storage.sources_repo import SummaryStatus
from core.tokens import _encoder, count_tokens

log = get_logger("summary.summarizer")


class _LLMLike(Protocol):
    async def generate(
        self, *, model: str, prompt: str, options: dict | None = None
    ) -> str: ...


class _BrokerLike(Protocol):
    async def publish(self, topic: str, payload: dict[str, Any]) -> None: ...


# 要約プロンプト設計(deep-research §案A+B ハイブリッド・2026-06)。
#
# 採択理由(短く):
#   - Reasoning Budget Paradox (arXiv 2512.03503): CoT/長い推論は要約の
#     faithfulness を必ずしも上げない。短い「忠実圧縮」が支配的タスクなので
#     vanilla 寄りで指示する。
#   - Chain of Density (arXiv 2309.04269): エンティティ網羅は人間評価で
#     好まれるが最大密度は逆効果。「重要エンティティを過不足なく」と
#     「読みやすさを保つ」の両立指示を入れる。
#   - 出力フォーマット制約 (arXiv 2507.05123): 一貫性の改善は実証あり。
#     箇条書き禁止・3〜5文・句点終止・前置き禁止は安価に効く。
#   - 思考過程の漏出抑制: LRM 系(gpt-oss 含む)が要約本文に思考をこぼす
#     現象への防御。
#   - 切り詰め時の注釈は build 側で動的に挿入し、欠落部分を推測で補わせない。
_PROMPT_INTRO = (
    "あなたは与えられた資料の内容のみを用いて、簡潔かつ忠実に日本語で"
    "要約するアシスタントです。\n\n"
    "# 制約\n"
    "- 資料に書かれていない事実、推測、一般常識による補完は一切行わない。\n"
    "- 重要なエンティティ(人物・組織・製品・数値・日付・固有概念)を"
    "見落とさず、過不足なく含める。\n"
    "- 出力は日本語の平文で、句点で終わる 3〜5 文。"
    "箇条書き・見出し・前置き・後書きを禁止する。\n"
    "- 推論過程・思考過程を出力しない。要約本文のみを返す。\n"
    "- 固有名詞・数値・日付は原文表記を尊重する。\n"
    "- 情報量と読みやすさを両立させ、詰め込みすぎない。\n\n"
)
_PROMPT_DOC_HEAD = "# 資料\n"
_PROMPT_TRUNCATED_NOTE = (
    "\n(注: 資料は長いため先頭から一部のみ抜粋しています。"
    "本文の欠落部分は推測せず、与えられた範囲だけから要約してください。)\n"
)
_PROMPT_REQUEST = (
    "\n\n# 要求\n"
    "上記資料の要点を 3〜5 文の日本語で要約してください。"
)

_DEFAULT_MAX_INPUT_TOKENS = 4000
_DEFAULT_MAX_ATTEMPTS = 3


@dataclass
class SummaryDeps:
    conn: sqlite3.Connection
    llm: _LLMLike
    model: str
    broker: _BrokerLike | None = None
    max_input_tokens: int = _DEFAULT_MAX_INPUT_TOKENS
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

        prompt = self._build_prompt(chunks)

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

    def _build_prompt(self, chunks: list) -> str:
        joined = "\n\n".join(c.text for c in chunks)
        truncated, was_cut = self._truncate_to_tokens(
            joined, self._deps.max_input_tokens
        )
        truncation_note = _PROMPT_TRUNCATED_NOTE if was_cut else ""
        return (
            _PROMPT_INTRO
            + _PROMPT_DOC_HEAD
            + truncated
            + truncation_note
            + _PROMPT_REQUEST
        )

    @staticmethod
    def _truncate_to_tokens(text: str, max_tokens: int) -> tuple[str, bool]:
        """Return (text, was_truncated)。元のテキスト長を超えた場合のみ True。"""
        if count_tokens(text) <= max_tokens:
            return text, False
        enc = _encoder()
        ids = enc.encode(text)[:max_tokens]
        return enc.decode(ids), True

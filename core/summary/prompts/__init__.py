"""ソース要約のプロンプトテンプレ集。

- document.py: PDF / Markdown / DOCX 等の汎用ドキュメント要約。
- meeting.py: 録音(Whisper STT + 話者分離)の議事録風要約。

設計判断は docs/specs/2026-06-26-meeting-adr-templates.md と
docs/specs/2026-06-26-summary-prompt-tune.md を参照。
"""
from core.summary.prompts.document import build_document_prompt
from core.summary.prompts.meeting import build_meeting_prompt

__all__ = ["build_document_prompt", "build_meeting_prompt"]

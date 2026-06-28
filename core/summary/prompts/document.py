"""汎用ドキュメント要約プロンプト(Faithful-Compression 案)。

設計根拠: docs/specs/2026-06-25-summary-prompt-tune.md
"""
from __future__ import annotations

from core.tokens import _encoder, count_tokens

_DOC_INTRO = (
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
_DOC_HEAD = "# 資料\n"
_DOC_TRUNCATED_NOTE = (
    "\n(注: 資料は長いため先頭から一部のみ抜粋しています。"
    "本文の欠落部分は推測せず、与えられた範囲だけから要約してください。)\n"
)
_DOC_REQUEST = (
    "\n\n# 要求\n"
    "上記資料の要点を 3〜5 文の日本語で要約してください。"
)


def build_document_prompt(chunks: list, max_tokens: int) -> str:
    """汎用ドキュメント用プロンプトを組む。chunks は ChunkRecord 様の text 属性を持つ。"""
    joined = "\n\n".join(c.text for c in chunks)
    truncated, was_cut = _truncate_to_tokens(joined, max_tokens)
    note = _DOC_TRUNCATED_NOTE if was_cut else ""
    return _DOC_INTRO + _DOC_HEAD + truncated + note + _DOC_REQUEST


def _truncate_to_tokens(text: str, max_tokens: int) -> tuple[str, bool]:
    if count_tokens(text) <= max_tokens:
        return text, False
    enc = _encoder()
    ids = enc.encode(text)[:max_tokens]
    return enc.decode(ids), True

from __future__ import annotations

from dataclasses import dataclass


SYSTEM_PROMPT = """\
あなたはユーザのノートブックに含まれるソースのみに基づいて回答するアシスタントです。
以下のルールに従ってください:

1. 提供された <sources> 内の情報のみを根拠に回答する。一般知識での補完は禁止。
2. 各主張の末尾に [^n] 形式で引用番号を付ける (n は <source id="n"> の n)。
3. 引用できる情報がなければ「ノートブック内に該当情報がありません」と回答する。
4. 推測や憶測は明示的に区別する。
5. 回答は日本語で、簡潔かつ構造化（必要に応じて箇条書き・表）で出力する。
"""


@dataclass
class PromptChunk:
    n: int
    title: str
    location: str
    text: str


def build_user_prompt(*, chunks: list[PromptChunk], question: str) -> str:
    if chunks:
        source_xml = "\n".join(
            f'<source id="{c.n}" title="{_escape(c.title)}" location="{_escape(c.location)}">\n'
            f'{c.text}\n</source>'
            for c in chunks
        )
        return f"<sources>\n{source_xml}\n</sources>\n\n質問: {question}"
    return f"<sources></sources>\n\n質問: {question}"


def _escape(s: str) -> str:
    return s.replace('"', "'")

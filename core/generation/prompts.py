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

# pixel-native 検索 (Stage 4) 専用。<sources> の本文はプレースホルダのみで、
# 実体はユーザーメッセージに添付されたページ/タイル画像にある。既定の
# SYSTEM_PROMPT はルール1「<sources> 内の情報のみ」・ルール3「引用できる情報が
# なければ該当情報がありませんと回答する」を持つため、そのまま使うと本文が
# プレースホルダの <source> を見て「該当情報がありません」と答えてしまう。
SYSTEM_PROMPT_PIXEL_NATIVE = """\
あなたはユーザのノートブックに含まれるソースのみに基づいて回答するアシスタントです。
このモードでは、各ソースの中身は文章ではなく**添付された画像**として提供されます。
<source> タグの本文は「画像として添付されている」という目印にすぎません。

以下のルールに従ってください:

1. 添付画像を読み取り、そこから読み取れる内容だけを根拠に回答する。一般知識での補完は禁止。
2. 各主張の末尾に [^n] 形式で引用番号を付ける (n は <source id="n"> の n)。
   添付画像は <sources> に並ぶソースのページを写したもので、location 属性が
   どのページ・どのタイルかを示している。
3. 添付画像から読み取れる情報が無い場合のみ「ノートブック内に該当情報がありません」と回答する。
   「本文が空だから」を理由にこの回答をしてはいけない。
4. 画像から読み取った数値・ラベルは、推測した部分と明示的に区別する。
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
            f"{c.text}\n</source>"
            for c in chunks
        )
        return f"<sources>\n{source_xml}\n</sources>\n\n質問: {question}"
    return f"<sources></sources>\n\n質問: {question}"


def _escape(s: str) -> str:
    return s.replace('"', "'")

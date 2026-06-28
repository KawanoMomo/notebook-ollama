"""ADR(Architecture Decision Record)抽出プロンプト。

設計根拠: docs/specs/2026-06-26-meeting-adr-templates.md
リサーチ:
  - MADR 4.0.0 (https://adr.github.io/madr/) — 既定テンプレ
  - Michael Nygard 元祖(代替案が乏しいときのフォールバック)
  - Decision Gate (yes/no + 根拠) で雑談スキップ
"""
from __future__ import annotations

from core.tokens import _encoder, count_tokens


def _truncate(text: str, max_tokens: int) -> tuple[str, bool]:
    if count_tokens(text) <= max_tokens:
        return text, False
    enc = _encoder()
    return enc.decode(enc.encode(text)[:max_tokens]), True


def _join_with_speakers(chunks: list) -> str:
    out: list[str] = []
    for c in chunks:
        spk = getattr(c, "speaker", None)
        if spk:
            out.append(f"{spk}: {c.text}")
        else:
            out.append(c.text)
    return "\n\n".join(out)


_GATE_HEADER = (
    "あなたは入力テキストに Architecture Decision Record (ADR) に値する"
    "『決定』が含まれるかを判定する分類器です。\n\n"
    "# 判定基準\n"
    "次の 3 つのうち最低 2 つを満たすときに『YES』、満たさないときに『NO』を返してください:\n"
    "  (a) 2 つ以上の選択肢・代替案が比較されている\n"
    "  (b) 制約・トレードオフ・前提条件への明示的な言及がある\n"
    "  (c) 合意・採用・決定の宣言(『採用』『決定』『承認』『Go』『LGTM』など)がある\n\n"
    "# 出力フォーマット\n"
    "- 1 行目に『YES』または『NO』のみを書く。\n"
    "- 2 行目以降に『根拠:』に続けて、判断の根拠となった入力中の文言を 1〜2 文で引用する。\n"
    "- 推測や言い換えはせず、入力に現れた文言で根拠を示すこと。\n\n"
    "# 入力テキスト\n"
)
_GATE_FOOTER = "\n\n# 判定\n"


_EXTRACT_HEADER = (
    "あなたは入力テキストから Architecture Decision Record (ADR) を抽出する"
    "アシスタントです。MADR 4.0.0 形式の Markdown を返してください。\n\n"
    "# 出力フォーマット (Markdown + YAML front-matter)\n"
    "```\n"
    "---\n"
    "template: madr        # または考慮された選択肢が 1 件以下なら 'nygard'\n"
    "status: proposed      # 合意宣言があれば 'accepted'\n"
    "confidence: high|medium|low   # 引用率に応じて段階指定\n"
    "---\n"
    "\n"
    "# ADR: <短いタイトル>\n"
    "\n"
    "## Context and Problem Statement (背景と問題)\n"
    "<入力からの引用中心、推測は<inferred>...</inferred>で囲む>\n"
    "\n"
    "## Decision Drivers (決定要因)\n"
    "- <制約・トレードオフ・前提>\n"
    "\n"
    "## Considered Options (考慮された選択肢) — madr のみ\n"
    "- <案 A>\n"
    "- <案 B>\n"
    "\n"
    "## Decision Outcome (決定とその根拠)\n"
    "<どれを採用したか + なぜか>\n"
    "\n"
    "## Consequences (影響)\n"
    "<良い結果 / 悪い結果 / フォローアップ>\n"
    "```\n\n"
    "# 重要なルール\n"
    "- 入力に現れる文言を可能な限りそのまま引用する。\n"
    "- 推測した部分は <inferred>...</inferred> で囲む。\n"
    "- 該当情報がないセクションは『<!-- TBD: 入力に該当記載なし -->』と書き、"
    "文章で埋めない。\n"
    "- Considered Options が 1 件以下なら、front-matter の template を 'nygard' に"
    "ダウングレードし、Considered Options セクションは削除する。\n"
    "- 推論過程・思考過程を出力しない。Markdown 本文のみを返す。\n\n"
    "# 入力テキスト\n"
)
_EXTRACT_FOOTER = "\n\n# 抽出結果(Markdown のみ)\n"


def build_gate_prompt(chunks: list, max_tokens: int) -> str:
    body, _ = _truncate(_join_with_speakers(chunks), max_tokens)
    return _GATE_HEADER + body + _GATE_FOOTER


def build_extract_prompt(
    chunks: list, max_tokens: int, *, summary_hint: str | None = None
) -> str:
    body, _ = _truncate(_join_with_speakers(chunks), max_tokens)
    hint = ""
    if summary_hint:
        hint = (
            "\n\n# 既存の要約(補助情報、引用可)\n"
            + summary_hint
        )
    return _EXTRACT_HEADER + body + hint + _EXTRACT_FOOTER

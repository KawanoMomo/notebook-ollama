"""議事録(Whisper STT + 話者分離)要約プロンプト。

設計根拠: docs/specs/2026-06-26-meeting-adr-templates.md
リサーチ: arXiv 2407.11919 (Refining Meeting Summaries), arXiv 2509.13814
(AutoMin 2025), arXiv 2307.15793 (Action Items extraction), Chain of Density.

通常文書要約との違い:
  - 議事録は「決定 / 未解決 / 次のアクション」の 3 軸が必須(intent / agency /
    temporality 推論)
  - 話者ラベル付きで話者の行動を中立記述(感情/性格は推定禁止)
  - Whisper の誤認識・フィラー・口語表現の伝播抑制
"""
from __future__ import annotations

from core.tokens import _encoder, count_tokens

_MEETING_INTRO = (
    "あなたは会議の書き起こしから、議事録として使える日本語要約を作る要約器です。\n"
    "入力は Whisper による文字起こしに話者分離ラベル"
    "(『あなた』『相手1』『相手2』...)が付いたもので、"
    "誤認識・フィラー(『えーと』『そうですね』)・雑談・言い直し・"
    "相槌・繰り返しが混入します。\n\n"
    "# 最優先ルール (忠実性)\n"
    "- 書き起こしに明示的に存在しない情報(数値・固有名詞・期限・人物関係)を"
    "絶対に補完しない。推測・常識補完・一般論の追加は禁止する。\n"
    "- 固有名詞・数値・略語が不明瞭または誤認識と思われる場合は、"
    "原文表記のまま引用するか省略する。勝手に正しい綴りに直さない。\n"
    "- 同音異義語の解釈を一意に決めない。複数解釈があり得る箇所は要約に含めない。\n"
    "- 話者の感情・性格・態度・能力を推定して書かない。"
    "話者は「誰が何を主張し、誰が何を引き受けたか」という行動"
    "(提案・合意・反対・保留・引き受け)のみ、話者ラベルをそのまま引用して記述する。\n\n"
    "# 要約に含めない情報\n"
    "- 議題に直接関係しない雑談、世間話、私事\n"
    "- フィラー、相槌、言い直し\n"
    "- 同じ趣旨の発言の繰り返し\n"
    "ただし議題関連の脱線で結論に影響したものは 1 文で触れてよい。\n\n"
    "# 出力の文構成 (3〜5 文、日本語の常体)\n"
    "- 1 文目: 会議の目的(分かる範囲で)と最も重要な決定事項。"
    "決定事項が 0 件なら『本会議では確定した決定事項は無かった』と明記する。\n"
    "- 2〜3 文目: 議論で出た未解決の論点・対立点・保留事項。\n"
    "- 4〜5 文目: 次のアクション(担当者は話者ラベルをそのまま引用、"
    "期限が言及されていればそのまま、無ければ『期限未定』)。"
    "アクションが 0 件なら『次のアクションは合意されなかった』と明記する。\n\n"
    "# 出力フォーマット制約\n"
    "- 日本語の常体(である調)。敬語・絵文字・装飾記号は使わない。\n"
    "- Markdown 見出し・箇条書き・太字・コードブロックは使わない。"
    "3〜5 文の散文のみ。\n"
    "- 「私見では」「〜と思われる」「おそらく」「〜だろう」等の推測表現を使わない。\n"
    "- 推論過程・思考過程は出力しない。要約本文のみを返す。\n\n"
)
_MEETING_HEAD = "# 書き起こし\n"
_MEETING_TRUNCATED_NOTE = (
    "\n(注: 書き起こしは長いため先頭から一部のみ抜粋しています。"
    "欠落部分は推測せず、与えられた範囲だけから要約してください。)\n"
)
_MEETING_REQUEST = (
    "\n\n# 要求\n"
    "上記の書き起こしを上のルールに厳密に従って 3〜5 文の日本語で要約してください。"
)


def build_meeting_prompt(chunks: list, max_tokens: int) -> str:
    """議事録用プロンプトを組む。chunks の speaker 属性があれば prefix する。"""
    joined = _join_with_speakers(chunks)
    truncated, was_cut = _truncate_to_tokens(joined, max_tokens)
    note = _MEETING_TRUNCATED_NOTE if was_cut else ""
    return _MEETING_INTRO + _MEETING_HEAD + truncated + note + _MEETING_REQUEST


def _join_with_speakers(chunks: list) -> str:
    """speaker: text 形式で連結。speaker が無いチャンクはそのまま。"""
    out: list[str] = []
    for c in chunks:
        spk = getattr(c, "speaker", None)
        if spk:
            out.append(f"{spk}: {c.text}")
        else:
            out.append(c.text)
    return "\n\n".join(out)


def _truncate_to_tokens(text: str, max_tokens: int) -> tuple[str, bool]:
    if count_tokens(text) <= max_tokens:
        return text, False
    enc = _encoder()
    ids = enc.encode(text)[:max_tokens]
    return enc.decode(ids), True

"""セグメント整列を保つ LLM 校正。

各セグメントの start_ms / end_ms / speaker / language は不変で、text のみ補正候補に
差し替える。件数保存が最優先: バッチの parse 件数が不一致、または LLM 呼び出しが
例外を投げた場合は、そのバッチの全セグメントで原文を維持する (推測・併合・並べ替えを
一切しない)。これにより引用→音声再生に必要なタイムコード対応が壊れない。

meeting-transcriber の app/core/postprocess.py correct_segments の
件数保存バッチ方式を、Segment dataclass と await llm.generate に適応したもの。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

_LINE_RE = re.compile(r"^\s*(\d+)\.\s*(.*)$")

_PROMPT_HEADER = (
    "あなたは会議の文字起こしを校正する専門家です。\n"
    "音声認識による誤変換・誤字・句読点を、前後の文脈から自然な日本語に補正してください。\n"
    "話者の意図や意味は絶対に変えないでください。行の併合・分割は禁止です。\n"
    "入力は番号付きの行です。出力は入力と同じ行数・同じ番号付けで、各行を "
    '"番号. 補正後テキスト" の形式で返してください。\n'
    "説明文・前置き・空行を含めないでください。\n\n"
)


@dataclass
class Segment:
    start_ms: int
    end_ms: int
    speaker: str
    text: str
    language: str = "ja"


def _build_prompt(batch: list[Segment]) -> str:
    numbered = "\n".join(f"{i + 1}. {seg.text}" for i, seg in enumerate(batch))
    return _PROMPT_HEADER + "【補正対象】\n" + numbered


def _parse_lines(raw: str, expected_count: int) -> list[str] | None:
    """LLM 応答を番号順の text 列に変換。件数不一致 / parse 失敗は None。"""
    parsed: dict[int, str] = {}
    for line in (raw or "").splitlines():
        m = _LINE_RE.match(line)
        if m is None:
            continue
        n = int(m.group(1))
        if n not in parsed:
            parsed[n] = m.group(2)
    if len(parsed) != expected_count:
        return None
    if sorted(parsed.keys()) != list(range(1, expected_count + 1)):
        return None
    return [parsed[i] for i in range(1, expected_count + 1)]


async def correct_segments_aligned(
    segments: list[Segment], llm, model: str, *, batch_size: int = 8
) -> list[Segment]:
    """セグメント整列を保ったまま text を LLM 校正する。

    入力と同じ長さ・同じ順序の NEW list を返す。各セグメントの
    start_ms / end_ms / speaker / language は不変で、text のみ補正候補に差し替える。
    バッチの parse 件数不一致・LLM 例外時は、そのバッチで原文を維持する。
    """
    if not segments:
        return []

    out: list[Segment] = list(segments)
    n = len(segments)
    for start in range(0, n, batch_size):
        end = min(start + batch_size, n)
        batch = segments[start:end]
        prompt = _build_prompt(batch)
        try:
            raw = await llm.generate(
                model=model, prompt=prompt, options={"temperature": 0}
            )
            corrected = _parse_lines(raw, len(batch))
        except Exception:
            corrected = None
        if corrected is None:
            continue  # 原文維持 (out には既に原セグメントが入っている)
        for offset, text in enumerate(corrected):
            out[start + offset] = replace(batch[offset], text=text)
    return out

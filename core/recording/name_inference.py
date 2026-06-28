from __future__ import annotations

import json
import re
from dataclasses import dataclass

_PROMPT_HEADER = (
    "あなたは会議の書き起こしから、各話者の実名を推定するアシスタントです。\n"
    "手がかり例: 「○○さんお願いします」と振られた直後に応答した話者は ○○ の可能性が高い。\n"
    "自信がない話者は出力に含めないこと。'あなた' は対象外。\n"
    "出力は JSON 配列のみ。各要素は "
    '{"speaker":"相手1","name":"田中","confidence":0.0〜1.0,"evidence":"根拠"} の形式。\n\n'
)


@dataclass
class NamePrediction:
    speaker: str
    name: str
    confidence: float
    evidence: str


def build_name_inference_prompt(segments: list[dict]) -> str:
    lines = [f"{s.get('speaker','?')}: {s.get('text','')}" for s in segments]
    return _PROMPT_HEADER + "書き起こし:\n" + "\n".join(lines)


def _extract_json_array(raw: str) -> str | None:
    m = re.search(r"\[.*\]", raw or "", re.DOTALL)
    return m.group(0) if m else None


def parse_name_inference(raw: str) -> list[NamePrediction]:
    arr = _extract_json_array(raw)
    if arr is None:
        return []
    try:
        data = json.loads(arr)
    except json.JSONDecodeError:
        return []
    out: list[NamePrediction] = []
    for item in data if isinstance(data, list) else []:
        try:
            out.append(NamePrediction(
                speaker=str(item["speaker"]), name=str(item["name"]),
                confidence=float(item["confidence"]), evidence=str(item.get("evidence", "")),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return out


async def infer_names(segments: list[dict], llm, model: str, *, threshold: float) -> dict[str, str]:
    prompt = build_name_inference_prompt(segments)
    raw = await llm.generate(model=model, prompt=prompt, options={"temperature": 0})
    preds = parse_name_inference(raw)
    result: dict[str, str] = {}
    for p in preds:
        if p.speaker == "あなた":
            continue
        if p.confidence >= threshold and p.speaker not in result:
            result[p.speaker] = p.name
    return result

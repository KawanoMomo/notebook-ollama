from __future__ import annotations

_PROMPT_HEADER = (
    "以下は会議の文字起こしです。内容を表す簡潔なタイトルを 1 つだけ出力してください。\n"
    "全角20文字程度、体言止め。タイトルのみを1行で返し、引用符や前置きは付けないこと。\n\n"
)

# 本文の打ち切り長(文字数)。長い会議でもプロンプトを抑え、先頭の話題で命名する。
_MAX_BODY_CHARS = 2000


def build_title_prompt(segments: list[dict]) -> str:
    body = "\n".join(s.get("text", "") for s in segments)
    body = body[:_MAX_BODY_CHARS]
    return _PROMPT_HEADER + "文字起こし:\n" + body


def parse_title(raw: str) -> str:
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        # 「タイトル:」「Title:」等の前置きを除去(最後のコロン以降を採用)。
        for sep in ("：", ":"):
            if sep in line:
                head, _, tail = line.rpartition(sep)
                if head.strip():  # コロン前に語があれば前置きとみなす
                    line = tail.strip()
                    break
        # 前後の引用符 / 鉤括弧を除去。
        line = line.strip("\"'「」『』 　")
        if line:
            return line
    return ""


async def infer_title(segments: list[dict], llm, model: str) -> str:
    if not segments:
        return ""
    try:
        prompt = build_title_prompt(segments)
        raw = await llm.generate(model=model, prompt=prompt, options={"temperature": 0})
        return parse_title(raw)
    except Exception:
        return ""

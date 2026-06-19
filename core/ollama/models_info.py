from __future__ import annotations

import re

_JAPANESE_FAMILIES = {"qwen", "llama", "gemma", "command-r", "mistral"}
_CODE_HINTS = ("coder", "code")
_LONG_CTX_THRESHOLD = 65536
_EMBED_NAME_MARKERS = (
    "embed",
    "bge",
    "nomic-embed",
    "mxbai",
    "snowflake-arctic-embed",
    "all-minilm",
)


def classify_recommendation(
    *, name: str, family: str, parameter_size: str, context_window: int | None
) -> list[str]:
    name_lower = name.lower()
    family_lower = (family or "").lower()
    labels: list[str] = []
    if any(hint in name_lower for hint in _CODE_HINTS):
        labels.append("code")
    if family_lower in _JAPANESE_FAMILIES:
        labels.append("japanese")
    if context_window and context_window >= _LONG_CTX_THRESHOLD:
        labels.append("long-context")
    labels.append("general")
    return labels


_NUM_CTX_RE = re.compile(r"^num_ctx\s+(\d+)$", re.MULTILINE)


def parse_context_window(parameters: str) -> int | None:
    m = _NUM_CTX_RE.search(parameters or "")
    if m:
        return int(m.group(1))
    return None


def classify_kind(*, capabilities: list[str], name: str) -> str:
    """Ollama モデルを用途別に分類する。

    返り値: "chat" | "embedding" | "both" | "unknown"。
    一次情報は /api/show の capabilities。空ならば名前ヒューリスティックに
    フォールバックする。
    """
    caps = {c.lower() for c in (capabilities or [])}
    has_embedding = "embedding" in caps
    has_chat = "completion" in caps or "chat" in caps
    if has_embedding and has_chat:
        return "both"
    if has_embedding:
        return "embedding"
    if has_chat:
        return "chat"

    # フォールバック: 名前ヒューリスティック。
    name_lower = (name or "").lower()
    if not name_lower:
        return "unknown"
    if any(marker in name_lower for marker in _EMBED_NAME_MARKERS):
        return "embedding"
    return "chat"

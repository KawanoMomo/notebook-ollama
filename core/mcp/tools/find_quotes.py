from __future__ import annotations

from typing import Any, Protocol

from core.exceptions import AppError, ErrorCode
from core.generation.locations import format_location
from core.retrieval.search import RetrievedChunk


class _RetrievalLike(Protocol):
    async def search(self, *, notebook_id: str, query: str, limit: int) -> list[RetrievedChunk]: ...


async def find_quotes_tool(
    *,
    notebook_id: str,
    query: str,
    max_quotes: int,
    retrieval: _RetrievalLike,
    config: Any,
    search_strategy: str | None = None,
) -> dict[str, Any]:
    # pixel_native は画像が唯一の根拠だが、MCP 経路には画像投入機構が一切無い
    # (build_image_message を呼ばず SYSTEM_PROMPT をそのまま使う)。そのまま
    # 通すとプレースホルダ本文だけを見たモデルが根拠なく回答してしまう
    # (spec §7.4 が名指しで禁じる失敗)。黙って通さず明示的に失敗させる。
    strategy = (
        search_strategy if search_strategy is not None
        else config.visual.search_strategy
    )
    if strategy == "pixel_native":
        raise AppError(
            ErrorCode.INPUT_INVALID,
            "MCP 経由の検索は pixel-native 戦略に対応していません",
            remediation=(
                "設定画面で検索戦略を「視覚のみ」または「RRF融合」に戻してください。"
                "pixel-native はチャット画面でのみ利用できます。"
            ),
        )
    capped = min(max(max_quotes, 1), 10)
    hits = await retrieval.search(notebook_id=notebook_id, query=query, limit=capped)
    quotes = [
        {
            "text": h.text,
            "source_title": h.source_title,
            # ask.py と同じく全項目を渡す (録音の話者/タイムコード・タイル番号が落ちる)
            "location": format_location(
                page=h.page,
                heading_path=h.heading_path,
                start_ms=h.start_ms,
                speaker=h.speaker,
                tile_index=getattr(h, "tile_index", None),
            ),
        }
        for h in hits[:capped]
    ]
    return {"quotes": quotes}

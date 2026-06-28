"""お知らせ (release notes) JSON の読み込み層。

spec §5.3 / plan Sprint 3 Task 3.6。

設計方針:
- お知らせは ``data/notices.json`` に静的に持つ (MVP)。
- 読み込みは「決して例外でアプリ起動を止めない」: ファイル不在 / 不正 JSON /
  想定外スキーマ / エントリ単位の欠損はすべて飲み込み、可能な範囲のお知らせ
  を返す。失敗は ``logging.warning`` に残し、運用者が気付けるようにする。
- 並び順は ``date`` (ISO 8601 ``YYYY-MM-DD``) の **降順**。ISO 形式は辞書順
  ソートで時系列順に並ぶため、別途 ``datetime`` パースは不要。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class Notice:
    """1 件のお知らせ。

    Attributes:
        id: 安定 ID (フロントの localStorage 既読管理キー)。
        date: ISO 8601 ``YYYY-MM-DD``。並び替えに使う。
        title: 一覧に表示する見出し。
        body: Markdown 本文。
        subsections: 任意のサブセクション。``[{heading, items}]`` 形式で、
            「新機能」「改善」のような小見出し + 箇条書きをそのまま表現する。
            無ければ ``None``。
    """

    id: str
    date: str
    title: str
    body: str
    subsections: list[dict] | None = None


# 必須フィールド (この順序で取り出し、欠落していればエントリを skip する)
_REQUIRED_STR_FIELDS: tuple[str, ...] = ("id", "date", "title", "body")


def _coerce_subsections(value: Any) -> list[dict] | None:
    """``subsections`` フィールドを正規化する。

    - ``None`` / 未指定 → ``None``
    - list 以外 → 不正なので ``ValueError``
    - 各要素は ``{"heading": str, "items": list[str]}`` を要求。逸脱は
      ``ValueError`` で呼び出し側に伝え、エントリごと skip させる。
    """
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError(f"subsections must be a list, got {type(value).__name__}")
    out: list[dict] = []
    for i, sub in enumerate(value):
        if not isinstance(sub, dict):
            raise ValueError(f"subsections[{i}] must be a dict")
        heading = sub.get("heading")
        items = sub.get("items")
        if not isinstance(heading, str):
            raise ValueError(f"subsections[{i}].heading must be a string")
        if not isinstance(items, list) or not all(isinstance(x, str) for x in items):
            raise ValueError(f"subsections[{i}].items must be a list of strings")
        out.append({"heading": heading, "items": list(items)})
    return out


def _entry_to_notice(entry: Any) -> Notice | None:
    """単一エントリを Notice に変換する。不正なら ``None``。"""
    if not isinstance(entry, dict):
        return None
    values: dict[str, Any] = {}
    for field_name in _REQUIRED_STR_FIELDS:
        v = entry.get(field_name)
        if not isinstance(v, str) or not v:
            return None
        values[field_name] = v
    try:
        subsections = _coerce_subsections(entry.get("subsections"))
    except ValueError as exc:
        log.warning("notices.json: dropping entry id=%r (%s)", values["id"], exc)
        return None
    return Notice(
        id=values["id"],
        date=values["date"],
        title=values["title"],
        body=values["body"],
        subsections=subsections,
    )


def load_notices(notices_path: Path) -> list[Notice]:
    """``notices_path`` を読み、お知らせ一覧を ``date`` 降順で返す。

    失敗ポリシ (すべて空リストで吸収、warning ログを残す):
    - ファイル不在 → ``[]`` (ログは出さない: 開発環境では通常)。
    - 空ファイル / JSON パース失敗 → ``[]`` + warning。
    - root が dict でない / ``notices`` キー不在 / ``notices`` が list でない →
      ``[]`` + warning。
    - 個別エントリの必須フィールド (id/date/title/body) 欠損または非文字列 →
      そのエントリだけ skip (warning は出さず、ログ汎濫を避ける)。
    - ``subsections`` の形が崩れているエントリは skip + warning。
    """
    path = Path(notices_path)
    if not path.is_file():
        return []

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("notices.json: cannot read %s: %s", path, exc)
        return []

    if not text.strip():
        log.warning("notices.json: file is empty: %s", path)
        return []

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        log.warning("notices.json: invalid JSON in %s: %s", path, exc)
        return []

    if not isinstance(data, dict):
        log.warning("notices.json: root must be an object, got %s", type(data).__name__)
        return []

    raw_entries = data.get("notices")
    if raw_entries is None:
        log.warning("notices.json: missing 'notices' key in %s", path)
        return []
    if not isinstance(raw_entries, list):
        log.warning(
            "notices.json: 'notices' must be a list, got %s",
            type(raw_entries).__name__,
        )
        return []

    notices: list[Notice] = []
    for entry in raw_entries:
        notice = _entry_to_notice(entry)
        if notice is not None:
            notices.append(notice)

    # ISO 8601 (YYYY-MM-DD) は辞書順 = 時系列順なので reverse=True で降順
    notices.sort(key=lambda n: n.date, reverse=True)
    return notices

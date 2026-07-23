"""ベータ機能フラグレジストリ(spec: 2026-07-20-beta-feature-flags-design)。

フラグ定義はこのファイルだけが真実。GA昇格は該当エントリの stage を 'ga' に
変える1行変更で完了する(ゲートは is_enabled 経由なので他の変更は不要)。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureFlag:
    id: str
    name: str
    description: str
    stage: str  # 'beta' | 'ga'
    since: str
    spec: str


REGISTRY: tuple[FeatureFlag, ...] = (
    FeatureFlag(
        id="table-figure-rag",
        name="表・図検索強化",
        description="PDFの表・図を抽出し、検索と回答に反映するベータ機能",
        stage="beta",
        since="2026-07-20",
        spec="docs/specs/2026-07-20-pdf-table-figure-sidecar-design.md",
    ),
)


def get_flag(flag_id: str) -> FeatureFlag | None:
    return next((f for f in REGISTRY if f.id == flag_id), None)


def is_enabled(flag_id: str, optins: dict[str, bool]) -> bool:
    flag = get_flag(flag_id)
    if flag is None:
        return False
    if flag.stage == "ga":
        return True
    return optins.get(flag_id, False) is True

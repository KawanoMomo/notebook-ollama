"""設定マトリクスの展開と、再インデックス要否の仕分け。

純粋関数のみで構成し、検索も索引構築も行わない (spec §4.2)。
"""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# 値を変えるとタイル索引の再構築が必要になる設定キー。
# index_unit はここに含めない: page 索引と tile 索引は同時保持でき、
# 切替に再構築を要さない (core/config.py VisualSettings の実装コメント)。
REINDEX_KEYS = frozenset({"embedding_model", "tile_rows", "tile_cols", "tile_overlap"})

_REQUIRED_SPEC_KEYS = ("name", "corpus", "golden", "notebook_id", "baseline")


class MatrixError(Exception):
    """マトリクス定義が不正。"""


@dataclass(frozen=True)
class Condition:
    id: str
    overrides: dict[str, Any]
    requires_reindex: bool


@dataclass(frozen=True)
class SweepSpec:
    name: str
    corpus: str
    golden: str
    # 検索対象のノートブックID。コーパスを取り込んだ先を指す (CLI が
    # RetrievalService.search へそのまま渡す)。
    notebook_id: str
    baseline: dict[str, Any]
    axes: dict[str, list[Any]]


def condition_id(overrides: dict[str, Any]) -> str:
    """キーの並び順に依存しない安定ハッシュ。"""
    payload = json.dumps(overrides, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def load_sweep(path: Path) -> SweepSpec:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

    for key in _REQUIRED_SPEC_KEYS:
        if key not in raw:
            raise MatrixError(f"{path}: 必須キーが無い: {key}")

    return SweepSpec(
        name=str(raw["name"]),
        corpus=str(raw["corpus"]),
        golden=str(raw["golden"]),
        notebook_id=str(raw["notebook_id"]),
        baseline=dict(raw["baseline"]),
        axes={k: list(v) for k, v in (raw.get("axes") or {}).items()},
    )


def expand(spec: SweepSpec) -> list[Condition]:
    """軸の直積を展開する。先頭は必ず baseline 条件。"""
    for key, values in spec.axes.items():
        if key not in spec.baseline:
            raise MatrixError(
                f"軸 {key!r} が baseline に無い。baseline に既定値を書くこと"
            )
        if not values:
            raise MatrixError(f"軸 {key!r} の値が空")

    keys = sorted(spec.axes)
    products = itertools.product(*(spec.axes[k] for k in keys)) if keys else [()]

    conditions: list[Condition] = []
    for combo in products:
        overrides = dict(spec.baseline)
        overrides.update(dict(zip(keys, combo, strict=True)))
        conditions.append(
            Condition(
                id=condition_id(overrides),
                overrides=overrides,
                requires_reindex=_needs_reindex(overrides, spec.baseline),
            )
        )

    baseline_id = condition_id(spec.baseline)
    conditions.sort(key=lambda c: (c.id != baseline_id,))
    return conditions


def _needs_reindex(overrides: dict[str, Any], baseline: dict[str, Any]) -> bool:
    """索引形状に関わるキーが baseline と違えば再構築が要る。"""
    return any(overrides.get(k) != baseline.get(k) for k in REINDEX_KEYS)


def _index_shape(overrides: dict[str, Any]) -> tuple:
    return tuple(sorted((k, str(overrides.get(k))) for k in REINDEX_KEYS))


def partition(conditions: list[Condition]) -> tuple[list[Condition], list[Condition]]:
    """(検索時パラメータのみの条件, 再インデックスが要る条件)。"""
    search_only = [c for c in conditions if not c.requires_reindex]
    reindex = [c for c in conditions if c.requires_reindex]
    return search_only, reindex


def reindex_count(conditions: list[Condition]) -> int:
    """索引構築が実際に何回走るか。同じ索引形状の条件はまとめて1回。"""
    shapes = {_index_shape(c.overrides) for c in conditions if c.requires_reindex}
    return len(shapes)

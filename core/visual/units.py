"""視覚索引の「単位」語彙の単一の出どころ。

`page` / `tile` の語彙は当初 5 箇所に散っていた (core/config.py の Literal /
apps/api/schemas/settings.py の Literal 2 つ / apps/api/routers/visual_index.py の
UNITS と UnitParam / core/storage/visual_store.py の _COLLECTION_BY_UNIT)。
単位を増やすたびに全部を直す必要があり、直し漏れると
「設定では選べるがコレクションが無い」といった半端な状態になる。

このモジュールは依存を持たないリーフに保つこと (config / storage / routers /
schemas のすべてから import されるため、ここが何かを import すると循環しやすい)。
"""

from __future__ import annotations

from typing import Literal, get_args

VisualUnit = Literal["page", "tile"]
"""索引単位。設定値・API のクエリパラメータ・ストアのコレクション選択で共有する。"""

VISUAL_UNITS: tuple[VisualUnit, ...] = get_args(VisualUnit)
"""`VisualUnit` の全値。反復用 (GET /visual-index が両単位を返す等)。

`get_args` で導出しているので、Literal に値を足せば自動的に増える。
"""

DEFAULT_VISUAL_UNIT: VisualUnit = "page"
"""既定の索引単位。Stage 3 までの唯一の単位であり、既存挙動と一致させるための値。"""

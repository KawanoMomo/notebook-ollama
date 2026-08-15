"""コード領域判定の基準面が FE (markdown-it) と一致することの回帰テスト。

BE と FE で「どこがコードか」の判定がズレると、ズレた箇所より後ろの
answer_occurrence が全部1つずつ動く。同じ引用番号が前後に出ていると、別の主張の
根拠を枝番付きで自信満々に表示する誤帰属になる(検証で再現済み)。

ケースは FE と共有する: tests/fixtures/code_region_cases.json
対の FE テスト: apps/web/tests/unit/citationCodeRegions.test.ts
(FE 側は手書き HTML ではなく実際に markdown-it へ通して数える)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.generation.evidence_spans import iter_claim_occurrences

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "code_region_cases.json"
_CASES = json.loads(_FIXTURE.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_code_region_baseline_matches_markdown_it(case):
    got = [c.n for c in iter_claim_occurrences(case["markdown"])]
    assert got == case["expected"], case.get("why", "")


def test_misattribution_repro_keeps_occurrence_alignment():
    """入れ子箇条書きで根拠が1つズレていた実例。"""
    answer = (
        "能力レベルについて説明する。\n\n"
        "- プロセス能力レベル1は…を示す[^3]\n"
        "    - なお詳細は規格本文を参照のこと[^3]\n"
        "- レベル2では作業成果物が適切に管理される[^3]\n"
    )
    got = iter_claim_occurrences(answer)
    assert [(c.n, c.answer_occurrence) for c in got] == [(3, 0), (3, 1), (3, 2)]
    assert "プロセス能力レベル1" in got[0].claim
    assert "規格本文を参照" in got[1].claim
    assert "レベル2では作業成果物" in got[2].claim

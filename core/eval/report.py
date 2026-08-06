"""条件別比較表の markdown 生成 (純粋関数)。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.eval.metrics import QuestionScore

# 表に出す指標と表示名。context_recall を先頭に置く (spec §6: 主指標)。
_METRIC_ORDER = (
    ("context_recall", "ctx recall"),
    ("context_precision", "ctx precision"),
    ("recall_at_k", "recall@k"),
    ("mrr", "MRR"),
)


@dataclass(frozen=True)
class ConditionSummary:
    condition_id: str
    overrides: dict[str, Any]
    overall: dict[str, float]
    by_kind: dict[str, dict[str, float]]
    elapsed_s: float
    failed_reason: str | None = None


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _aggregate(scores: list[QuestionScore]) -> dict[str, float]:
    """None を含む指標は集計から落とす (Ragas 未導入時)。"""
    out: dict[str, float] = {}
    for key, _label in _METRIC_ORDER:
        values = [
            getattr(s, key) for s in scores if getattr(s, key, None) is not None
        ]
        if values:
            out[key] = _mean(values)
    return out


def summarize(
    *,
    condition_id: str,
    overrides: dict[str, Any],
    scores: list[QuestionScore],
    elapsed_s: float,
    failed_reason: str | None = None,
) -> ConditionSummary:
    by_kind: dict[str, dict[str, float]] = {}
    for kind in sorted({s.kind for s in scores}):
        by_kind[kind] = _aggregate([s for s in scores if s.kind == kind])

    return ConditionSummary(
        condition_id=condition_id,
        overrides=dict(overrides),
        overall=_aggregate(scores),
        by_kind=by_kind,
        elapsed_s=elapsed_s,
        failed_reason=failed_reason,
    )


def _fmt_overrides(overrides: dict[str, Any]) -> str:
    return ", ".join(f"{k}={overrides[k]}" for k in sorted(overrides))


def _fmt_cell(
    summary: ConditionSummary, baseline: ConditionSummary | None, key: str
) -> str:
    if key not in summary.overall:
        return "—"
    value = summary.overall[key]
    if baseline is None or summary.condition_id == baseline.condition_id:
        return f"{value:.3f}"
    if key not in baseline.overall:
        return f"{value:.3f}"
    delta = value - baseline.overall[key]
    return f"{value:.3f} ({delta:+.3f})"


def render_report(
    summaries: list[ConditionSummary], *, sweep_name: str, baseline_id: str
) -> str:
    baseline = next(
        (s for s in summaries if s.condition_id == baseline_id), None
    )
    ok = [s for s in summaries if s.failed_reason is None]
    failed = [s for s in summaries if s.failed_reason is not None]

    lines: list[str] = [f"# 検索精度スイープ結果: {sweep_name}", ""]
    lines += [
        f"- 条件数: {len(summaries)} (成功 {len(ok)} / 失敗 {len(failed)})",
        f"- baseline 条件: `{baseline_id}`",
        "- 括弧内は baseline との差分。主指標は ctx recall (取りこぼしの少なさ)。",
        "",
        "## 全体",
        "",
    ]

    header = ["条件", "設定"] + [label for _k, label in _METRIC_ORDER] + ["秒"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))

    for s in ok:
        mark = " (baseline)" if s.condition_id == baseline_id else ""
        row = [
            f"`{s.condition_id}`{mark}",
            _fmt_overrides(s.overrides),
            *[_fmt_cell(s, baseline, key) for key, _label in _METRIC_ORDER],
            f"{s.elapsed_s:.1f}",
        ]
        lines.append("| " + " | ".join(row) + " |")

    lines += ["", "## kind 別 (text / table / figure)", ""]
    kinds = sorted({k for s in ok for k in s.by_kind})
    if not kinds:
        lines.append("(内訳なし)")
    else:
        kind_header = ["条件", "kind"] + [label for _k, label in _METRIC_ORDER]
        lines.append("| " + " | ".join(kind_header) + " |")
        lines.append("|" + "---|" * len(kind_header))
        for s in ok:
            for kind in kinds:
                metrics = s.by_kind.get(kind)
                if not metrics:
                    continue
                row = [f"`{s.condition_id}`", kind] + [
                    f"{metrics[key]:.3f}" if key in metrics else "—"
                    for key, _label in _METRIC_ORDER
                ]
                lines.append("| " + " | ".join(row) + " |")

    if failed:
        lines += ["", "## 失敗した条件", ""]
        lines.append("| 条件 | 設定 | 理由 |")
        lines.append("|---|---|---|")
        for s in failed:
            lines.append(
                f"| `{s.condition_id}` | {_fmt_overrides(s.overrides)} "
                f"| {s.failed_reason} |"
            )

    return "\n".join(lines) + "\n"

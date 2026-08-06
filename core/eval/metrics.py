"""検索精度メトリクス。

自前指標 (recall@k / MRR) は Ragas と独立に動き、Ragas 側の閾値設定ミスで
全条件が同スコアに潰れた場合の切り分けに使う (spec §6)。
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from core.logging import get_logger

# 文字列類似度の既定閾値。全モジュールでこの値を共有する。
DEFAULT_THRESHOLD = 0.6

log = get_logger("eval.metrics")


def _normalize(text: str) -> str:
    """空白の揺れを吸収する。改行・全角空白・連続空白を単一空白に潰す。"""
    return " ".join(text.replace("　", " ").split())


def matches(
    retrieved: str, reference: str, *, threshold: float = DEFAULT_THRESHOLD
) -> bool:
    """検索結果チャンクが正解チャンクと同一とみなせるか。"""
    a, b = _normalize(retrieved), _normalize(reference)
    if not a or not b:
        return False
    if a == b:
        return True
    # 正解チャンクが検索結果の一部として含まれる場合も一致とみなす
    # (チャンク境界のずれで前後に余分な文が付くケース)。
    if b in a or a in b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= threshold


def recall_at_k(
    retrieved: list[str],
    reference: list[str],
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> float:
    """正解チャンクのうち、検索結果に現れた割合。"""
    if not retrieved or not reference:
        return 0.0

    hit = sum(
        1
        for ref in reference
        if any(matches(r, ref, threshold=threshold) for r in retrieved)
    )
    return hit / len(reference)


def mrr(
    retrieved: list[str],
    reference: list[str],
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> float:
    """最初に正解が現れた順位の逆数。どの正解でもよい。"""
    if not retrieved or not reference:
        return 0.0

    for rank, r in enumerate(retrieved, 1):
        if any(matches(r, ref, threshold=threshold) for ref in reference):
            return 1.0 / rank
    return 0.0


@dataclass(frozen=True)
class QuestionScore:
    id: str
    kind: str
    recall_at_k: float
    mrr: float
    # Ragas 未導入、または Ragas 側が失敗した場合は None。
    context_recall: float | None = None
    context_precision: float | None = None


def ragas_available() -> bool:
    """ragas (eval extra) が導入されているか。"""
    try:
        import ragas  # noqa: F401
    except ImportError:
        return False
    return True


def score_question(
    *,
    id: str,
    kind: str,
    retrieved: list[str],
    reference: list[str],
    use_ragas: bool = True,
    threshold: float = DEFAULT_THRESHOLD,
) -> QuestionScore:
    own_recall = recall_at_k(retrieved, reference, threshold=threshold)
    own_mrr = mrr(retrieved, reference, threshold=threshold)

    ctx_recall: float | None = None
    ctx_precision: float | None = None
    if use_ragas and ragas_available():
        ctx_recall, ctx_precision = _ragas_scores(retrieved, reference)

    return QuestionScore(
        id=id,
        kind=kind,
        recall_at_k=own_recall,
        mrr=own_mrr,
        context_recall=ctx_recall,
        context_precision=ctx_precision,
    )


def _ragas_scores(
    retrieved: list[str], reference: list[str]
) -> tuple[float | None, float | None]:
    """Ragas の non-LLM メトリクスを1問分だけ実行する。

    Ragas は judge LLM を使わない実装 (NonLLM*) のみを使うため、同期呼び出しで
    完結する。バージョン差でシグネチャが変わる可能性があるため、失敗しても
    None を返して自前指標だけで続行する (スイープ全体を落とさない)。
    """
    # 検索が1件も引けなかった場合。Ragas の NonLLM メトリクスは空の
    # retrieved_contexts に対して `max() iterable argument is empty` で落ちるが、
    # これは「値が定義されていない」のではなく単に未定義入力でクラッシュして
    # いるだけ。1件も引けていない = 正解を1件も含んでいない のだから、
    # context recall も precision も 0.0 が正しい (他の解釈はない)。
    # 例外に任せると None (欠測) になり、最も成績の悪い条件だけが主指標の平均から
    # 抜けて壊れた設定が良く見える。自前指標 recall_at_k / mrr が空入力で 0.0 を
    # 返すのとも揃える (同一モジュール内で扱いを割らない)。
    # reference が空のケースは golden set 読み込み時に GoldenSetError で弾かれる。
    if not retrieved:
        return 0.0, 0.0

    import asyncio
    import concurrent.futures
    import warnings

    from ragas.dataset_schema import SingleTurnSample

    # ragas.metrics からの import は v1.0 で削除予定の DeprecationWarning を出すが、
    # 代替の ragas.metrics.collections には NonLLM 系 (judge LLM 不使用版) が
    # 存在しない (LLM ベースの ContextRecall/ContextPrecision のみ)。他に選択肢が
    # ないため、この import 一箇所に限定して警告を握りつぶす。
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from ragas.metrics import (
            NonLLMContextPrecisionWithReference,
            NonLLMContextRecall,
        )

    sample = SingleTurnSample(
        retrieved_contexts=list(retrieved),
        reference_contexts=list(reference),
    )

    async def _run() -> tuple[float, float]:
        recall = await NonLLMContextRecall().single_turn_ascore(sample)
        precision = await NonLLMContextPrecisionWithReference().single_turn_ascore(
            sample
        )
        return float(recall), float(precision)

    try:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # 同期文脈。素直に自前のループを立てて回す。
            return asyncio.run(_run())
        # すでにイベントループの中。CLI の `_render` は async な `_amain` から
        # 同期呼び出しされるため、この経路が実運用の既定になる。ここで
        # asyncio.run() を呼ぶと RuntimeError になり、下の except が握って
        # 主指標が丸ごと欠測する (レポートの ctx recall 列が全条件 `—`)。
        # 呼び出し側を async 化すると同期の呼び出し元が壊れるので、
        # ワーカースレッド上で新しいループを立てて完了を待つ。
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(_run())).result()
    except Exception as exc:  # noqa: BLE001 — Ragas の例外型に依存しない
        log.warning("ragas_metric_failed", error=str(exc))
        return None, None

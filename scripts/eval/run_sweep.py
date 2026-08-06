"""検索精度スイープの実行 CLI。

spec: docs/specs/2026-08-07-ragas-retrieval-eval-design.md

使い方:
    uv run --no-sync python scripts/eval/run_sweep.py \
        --matrix scripts/eval/example-matrix.yaml \
        --out docs/eval/retrieval

前提:
    - 評価コーパスが notebook_id のノートブックに取り込み済みであること
    - 視覚索引 (page / tile) が baseline の格子で構築済みであること
    - 専用 data_dir を NOTEBOOK_OLLAMA_DATA_DIR で指定していること (本番に触らない)
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any

# リポジトリルートを import パスに載せる (scripts/ から core/ を読むため)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.eval import goldenset, matrix, metrics, report, runner  # noqa: E402
from core.logging import get_logger  # noqa: E402

log = get_logger("eval.cli")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="検索精度スイープを実行する")
    p.add_argument("--matrix", required=True, type=Path, help="matrix.yaml のパス")
    p.add_argument(
        "--out",
        type=Path,
        default=Path("docs/eval/retrieval"),
        help="結果の出力先ディレクトリ (既定: docs/eval/retrieval)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="条件を展開して表示するだけで、検索は実行しない",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="確認プロンプトを出さない",
    )
    p.add_argument(
        "--no-ragas",
        action="store_true",
        help="Ragas を使わず自前指標だけで採点する",
    )
    return p.parse_args(argv)


def _confirm(prompt: str) -> bool:
    answer = input(f"{prompt} [y/N]: ").strip().lower()
    return answer in ("y", "yes")


async def _amain(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    spec = matrix.load_sweep(args.matrix)
    conditions = matrix.expand(spec)
    search_only, reindex = matrix.partition(conditions)

    print(f"スイープ: {spec.name}")
    print(f"条件数: {len(conditions)} (検索時のみ {len(search_only)} / 再索引要 {len(reindex)})")
    for c in conditions:
        mark = "[再索引]" if c.requires_reindex else "          "
        print(f"  {mark} {c.id}  {c.overrides}")

    if args.dry_run:
        return 0

    if reindex:
        # 再インデックス対応は未実装。実測で約95秒/ページかかるため、
        # 無自覚に走らせると数時間拘束される (spec Global Constraints)。
        print(
            f"\nエラー: 再インデックスが必要な条件が {len(reindex)} 件あります "
            f"(索引構築 {matrix.reindex_count(conditions)} 回相当)。",
            file=sys.stderr,
        )
        print(
            "現状の CLI は検索時パラメータのみを対象にしています。"
            "tile_rows / tile_cols / tile_overlap / embedding_model を axes から外すか、"
            "その値で索引を手動構築してから baseline に設定してください。",
            file=sys.stderr,
        )
        return 2

    golden = goldenset.load_golden(Path(spec.golden))
    print(f"golden set: {len(golden)} 問")

    out_dir = Path(args.out) / f"{date.today().isoformat()}-{spec.name}"
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"

    done = runner.completed_condition_ids(results_path)
    if done:
        print(f"再開: {len(done)} 件の条件は実行済みのためスキップします")

    harness = _EvalHarness(notebook_id=spec.notebook_id)
    # data_dir は本番と分離しているか目視できるよう、確認前に必ず出す。
    print(f"data_dir: {harness.data_dir}")

    if not args.yes and not _confirm(f"{len(conditions) - len(done)} 条件を実行しますか"):
        print("中止しました")
        harness.close()
        return 1

    # 実行時の設定スナップショットを残す (spec §7)
    shutil.copyfile(args.matrix, out_dir / "matrix.yaml")

    try:
        await runner.run_sweep(
            conditions=conditions,
            golden=golden,
            search=harness.search,
            results_path=results_path,
        )
    finally:
        harness.close()

    md = _render(results_path, conditions, spec, use_ragas=not args.no_ragas)
    (out_dir / "report.md").write_text(md, encoding="utf-8")
    print(f"\n完了: {out_dir / 'report.md'}")
    return 0


def _render(results_path, conditions, spec, *, use_ragas: bool) -> str:
    import json

    rows = [
        json.loads(line)
        for line in results_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    markers = {r["condition_id"]: r for r in rows if r["type"] == "condition"}

    summaries = []
    for c in conditions:
        marker = markers.get(c.id)
        if marker is None:
            continue
        scores = [
            metrics.score_question(
                id=r["question_id"],
                kind=r["kind"],
                retrieved=r["retrieved_contexts"],
                reference=r["reference_contexts"],
                use_ragas=use_ragas,
            )
            for r in rows
            if r["type"] == "question" and r["condition_id"] == c.id
        ]
        summaries.append(
            report.summarize(
                condition_id=c.id,
                overrides=c.overrides,
                scores=scores,
                elapsed_s=marker["elapsed_s"],
                failed_reason=marker["failed_reason"],
            )
        )

    return report.render_report(
        summaries,
        sweep_name=spec.name,
        baseline_id=matrix.condition_id(spec.baseline),
    )


class _EvalHarness:
    """評価専用に組み立てた RetrievalService と、その条件切替。

    `apps/api/dependencies.py::build_context` の検索まわりの配線を**再現**した
    もの。共有化ではなく複製なのは意図的で、評価ハーネスが本番配線の変更を
    妨げないようにするため (Global Constraints: dependencies.py は改変しない)。

    RetrievalService と VisualSearchDeps は設定値を getter (Callable) で
    受け取るため、サービスは1回だけ組み立て、可変セル ``_current`` を
    差し替えるだけで条件を切り替えられる。
    """

    def __init__(self, *, notebook_id: str) -> None:
        from core.config import AppConfig
        from core.feature_service import FeatureService
        from core.ollama.client import OllamaClient
        from core.ollama.gateway import OllamaGateway
        from core.retrieval.search import RetrievalService, VisualSearchDeps
        from core.settings_store import apply_overrides
        from core.storage.database import connect, migrate
        from core.storage.vector_store import VectorStore
        from core.storage.visual_index_repo import get_meta as visual_get_meta
        from core.storage.visual_store import VisualUnitStore
        from core.visual.encoder import TransformersVisualEncoder, visual_extra_available

        # main.py の lifespan と同じ順序: 環境変数で AppConfig を作り、
        # settings.json の上書きを適用する。
        config = AppConfig()
        apply_overrides(config)
        config.ensure_dirs()
        self._notebook_id = notebook_id
        self.data_dir = config.data_dir
        self._current: dict[str, Any] = {}

        self._conn = connect(config.metadata_db_path)
        migrate(self._conn)
        self._vs = VectorStore(path=config.qdrant_path, dim=_resolve_embedding_dim(config))
        self._vs.ensure_collection()

        # 埋め込み用ゲートウェイ。build_context は BackendPlanner/BackendFactory
        # 経由で選ぶが、評価で使うのはクエリ埋め込み (gateway.embed) だけなので、
        # 既定プラン (ollama-cuda) が組み立てるのと同じ構成を直接作る
        # (BackendFactory._build_ollama_gateway と同じ引数)。
        gateway = OllamaGateway(
            client=OllamaClient(
                endpoint=config.ollama.endpoint,
                timeout=config.ollama.request_timeout_seconds,
                chat_read_timeout=config.ollama.chat_read_timeout_seconds,
            ),
            embedding_options=config.ollama.embedding_options or None,
        )

        features = FeatureService(config.data_dir)
        if not features.is_enabled("table-figure-rag"):
            # 本番配線はこのフラグで図表・視覚検索を丸ごと落とす。気付かずに
            # 走らせると「全条件が同じテキスト検索」という無意味な結果が出る。
            print(
                "警告: feature flag 'table-figure-rag' が OFF です。"
                "視覚検索が無効化され、条件差が出ません。",
                file=sys.stderr,
            )

        visual_stores = {
            "page": VisualUnitStore(client=self._vs.client, unit="page"),
            "tile": VisualUnitStore(client=self._vs.client, unit="tile"),
        }
        encoder = (
            TransformersVisualEncoder(
                model_name=config.visual.embedding_model,
                idle_unload_seconds=config.visual.idle_unload_seconds,
                cpu_threads=config.visual.cpu_threads,
                prefer_performance_cores=config.visual.cpu_prefer_performance_cores,
            )
            if visual_extra_available()
            else None
        )
        if encoder is None:
            print(
                "警告: visual extra が未導入のため視覚検索は実行されません "
                "(uv sync --extra visual)。",
                file=sys.stderr,
            )

        current = self._current
        base = config.visual
        self._service = RetrievalService(
            conn=self._conn,
            vector_store=self._vs,
            ollama=gateway,
            embedding_model=config.ollama.embedding_model,
            embedding_model_getter=lambda: config.ollama.embedding_model,
            figure_desc_enabled=lambda: features.is_enabled("table-figure-rag"),
            visual=VisualSearchDeps(
                stores=visual_stores,
                encoder=encoder,
                enabled=lambda: (
                    config.visual.search_enabled
                    and encoder is not None
                    and features.is_enabled("table-figure-rag")
                ),
                meta_lookup=lambda nb_id, unit: visual_get_meta(self._conn, nb_id, unit),
                # 埋め込みモデルは索引側と一致していなければならないため、
                # 条件では振らない (振ると再索引が要る = CLI が拒否する)。
                model_name_getter=lambda: config.visual.embedding_model,
                unit_getter=lambda: str(current.get("index_unit", base.index_unit)),
                # 本番の _effective_strategy と違いベータOFFでの丸めは行わない。
                # 評価では matrix に書いた戦略がそのまま走ることが要件。
                strategy_getter=lambda: str(
                    current.get("search_strategy", base.search_strategy)
                ),
                tile_grid_getter=lambda: (
                    int(current.get("tile_rows", base.tile_rows)),
                    int(current.get("tile_cols", base.tile_cols)),
                ),
                max_images_getter=lambda: int(current.get("max_images", base.max_images)),
            ),
        )

    async def search(self, *, condition, item) -> list[str]:
        self._current.clear()
        self._current.update(condition.overrides)
        hits = await self._service.search(
            notebook_id=self._notebook_id,
            query=item.question,
            limit=int(condition.overrides["top_k"]),
        )
        return [h.text for h in hits]

    def close(self) -> None:
        self._vs.close()
        self._conn.close()


def _resolve_embedding_dim(config) -> int:
    """既存 collection の次元を採用する (dependencies.py の同名処理の再現)。

    評価は構築済み索引を前提にするので、通常は 1 で既存次元が取れる。
    取れないときだけ settings.json / 既定値へ落ちる。
    """
    from core.settings_store import load_overrides
    from core.storage.vector_store import VectorStore

    probe = VectorStore(path=config.qdrant_path, dim=1024)
    try:
        existing = probe.collection_dim()
    finally:
        probe.close()
    if existing is not None:
        return existing
    ollama_ov = load_overrides(config.data_dir).get("ollama")
    if isinstance(ollama_ov, dict):
        dim = ollama_ov.get("embedding_dim")
        if isinstance(dim, int) and dim > 0:
            return dim
    return 1024


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_amain()))

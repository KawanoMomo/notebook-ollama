"""golden set の半自動生成 CLI。

spec: docs/specs/2026-08-07-ragas-retrieval-eval-design.md §2.4 / §5.1

Ragas の testset generator で候補を作り、対話的に採否をレビューして確定する。
ローカルLLMが生成した正解は誤りうるので、人手ゲートを必ず通す。

使い方:
    NOTEBOOK_OLLAMA_DATA_DIR=./data/eval/workdir uv run --no-sync python \\
        scripts/eval/build_goldenset.py \\
        --notebook-id eval-notebook --count 20 --out data/eval/golden.jsonl
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.eval.goldenset import (  # noqa: E402
    VALID_KINDS,
    GoldenItem,
    dump_golden,
    load_golden,
)

# Ragas のナレッジグラフ構築は 1 チャンクあたり数十秒かかる (実測)。候補数と
# 同数だけ渡しても足りないことがあるので少し多めに、ただし青天井にはしない。
_MIN_SAMPLE_CHUNKS = 8


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="golden set を半自動生成する")
    p.add_argument("--notebook-id", required=True, help="取り込み済みノートブックID")
    p.add_argument("--count", type=int, default=40, help="生成する候補数 (既定 40)")
    p.add_argument("--out", required=True, type=Path, help="出力先 jsonl")
    p.add_argument(
        "--resume",
        action="store_true",
        help="既存の出力ファイルに追記する (途中から再開)",
    )
    p.add_argument(
        "--manual",
        action="store_true",
        help="Ragas を使わず、チャンクを提示して質問を人が入力する半手動モード",
    )
    p.add_argument(
        "--llm-model",
        default=None,
        help="候補生成に使う Ollama モデル (既定: 設定の default_model)",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="チャンクサンプリングの乱数シード (再現用)",
    )
    p.add_argument(
        "--allow-production-data-dir",
        action="store_true",
        help="本番 data_dir での実行を許可する (既定は停止。通常は使わない)",
    )
    return p.parse_args(argv)


# --- 設定と本番データ保護 ----------------------------------------------------
# run_sweep.py と同じガード。この CLI も同じ SQLite を開くため、環境変数の
# 設定忘れで本番データを触らないよう既定を「停止」にする。


def _load_eval_config():
    """main.py の lifespan と同じ順序で設定を解決する (ディスクは触らない)。"""
    from core.config import AppConfig
    from core.settings_store import apply_overrides

    config = AppConfig()
    apply_overrides(config)
    return config


def _default_data_dir() -> Path:
    """環境変数が未指定のときに AppConfig が使う data_dir (= 本番)。

    リテラルを書き写すと core/config.py の変更で静かにズレるため、
    pydantic のフィールド定義から default_factory を引く。
    """
    from core.config import AppConfig

    factory = AppConfig.model_fields["data_dir"].default_factory
    return Path(factory())


def _check_data_dir(config, *, args) -> str | None:
    if args.allow_production_data_dir:
        return None
    if Path(config.data_dir).resolve() != _default_data_dir().resolve():
        return None
    return (
        f"本番の data_dir ({config.data_dir}) で golden set を作ろうとしています。\n"
        "評価は本番データに触れてはいけません。\n"
        "専用の data_dir を環境変数で指定してください:\n"
        "    NOTEBOOK_OLLAMA_DATA_DIR=./data/eval/workdir uv run --no-sync python "
        "scripts/eval/build_goldenset.py --notebook-id <id> --out <path>\n"
        "(PowerShell: $env:NOTEBOOK_OLLAMA_DATA_DIR = './data/eval/workdir')\n"
        "本当に本番 data_dir で走らせる場合のみ --allow-production-data-dir を付けること。"
    )


# --- チャンクの取得 ----------------------------------------------------------


@dataclass(frozen=True)
class _Chunk:
    """候補生成に必要な最小限だけを持つ、チャンクの読み出し結果。"""

    text: str
    page: int | None


def _load_chunks(config, notebook_id: str) -> list[_Chunk]:
    """取り込み済みノートブックのチャンク本文を読み出す (読み取り専用)。"""
    from core.storage.chunks_repo import list_chunks_for_source
    from core.storage.database import connect
    from core.storage.sources_repo import list_sources

    db_path = Path(config.metadata_db_path)
    if not db_path.exists():
        # この CLI は読み取り専用。migrate して空DBを作っても意味が無いので、
        # 「取り込みが済んでいない」ことを明示して止める。
        raise SystemExit(
            f"メタデータDBがありません: {db_path}\n"
            "評価コーパスをこの data_dir のノートブックへ先に取り込んでください。"
        )

    conn = connect(db_path)
    try:
        sources = list_sources(conn, notebook_id=notebook_id)
        chunks: list[_Chunk] = []
        for src in sources:
            for rec in list_chunks_for_source(conn, src.id):
                if rec.text.strip():
                    chunks.append(_Chunk(text=rec.text, page=rec.page))
        return chunks
    finally:
        conn.close()


def _index_by_text(chunks: list[_Chunk]) -> dict[str, _Chunk]:
    return {c.text: c for c in chunks}


# --- 候補生成 ----------------------------------------------------------------


def _generate_candidates(
    notebook_id: str,
    count: int,
    *,
    config,
    manual: bool,
    llm_model: str | None,
    rng: random.Random,
) -> list[dict]:
    """Q&A 候補を作る。

    既定は Ragas の testset generator (ローカル Ollama を LangChain 経由で
    ラップして渡す)。``manual`` を指定した場合は質問生成を行わず、チャンク
    本文だけを提示して人が質問を書く。どちらでも採否の人手レビューは通る。
    """
    chunks = _load_chunks(config, notebook_id)
    if not chunks:
        raise SystemExit(
            f"ノートブック {notebook_id!r} に取り込み済みチャンクがありません。"
            f" data_dir: {config.data_dir}"
        )

    sample_size = min(len(chunks), max(count, _MIN_SAMPLE_CHUNKS))
    sampled = rng.sample(chunks, sample_size)
    print(f"チャンク {len(chunks)} 件中 {sample_size} 件をサンプリングしました")

    if manual:
        return [
            {"question": None, "reference_contexts": [c.text], "page_no": c.page}
            for c in sampled[:count]
        ]
    return _generate_with_ragas(sampled, count, config=config, llm_model=llm_model)


def _generate_with_ragas(
    sampled: list[_Chunk], count: int, *, config, llm_model: str | None
) -> list[dict]:
    """Ragas の TestsetGenerator に生チャンクを渡して質問を作らせる。

    Ragas 側の LLM/埋め込みは自前のインターフェース型を要求するため、
    langchain-community の Ollama ラッパー (eval extra で導入済み) を挟む。
    本体の core/ollama は使わない — 評価専用の一時経路を本番配線に混ぜない。
    """
    from langchain_community.chat_models import ChatOllama
    from langchain_community.embeddings import OllamaEmbeddings
    from ragas.testset import TestsetGenerator

    model = llm_model or config.ollama.default_model
    print(
        f"Ragas で候補を生成します (LLM: {model} / 埋め込み: "
        f"{config.ollama.embedding_model})。"
        "ナレッジグラフ構築に数十秒/チャンクかかります"
    )

    generator = TestsetGenerator.from_langchain(
        ChatOllama(model=model, base_url=config.ollama.endpoint, temperature=0.0),
        OllamaEmbeddings(
            model=config.ollama.embedding_model, base_url=config.ollama.endpoint
        ),
    )
    testset = generator.generate_with_chunks(
        [c.text for c in sampled], testset_size=count
    )

    by_text = _index_by_text(sampled)
    candidates: list[dict] = []
    for sample in testset.samples:
        contexts = [str(c) for c in (sample.eval_sample.reference_contexts or [])]
        if not contexts:
            # 根拠が取れない候補は採点に使えない (reference_contexts が必須)。
            continue
        origin = by_text.get(contexts[0])
        candidates.append(
            {
                "question": str(sample.eval_sample.user_input),
                "reference_contexts": contexts,
                "page_no": origin.page if origin else None,
            }
        )
    return candidates


# --- 対話レビュー ------------------------------------------------------------


def _prompt_kind() -> str:
    options = sorted(VALID_KINDS)
    while True:
        raw = input(f"  kind {options} > ").strip()
        if raw in VALID_KINDS:
            return raw
        print(f"  {options} のいずれかを入力してください")


def _review(candidates: list[dict]) -> list[GoldenItem]:
    """候補を1件ずつ提示して採否を取る。Ctrl-C で打ち切っても採用分は残す。"""
    accepted: list[GoldenItem] = []

    for i, cand in enumerate(candidates, 1):
        print(f"\n--- 候補 {i}/{len(candidates)} ---")
        for ctx in cand["reference_contexts"]:
            preview = ctx if len(ctx) <= 300 else ctx[:300] + "…"
            print(f"正解: {preview}")
        print(f"ページ: {cand.get('page_no')}")

        try:
            question = cand.get("question")
            if question is None:
                # 半手動モード: 質問は人が書く。空入力はその候補の見送り。
                question = input("この本文に対する質問 (空でスキップ): ").strip()
                if not question:
                    continue
                answer = "y"
            else:
                print(f"質問: {question}")
                answer = input("採用しますか [y/N/q]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\n中断しました")
            break

        if answer == "q":
            break
        if answer not in ("y", "yes"):
            continue

        try:
            kind = _prompt_kind()
        except (KeyboardInterrupt, EOFError):
            print("\n中断しました")
            break

        accepted.append(
            GoldenItem(
                id=f"q{len(accepted) + 1:03d}",
                question=question,
                reference_contexts=cand["reference_contexts"],
                kind=kind,
                page_no=cand.get("page_no"),
            )
        )

    return accepted


def _force_utf8_output() -> None:
    """出力を UTF-8 に固定する。

    Windows の既定コンソール encoding (cp932) だと日本語チャンク本文の表示で
    文字化け・UnicodeEncodeError が起きる。レビューは本文を読んで判断する
    作業なので、読めないと成立しない。--help もここを通す必要がある。
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    args = _parse_args(argv)

    config = _load_eval_config()
    print(f"data_dir: {config.data_dir}")

    message = _check_data_dir(config, args=args)
    if message is not None:
        print(f"\nエラー: {message}", file=sys.stderr)
        return 2

    existing: list[GoldenItem] = []
    if args.resume and args.out.exists():
        existing = load_golden(args.out)
        print(f"既存 {len(existing)} 問を読み込みました")

    print(f"候補を {args.count} 件生成しています...")
    candidates = _generate_candidates(
        args.notebook_id,
        args.count,
        config=config,
        manual=args.manual,
        llm_model=args.llm_model,
        # 候補チャンクの抽出であって暗号用途ではない (再現性のため seed 可)
        rng=random.Random(args.seed),  # noqa: S311
    )
    if not candidates:
        print("候補が生成されませんでした", file=sys.stderr)
        return 1

    accepted = _review(candidates)
    if not accepted:
        print("採用された候補がありません。何も書き込みません")
        return 1

    # id を通し番号で振り直す (既存分の後ろに続ける)
    merged = existing + [
        GoldenItem(
            id=f"q{len(existing) + i + 1:03d}",
            question=a.question,
            reference_contexts=a.reference_contexts,
            kind=a.kind,
            page_no=a.page_no,
        )
        for i, a in enumerate(accepted)
    ]

    dump_golden(merged, args.out)
    by_kind: dict[str, int] = {}
    for item in merged:
        by_kind[item.kind] = by_kind.get(item.kind, 0) + 1
    print(f"\n{args.out} に {len(merged)} 問を書き込みました")
    print(f"kind 別: {by_kind}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

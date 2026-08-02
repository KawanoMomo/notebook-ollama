"""Obsidian ナレッジ層 (frontmatter / MOC / Canvas / 実装マップ) の鮮度を検査する。

索引が実体からずれると、LLM は古い情報を読んで誤った前提で作業する。
その腐敗を機械で検出するのが目的。CI や doc 追加時に実行する。

    uv run python scripts/check_design_index.py

異常があれば終了コード 1。
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIRED = ("type", "title", "summary", "status", "date", "area")

# Windows の既定コンソールは cp932 で、この検査が出す ❌ や設計書タイトルを
# エンコードできずに落ちる(検査結果ではなく検査自体が失敗する)。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
STATUS_VOCAB = {"draft", "review", "approved", "planned", "deferred", "proposed"}


def fm_of(path: str) -> tuple[str, str]:
    text = open(path, encoding="utf-8").read()
    if not text.startswith("---"):
        return "", text
    parts = text.split("---", 2)
    return parts[1], parts[2]


def get(fm: str, key: str) -> str:
    m = re.search(rf"^{key}:\s*(.*)$", fm, re.M)
    return m.group(1).strip().strip('"') if m else ""


def listed(fm: str, key: str) -> list[str]:
    m = re.search(rf"^{key}:\s*\n((?:  - .*\n?)+)", fm, re.M)
    return [ln.strip()[2:].strip() for ln in m.group(1).strip().split("\n")] if m else []


def main() -> int:
    problems: list[str] = []
    docs = {}

    paths = sorted(glob.glob(os.path.join(ROOT, "docs/specs/*.md"))
                   + glob.glob(os.path.join(ROOT, "docs/adr/*.md"))
                   + glob.glob(os.path.join(ROOT, "docs/adr/drafts/*.md")))
    for path in paths:
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        name = os.path.basename(path)[:-3]
        fm, _ = fm_of(path)
        if not fm:
            problems.append(f"[frontmatter無し] {rel}")
            continue
        for key in REQUIRED:
            if not get(fm, key):
                problems.append(f"[{key} 未設定] {rel}")
        status = get(fm, "status")
        if status and status not in STATUS_VOCAB:
            problems.append(f"[status 語彙外 '{status}'] {rel}")
        docs[name] = {"rel": rel, "fm": fm, "type": get(fm, "type")}

    # frontmatter 中のウィキリンクのリンク切れ (related に限らず summary 等も見る)
    for name, doc in docs.items():
        # Obsidian はコードスパン内をリンク化しない。TOML の [[tool.uv.index]] のように
        # ウィキリンクと同形の記法を誤検出しないよう、走査前に `...` を落とす。
        scannable = re.sub(r"`[^`\n]*`", "", doc["fm"])
        for target in re.findall(r"\[\[([^\]|#]+)", scannable):
            t = target.strip()
            if t in docs or os.path.exists(os.path.join(ROOT, "docs/specs", t)):
                continue
            if t.endswith(".html") or t.endswith(".base") or t.endswith(".canvas"):
                continue
            problems.append(f"[リンク切れ '{t}'] {doc['rel']}")

    # code: の指すパスが実在するか
    for name, doc in docs.items():
        for p in listed(doc["fm"], "code"):
            if not os.path.exists(os.path.join(ROOT, p)):
                problems.append(f"[code パス消滅 '{p}'] {doc['rel']}")

    # MOC の網羅
    moc_path = os.path.join(ROOT, "docs/設計資産MOC.md")
    if os.path.exists(moc_path):
        moc = open(moc_path, encoding="utf-8").read()
        for name in docs:
            if name not in moc:
                problems.append(f"[MOC 未掲載] {docs[name]['rel']}")
    else:
        problems.append("[欠落] docs/設計資産MOC.md")

    # Canvas の網羅と参照切れ
    canvas_path = os.path.join(ROOT, "docs/設計資産.canvas")
    if os.path.exists(canvas_path):
        canvas = json.load(open(canvas_path, encoding="utf-8"))
        files = [n for n in canvas["nodes"] if n["type"] == "file"]
        included = {os.path.basename(n["file"])[:-3] for n in files}
        for name in docs:
            if name not in included:
                problems.append(f"[Canvas 未収録] {docs[name]['rel']} "
                                f"→ uv run python scripts/gen_design_canvas.py")
        for n in files:
            if not os.path.exists(os.path.join(ROOT, n["file"])):
                problems.append(f"[Canvas 参照切れ] {n['file']}")
    else:
        problems.append("[欠落] docs/設計資産.canvas")

    # 実装マップの存在
    if not os.path.exists(os.path.join(ROOT, "docs/実装マップ.md")):
        problems.append("[欠落] docs/実装マップ.md "
                        "→ uv run python scripts/gen_code_map.py")

    # どの spec にも紐付いていない core モジュール (情報として報告)
    mapped = {p for d in docs.values() for p in listed(d["fm"], "code")}
    orphan_modules = []
    for mod in sorted(glob.glob(os.path.join(ROOT, "core/*/"))):
        name = "core/" + os.path.basename(mod.rstrip("/\\"))
        if name.endswith("__pycache__"):
            continue
        if not any(m == name or m.startswith(name + "/") for m in mapped):
            orphan_modules.append(name)

    print(f"検査: 設計書 {len(docs)} 本")
    if orphan_modules:
        print("\n[情報] どの設計書にも紐付いていない core モジュール "
              "(設計書本文にパスを書けば実装マップに載る):")
        for m in orphan_modules:
            print("   -", m)
    if problems:
        print(f"\n❌ 問題 {len(problems)} 件:")
        for p in problems:
            print("   -", p)
        return 1
    print("\n✅ 索引は最新 (frontmatter / MOC / Canvas / 実装マップ すべて整合)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

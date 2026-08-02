"""設計書の本文から実在するコードパスを抽出し、

  1. 各 spec の frontmatter に `code:` を書き込む (doc → コード)
  2. `docs/実装マップ.md` を生成する (コード → doc の逆引き)

「どのコードがどの設計書に規定されているか」を vault 側に永続化するのが目的。
実装箇所を探すとき、毎回 Grep する代わりにこのマップを引けるようにする。

抽出は**本文が実際に言及し、かつリポジトリに実在するパスだけ**を対象にする
(推測で紐付けない)。未実装の spec は `code:` が空のままになり、それ自体が
「まだ実装されていない」というシグナルになる。

    uv run python scripts/gen_code_map.py
"""

from __future__ import annotations

import glob
import os
import re
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_OUT = os.path.join(ROOT, "docs", "実装マップ.md")

PATH_RE = re.compile(r"((?:core|apps/api|apps/web|scripts|tests)/[A-Za-z0-9_./\-]+)")
# 抽象的すぎて逆引きの役に立たないパス
TOO_GENERIC = {"core", "apps/api", "apps/web", "scripts", "tests",
               "apps/web/src", "apps/web/src/lib", "apps/web/src/routes"}


def rel_exists(path: str) -> bool:
    return os.path.exists(os.path.join(ROOT, path))


def extract_paths(body: str) -> list[str]:
    found = set()
    for raw in PATH_RE.findall(body):
        p = raw.rstrip(".,;:)》」`*")
        p = p.rstrip("/")
        if not p or p in TOO_GENERIC:
            continue
        if rel_exists(p):
            found.add(p)
    return sorted(found)


def split_doc(text: str) -> tuple[str, str]:
    """(frontmatter, body) に分割。frontmatter が無ければ ('', text)。"""
    if not text.startswith("---"):
        return "", text
    parts = text.split("---", 2)
    return parts[1], parts[2]


def set_code_field(fm: str, paths: list[str]) -> str:
    """frontmatter の code: を置換 or 追記 (冪等)。"""
    lines = fm.split("\n")
    out, skipping = [], False
    for line in lines:
        if skipping:
            if line.startswith("  - ") or line.strip() == "":
                if line.startswith("  - "):
                    continue
            skipping = False
        if line.startswith("code:"):
            skipping = True
            continue
        out.append(line)
    while out and out[-1].strip() == "":
        out.pop()
    if paths:
        out.append("code:")
        out += [f"  - {p}" for p in paths]
    out.append("")
    return "\n".join(out)


def get(fm: str, key: str) -> str:
    m = re.search(rf"^{key}:\s*(.*)$", fm, re.M)
    return m.group(1).strip().strip('"') if m else ""


def main() -> None:
    specs = []
    for path in sorted(glob.glob(os.path.join(ROOT, "docs/specs/*.md"))):
        text = open(path, encoding="utf-8").read()
        fm, body = split_doc(text)
        if not fm:
            continue
        paths = extract_paths(body)
        new_fm = set_code_field(fm, paths)
        if new_fm != fm:
            open(path, "w", encoding="utf-8").write("---" + new_fm + "---" + body)
        specs.append({
            "name": os.path.basename(path)[:-3],
            "title": get(fm, "title"),
            "status": get(fm, "status"),
            "area": get(fm, "area"),
            "paths": paths,
        })

    # ---- 逆引き: コード -> spec ----
    owners: dict[str, list[dict]] = defaultdict(list)
    for spec in specs:
        for p in spec["paths"]:
            owners[p].append(spec)

    def bucket(path: str) -> str:
        parts = path.split("/")
        if path.startswith("core/"):
            return f"core/{parts[1]}"
        if path.startswith("apps/api/"):
            return "apps/api/" + (parts[2] if len(parts) > 3 else "")
        if path.startswith("apps/web/"):
            return "/".join(parts[:4])
        return parts[0]

    grouped: dict[str, list[str]] = defaultdict(list)
    for p in owners:
        grouped[bucket(p).rstrip("/")].append(p)

    lines = [
        "---",
        "title: 実装マップ (コード → 設計書 逆引き)",
        'summary: "コードパスから、それを規定する設計書/ADRを逆引きする索引。Grepの代わりに引く。"',
        "aliases:",
        "  - 実装マップ",
        "  - コードマップ",
        "type: index",
        "project: NotebookOllama",
        "tags:",
        "  - index",
        "  - codemap",
        "---",
        "",
        "# 🔎 実装マップ — コード → 設計書 逆引き",
        "",
        "> [!tip] 使い方",
        "> コードを触る前にこの表を引く。`core/retrieval/search.py` を変更する →"
        " 該当行の設計書を開く → その `related` から ADR を辿る。",
        "> **Grep はこの表に載っていないときの最後の手段**。",
        "> この表は `scripts/gen_code_map.py` が設計書本文から自動生成する(手編集しない)。",
        "",
        f"対象: 設計書 {len(specs)} 本 / 紐付いたコードパス {len(owners)} 件",
        "",
    ]
    for group in sorted(grouped):
        lines.append(f"## `{group}`")
        lines.append("")
        lines.append("| コードパス | 規定する設計書 |")
        lines.append("|---|---|")
        for p in sorted(grouped[group]):
            docs_cell = " ・".join(
                f"[[{s['name']}\\|{s['title'] or s['name']}]]" for s in owners[p]
            )
            lines.append(f"| `{p}` | {docs_cell} |")
        lines.append("")

    unmapped = [s for s in specs if not s["paths"]]
    if unmapped:
        lines += [
            "## 🚧 コード未紐付けの設計書",
            "",
            "本文にコードパスの言及が無い設計書。**未実装 / 計画中**の可能性が高い"
            "(実装したら本文にパスを書き、本スクリプトを再実行する)。",
            "",
        ]
        for s in sorted(unmapped, key=lambda d: d["name"]):
            lines.append(f"- [[{s['name']}|{s['title'] or s['name']}]] "
                         f"— `status: {s['status']}` / `area: {s['area']}`")
        lines.append("")

    open(MAP_OUT, "w", encoding="utf-8").write("\n".join(lines))
    print(f"wrote docs/実装マップ.md: {len(owners)} paths, "
          f"{len(specs) - len(unmapped)}/{len(specs)} specs mapped")


if __name__ == "__main__":
    main()

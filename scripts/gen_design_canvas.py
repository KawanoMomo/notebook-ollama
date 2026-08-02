"""docs/specs + docs/adr の frontmatter から docs/設計資産.canvas を生成する。

設計資産 Canvas は 3 レーン構成:
  レーンA: システム構成 (README のアーキ図。静的定義)
  レーンB: core/ モジュール & 機能クラスタ (静的定義)
  レーンC: 設計書 / ADR ドラフト (frontmatter から自動生成)

レーンC は「島 (island)」単位で並べる。1 島 = 1 つの spec + その spec から起票された
ADR ドラフト。島は area ごとの枠にまとめ、機能クラスタ順に左上から流し込む。
関連 doc が必ず隣接するため、ボードを横断する長い配線が発生しない。

読みやすさのための方針:
  - 島の中の線 (spec → ADR) だけを描く。area をまたぐ related は線を引かず、
    frontmatter の related と Obsidian のグラフビューに委ねる
  - 相互参照 (A→B かつ B→A) は 1 本にまとめる
  - 島の色 = レーンB の機能クラスタ色。凡例ノードで対応を示す

新しい spec / ADR を追加したら本スクリプトを再実行すれば Canvas が最新化される。

    uv run python scripts/gen_design_canvas.py
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "設計資産.canvas")

# area -> レーンB の機能クラスタ
AREA_TO_CLUSTER = {
    "recording": "取込",
    "ingestion": "取込",
    "youtube": "取込",
    "chat": "取込",
    "presentation": "取込",
    "rag-ux": "検索応答",
    "retrieval": "検索応答",
    "prompts": "検索応答",
    "summary": "要約",
    "model": "推論基盤",
    "accel": "推論基盤",
    "feedback": "運用",
    "dev-mode": "運用",
    "notifications": "運用",
    "foundation": "基盤",
    "platform": "基盤",
}

CLUSTERS = [
    ("取込", "2", "`ingestion`\n`recording`"),
    ("検索応答", "5", "`retrieval`\n`generation`\n`prompts`"),
    ("要約", "3", "`summary`"),
    ("推論基盤", "6", "`llm`\n`ollama`\n`accel`"),
    ("運用", "4", "`feedback_hub`\n`crash_reporter`\n`dev_logs`"),
    ("基盤", "1", "`storage`\n`mcp`\n`adr`"),
]
CLUSTER_ORDER = [c[0] for c in CLUSTERS]
CLUSTER_COLOR = {name: color for name, color, _ in CLUSTERS}

CARD_W, CARD_H = 260, 85
CARD_GAP = 12          # 島の中のカード間隔
ISLAND_GAP = 26        # 島どうしの間隔
COL_GAP = 24           # area 枠の中の列間隔
GROUP_PAD_X, GROUP_TOP, GROUP_BOT = 16, 46, 16
GROUP_GAP_X, GROUP_GAP_Y = 40, 40
MAX_COL_H = 620        # この高さを超えたら area 枠の中で列を折り返す
BOARD_MAX_W = 2500     # この幅を超えたら area 枠を次の行へ折り返す
LANE_C_Y = 900


def nid(key: str) -> str:
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:16]


def read_frontmatter(path: str) -> dict:
    text = open(path, encoding="utf-8").read()
    if not text.startswith("---"):
        return {}
    fm = text.split("---", 2)[1]
    out: dict = {}
    for key in ("type", "title", "status", "area", "date"):
        m = re.search(rf"^{key}:\s*(.*)$", fm, re.M)
        if m:
            out[key] = m.group(1).strip().strip('"')
    out["related"] = [r.strip() for r in re.findall(r"\[\[([^\]|#]+)", fm)]
    return out


def collect_docs() -> dict[str, dict]:
    docs: dict[str, dict] = {}
    for pattern in ("docs/specs/*.md", "docs/adr/*.md", "docs/adr/drafts/*.md"):
        for path in glob.glob(os.path.join(ROOT, pattern)):
            fm = read_frontmatter(path)
            if not fm.get("type"):
                continue
            fm["path"] = os.path.relpath(path, ROOT).replace("\\", "/")
            fm["name"] = os.path.basename(path)[:-3]
            docs[fm["name"]] = fm
    return docs


def build_islands(docs: dict[str, dict]) -> dict[str, list[list[dict]]]:
    """area -> [island, ...]。island = [spec, adr, adr, ...]"""
    specs = {n: d for n, d in docs.items() if d["type"] == "spec"}
    adrs = {n: d for n, d in docs.items() if d["type"] != "spec"}

    children: dict[str, list[dict]] = defaultdict(list)
    orphan_adrs: list[dict] = []
    for name, adr in adrs.items():
        parent = next((r for r in adr["related"] if r in specs), None)
        if parent:
            children[parent].append(adr)
        else:
            orphan_adrs.append(adr)

    by_area: dict[str, list[list[dict]]] = defaultdict(list)
    for name, spec in specs.items():
        island = [spec] + sorted(children[name], key=lambda d: (d.get("date", ""), d["name"]))
        by_area[spec.get("area", "その他")].append(island)
    for adr in orphan_adrs:
        by_area[adr.get("area", "その他")].append([adr])

    for area, islands in by_area.items():
        islands.sort(key=lambda isl: (isl[0].get("date", ""), isl[0]["name"]))
    return by_area


def build() -> dict:
    docs = collect_docs()
    by_area = build_islands(docs)
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_edges: set[str] = set()

    def group(key, x, y, w, h, label, color=None):
        n = {"id": nid("g:" + key), "type": "group", "x": int(x), "y": int(y),
             "width": int(w), "height": int(h), "label": label}
        if color:
            n["color"] = color
        nodes.append(n)
        return n["id"]

    def text(key, x, y, w, h, body, color=None):
        n = {"id": nid("t:" + key), "type": "text", "x": int(x), "y": int(y),
             "width": int(w), "height": int(h), "text": body}
        if color:
            n["color"] = color
        nodes.append(n)
        return n["id"]

    def filenode(key, x, y, w, h, path, color=None):
        n = {"id": nid("f:" + key), "type": "file", "x": int(x), "y": int(y),
             "width": int(w), "height": int(h), "file": path}
        if color:
            n["color"] = color
        nodes.append(n)
        return n["id"]

    def edge(a, b, label=None, fs="bottom", ts="top", color=None):
        eid = nid("e:" + "|".join(sorted([a, b])))  # 相互参照は 1 本に畳む
        if eid in seen_edges or a == b:
            return
        seen_edges.add(eid)
        e = {"id": eid, "fromNode": a, "toNode": b,
             "fromSide": fs, "toSide": ts, "toEnd": "arrow"}
        if label:
            e["label"] = label
        if color:
            e["color"] = color
        edges.append(e)

    # ---- レーンC を先に組み、その幅にレーンA/B を合わせる ----
    def island_h(island: list[dict]) -> int:
        return len(island) * CARD_H + (len(island) - 1) * CARD_GAP

    areas = sorted(
        by_area.keys(),
        key=lambda a: (CLUSTER_ORDER.index(AREA_TO_CLUSTER.get(a, "基盤")), a),
    )

    # area 枠ごとの内部レイアウト (島を列に流し込む) を先に計算
    layouts = []
    for area in areas:
        islands = by_area[area]
        cols: list[list[list[dict]]] = [[]]
        col_h = 0
        for isl in islands:
            h = island_h(isl)
            if col_h and col_h + ISLAND_GAP + h > MAX_COL_H:
                cols.append([])
                col_h = 0
            cols[-1].append(isl)
            col_h += (ISLAND_GAP if col_h else 0) + h
        heights = [
            sum(island_h(i) for i in col) + ISLAND_GAP * (len(col) - 1) for col in cols
        ]
        w = len(cols) * CARD_W + (len(cols) - 1) * COL_GAP + GROUP_PAD_X * 2
        h = max(heights) + GROUP_TOP + GROUP_BOT
        layouts.append({"area": area, "cols": cols, "w": w, "h": h})

    # 機能クラスタ = 1 本の帯 (行)。帯の中に area 枠を左から並べる
    BAND_PAD_X, BAND_TOP, BAND_BOT, BAND_GAP_Y = 20, 44, 20, 36
    bands: list[dict] = []
    y_cursor = LANE_C_Y
    for cluster in CLUSTER_ORDER:
        members = [l for l in layouts if AREA_TO_CLUSTER.get(l["area"], "基盤") == cluster]
        if not members:
            continue
        x_cursor, row_h, row_top = BAND_PAD_X, 0, y_cursor + BAND_TOP
        for lay in members:
            if x_cursor > BAND_PAD_X and x_cursor + lay["w"] > BOARD_MAX_W:
                x_cursor = BAND_PAD_X
                row_top += row_h + GROUP_GAP_Y
                row_h = 0
            lay["x"], lay["y"] = x_cursor, row_top
            x_cursor += lay["w"] + GROUP_GAP_X
            row_h = max(row_h, lay["h"])
        band_w = max(l["x"] + l["w"] for l in members) + BAND_PAD_X
        band_h = (row_top + row_h) - y_cursor + BAND_BOT
        bands.append({"cluster": cluster, "y": y_cursor, "w": band_w, "h": band_h})
        y_cursor += band_h + BAND_GAP_Y
    lane_c_w = max(b["w"] for b in bands)

    for band in bands:
        group("band:" + band["cluster"], 0, band["y"], lane_c_w, band["h"],
              f"▌ {band['cluster']}", CLUSTER_COLOR[band["cluster"]])

    node_of: dict[str, str] = {}
    for lay in layouts:
        area = lay["area"]
        cluster = AREA_TO_CLUSTER.get(area, "基盤")
        color = CLUSTER_COLOR[cluster]
        group("cC:" + area, lay["x"], lay["y"], lay["w"], lay["h"],
              f"{area}  ({cluster})", color)
        cx = lay["x"] + GROUP_PAD_X
        for col in lay["cols"]:
            cy = lay["y"] + GROUP_TOP
            for island in col:
                parent_id = None
                for doc in island:
                    card_color = "3" if doc["type"] != "spec" else color
                    node_id = filenode(doc["name"], cx, cy, CARD_W, CARD_H,
                                       doc["path"], card_color)
                    node_of[doc["name"]] = node_id
                    if parent_id is None:
                        parent_id = node_id
                    else:
                        edge(parent_id, node_id, "起票")
                    cy += CARD_H + CARD_GAP
                cy += ISLAND_GAP - CARD_GAP
            cx += CARD_W + COL_GAP

    # 同じ area 内の spec 同士の related だけ線を引く (シリーズの流れが見える)
    for doc in docs.values():
        if doc["type"] != "spec":
            continue
        src = node_of.get(doc["name"])
        for rel in doc["related"]:
            other = docs.get(rel)
            if (not src or not other or other["type"] != "spec"
                    or other.get("area") != doc.get("area")):
                continue
            edge(src, node_of[rel], None, fs="right", ts="left")

    # ---- レーンA: システム構成 ----
    lane_a_w = 1060
    lane_a_x = max(0, (lane_c_w - lane_a_w) // 2)
    group("laneA", lane_a_x, 0, lane_a_w, 500, "レーンA: システム構成 (データフロー)")
    bx = lane_a_x + 260
    browser = text("browser", bx, 40, 380, 90,
                   "**Browser** — `apps/web`\nSvelteKit + Svelte 5  :5173 / :8765", "5")
    fastapi = text("fastapi", bx, 200, 380, 110,
                   "**FastAPI** — `apps/api`\nrouters / schemas\n"
                   "/api/notebooks · sources · messages · SSE", "6")
    mcp = text("mcp", bx + 440, 200, 310, 110, "**MCP Server**\n`/mcp/*`  SSE + Bearer 認証", "6")
    sqlite = text("sqlite", lane_a_x + 60, 380, 220, 80, "**SQLite**\nメタデータ", "1")
    qdrant = text("qdrant", lane_a_x + 340, 380, 220, 80, "**Qdrant**\nベクトルDB (1024次元)", "1")
    ollama = text("ollama", lane_a_x + 620, 380, 220, 80, "**Ollama**\nLLM / 埋め込み (bge-m3)", "1")
    edge(browser, fastapi, "HTTP / SSE")
    edge(fastapi, mcp, "MCP", fs="right", ts="left")
    for target in (sqlite, qdrant, ollama):
        edge(fastapi, target)

    # ---- レーンB: core/ モジュール ----
    lane_b = group("laneB", 0, 560, lane_c_w, 270, "レーンB: core/ モジュール & 機能領域")
    slot = (lane_c_w - 40) / len(CLUSTERS)
    for i, (name, color, mods) in enumerate(CLUSTERS):
        cx = 20 + slot * i + (slot - 270) / 2
        text("cl:" + name, cx, 610, 270, 190, f"**{name}**\n{mods}", color)
    edge(fastapi, lane_b, "core modules")

    # ---- 凡例 ----
    legend_y = max(lay["y"] + lay["h"] for lay in layouts) + GROUP_GAP_Y
    legend = ("### 凡例\n"
              "- 枠 = `area` (括弧内は レーンB の機能クラスタ)。枠の色 = クラスタ色\n"
              "- 島 = 1 つの spec + そこから起票された ADR ドラフト(黄)。縦線は「起票」\n"
              "- 横線 = 同じ area 内の spec どうしの `related` (シリーズの流れ)\n"
              "- area をまたぐ `related` は線を引かない。frontmatter の `related` と\n"
              "  Obsidian のグラフビューで辿ること\n"
              "- このボードは `scripts/gen_design_canvas.py` で自動生成 (手編集しない)")
    text("legend", 0, legend_y, 780, 190, legend)

    canvas = {"nodes": nodes, "edges": edges}

    # ---- 検証 ----
    ids = [n["id"] for n in nodes]
    assert len(ids) == len(set(ids)), "duplicate node id"
    idset = set(ids)
    for e in edges:
        assert e["fromNode"] in idset and e["toNode"] in idset, "dangling edge"
    cards = [n for n in nodes if n["type"] == "file"]
    for n in cards:
        assert os.path.exists(os.path.join(ROOT, n["file"])), f"missing file: {n['file']}"
    for i, a in enumerate(cards):
        for b in cards[i + 1:]:
            if (a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"]
                    and a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"]):
                raise AssertionError(f"overlap: {a['file']} / {b['file']}")
    assert len(node_of) == len(docs), f"docs {len(docs)} != placed {len(node_of)}"
    return canvas


def main() -> None:
    canvas = build()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(canvas, f, ensure_ascii=False, indent=2)
    files = sum(1 for n in canvas["nodes"] if n["type"] == "file")
    print(f"wrote {os.path.relpath(OUT, ROOT)}: "
          f"{len(canvas['nodes'])} nodes ({files} docs), {len(canvas['edges'])} edges")


if __name__ == "__main__":
    main()

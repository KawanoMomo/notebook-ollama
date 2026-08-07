# 出典表示の刷新 — Phase 1 / 1.5 実装計画(根拠スパンのハイライト)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 出典クリック時にチャンク全文が一様に塗られる現状を、根拠スパンだけをマーカー下線で示す表示に置き換える(枝番バッジ `3-1` 付き)。

**Architecture:** 事後帰属 (post-hoc citation) の2段構成。第1段は生成完了直後にサーバで走る**字句照合**(LLM 呼び出しゼロ、CPU 数ms)。第2段は**バッジを押したときだけ**走る主張文⇔文の埋め込み類似(bge-m3 のクロスリンガル性で言語跨ぎに対応)。検索・生成・索引の経路には一切触れない。

**Tech Stack:** Python 3 / FastAPI / pytest(BE)、SvelteKit + Svelte 5 runes / vitest(FE)、markdown-it、Ollama(埋め込みのみ)

**対象範囲:** 設計書 `docs/specs/2026-08-07-citation-evidence-ui-design.md` の **Phase 1(①第1段・②・③・スキーマ/永続化)と Phase 1.5(①第2段)**。Phase 2 以降(原本ページ・quote モード β・選択範囲翻訳)は、Phase 1.5 のゲートを通過してから別計画を書く。

## Global Constraints

- 検索・生成経路のプロンプト、`core/retrieval/search.py`、索引スキーマには**変更を加えない**。
- 第1段は LLM 呼び出し・埋め込み計算を**一切行わない**(純ロジック、IO なし)。
- 第2段は**バッジ押下時のみ**実行する。生成ストリーム実行中は実行しない。15 秒でタイムアウト。
- 偽陽性は偽陰性より有害。閾値は「当たらないなら黙る」側に倒す。
- 既存の永続化済みメッセージ(`spans` 無し)は従来表示にフォールバックし、壊さない。
- 出現カウントの基準面は「**コード領域を除外した回答テキスト**」。BE と FE で同一とする。
- `answer_occurrence` は 0 起算、`ordinal` は 1 起算。
- BE テスト: `uv run --no-sync pytest`。FE テスト: `cd apps/web && npm run test:unit`。
- 作業ブランチは `spec/citation-evidence-ui`(master から分岐済み)。

## File Structure

| ファイル | 責務 |
|---|---|
| `core/generation/evidence_spans.py` (新規) | 第1段。コード領域マスク、主張文の切り出し、正規化と逆写像、n-gram 照合、閾値判定 |
| `core/retrieval/span_scorer.py` (新規) | 第2段。文分割、埋め込み類似、相対判定、多言語モデル許可リスト、LRU キャッシュ |
| `core/generation/stream.py` (変更) | `build_citations` の直後に第1段を適用 |
| `apps/api/schemas/chat.py` (変更) | `EvidenceSpan` スキーマ、第2段のリクエスト/レスポンス |
| `apps/api/routers/chat.py` (変更) | `POST /api/messages/{message_id}/citations/{n}/spans` |
| `apps/web/src/lib/api/types.ts` (変更) | `EvidenceSpan` 型、`Citation.spans` |
| `apps/web/src/lib/utils/citations.ts` (変更) | 出現カウンタ付きバッジ注入、コード領域スキップ、枝番ラベル |
| `apps/web/src/lib/utils/highlight.ts` (新規) | チャンク本文をスパン境界で分割するロジック(表示部品から分離) |
| `apps/web/src/lib/components/ChatMessage.svelte` (変更) | バッジのクリックで `answer_occurrence` を渡す |
| `apps/web/src/lib/components/SourceViewer.svelte` (変更) | `<mark>` 描画、スクロール、第2段の遅延解決 UI |
| `apps/web/src/routes/notebooks/[id]/+page.svelte` (変更) | 選択中引用の状態を保持し SourceViewer へ渡す |
| `apps/web/src/app.css` (変更) | 配色トークンの刷新 |
| `scripts/measure_evidence_spans.py` (新規) | Phase 1 / 1.5 のゲート実測 CLI |

---

### Task 1: コード領域マスクと主張文の切り出し

**Files:**
- Create: `core/generation/evidence_spans.py`
- Test: `tests/unit/test_evidence_spans_claims.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `mask_code_regions(text: str) -> str` — フェンス付きコードブロックとインラインコードの中身を同じ長さの空白に置換する(**オフセットを保存する**)
  - `@dataclass(frozen=True) ClaimOccurrence: n: int; answer_occurrence: int; claim: str`
  - `iter_claim_occurrences(answer: str) -> list[ClaimOccurrence]`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_evidence_spans_claims.py
from core.generation.evidence_spans import (
    ClaimOccurrence,
    iter_claim_occurrences,
    mask_code_regions,
)


def test_mask_code_regions_preserves_offsets():
    src = "前置き `[^9]` 後置き"
    masked = mask_code_regions(src)
    assert len(masked) == len(src)
    assert "[^9]" not in masked
    assert masked.startswith("前置き ")


def test_mask_code_regions_masks_fenced_block():
    src = "説明\n```python\nx = a[^1]\n```\n本文[^2]。"
    masked = mask_code_regions(src)
    assert len(masked) == len(src)
    assert masked.count("[^1]") == 0
    assert masked.count("[^2]") == 1


def test_iter_claim_occurrences_numbers_each_occurrence():
    answer = "レベル1は成果の達成を示す[^3]。レベル2では成果物が管理される[^3]。"
    got = iter_claim_occurrences(answer)
    assert [(c.n, c.answer_occurrence) for c in got] == [(3, 0), (3, 1)]
    assert got[0].claim == "レベル1は成果の達成を示す"
    assert got[1].claim == "レベル2では成果物が管理される"


def test_iter_claim_occurrences_strips_markers_from_claim():
    answer = "AはBである[^1][^2]。"
    got = iter_claim_occurrences(answer)
    assert all("[^" not in c.claim for c in got)
    assert [(c.n, c.answer_occurrence) for c in got] == [(1, 0), (2, 1)]


def test_iter_claim_occurrences_extends_short_claim_to_previous_sentence():
    answer = "能力レベルの定義は規格本文に示されている。そうである[^1]。"
    got = iter_claim_occurrences(answer)
    assert "能力レベルの定義は規格本文に示されている" in got[0].claim


def test_iter_claim_occurrences_ignores_markers_inside_code():
    answer = "本文[^1]。\n```\n[^2]\n```\n"
    got = iter_claim_occurrences(answer)
    assert [(c.n, c.answer_occurrence) for c in got] == [(1, 0)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_evidence_spans_claims.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.generation.evidence_spans'`

- [ ] **Step 3: Write minimal implementation**

```python
# core/generation/evidence_spans.py
"""根拠スパン解決 第1段 — 生成後の字句照合(LLM 呼び出し・埋め込み計算なし)。

設計: docs/specs/2026-08-07-citation-evidence-ui-design.md §3.1.1
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CITATION_RE = re.compile(r"\[\^(\d+)\]")
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
# 文末とみなす区切り。箇条書き先頭記号も文境界として扱う。
_SENTENCE_BOUNDARY_RE = re.compile(r"[。．!?！？\n]|(?:^|\n)\s*[-*・]\s*")

MIN_CLAIM_CHARS = 20


def mask_code_regions(text: str) -> str:
    """コード領域の中身を同じ長さの空白へ置換する。オフセットは保存される。"""

    def blank(m: re.Match[str]) -> str:
        return " " * len(m.group(0))

    masked = _FENCE_RE.sub(blank, text)
    return _INLINE_CODE_RE.sub(blank, masked)


@dataclass(frozen=True)
class ClaimOccurrence:
    n: int
    answer_occurrence: int
    claim: str


def _claim_before(masked: str, marker_start: int) -> str:
    """marker_start の直前の1文を返す。短すぎる場合は直前2文まで遡る。"""
    head = masked[:marker_start]
    bounds = [m.end() for m in _SENTENCE_BOUNDARY_RE.finditer(head)]
    for take in (1, 2):
        start = bounds[-take] if len(bounds) >= take else 0
        claim = _CITATION_RE.sub("", head[start:]).strip()
        if len(claim) >= MIN_CLAIM_CHARS:
            return claim
    start = bounds[-2] if len(bounds) >= 2 else 0
    return _CITATION_RE.sub("", head[start:]).strip()


def iter_claim_occurrences(answer: str) -> list[ClaimOccurrence]:
    """回答中の [^n] を出現順に列挙し、各出現の主張文を切り出す。

    コード領域内のマーカーは数えない(BE/FE で計数の基準面を揃えるため)。
    """
    masked = mask_code_regions(answer)
    out: list[ClaimOccurrence] = []
    for occurrence, m in enumerate(_CITATION_RE.finditer(masked)):
        out.append(
            ClaimOccurrence(
                n=int(m.group(1)),
                answer_occurrence=occurrence,
                claim=_claim_before(masked, m.start()),
            )
        )
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/unit/test_evidence_spans_claims.py -v`
Expected: PASS(6件)

- [ ] **Step 5: Commit**

```bash
git add core/generation/evidence_spans.py tests/unit/test_evidence_spans_claims.py
git commit -m "feat(citations): 回答中の引用出現ごとに主張文を切り出す"
```

---

### Task 2: 正規化と逆写像

**Files:**
- Modify: `core/generation/evidence_spans.py`
- Test: `tests/unit/test_evidence_spans_normalize.py`

**Interfaces:**
- Consumes: Task 1 のモジュール
- Produces:
  - `@dataclass(frozen=True) Normalized: text: str; origin: list[int]` — `origin[i]` は `text[i]` の元文字列上の位置
  - `normalize_for_match(text: str) -> Normalized`
  - `cjk_ratio(text: str) -> float`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_evidence_spans_normalize.py
from core.generation.evidence_spans import cjk_ratio, normalize_for_match


def test_normalize_keeps_reverse_index_map():
    src = "ABC DEF"
    got = normalize_for_match(src)
    assert len(got.text) == len(got.origin)
    # 先頭文字は元の位置 0 に対応する
    assert got.origin[0] == 0
    # 末尾文字は元の末尾に対応する
    assert got.origin[-1] == len(src) - 1


def test_normalize_drops_space_between_cjk():
    got = normalize_for_match("レベル 2 では")
    assert got.text == "レベル2では"


def test_normalize_collapses_space_between_latin():
    got = normalize_for_match("process   capability  level")
    assert got.text == "process capability level"


def test_normalize_folds_width_and_case():
    got = normalize_for_match("ＡＢＣ Ｄ")
    assert got.text.startswith("abc")


def test_normalize_drops_punctuation():
    got = normalize_for_match("レベル1は、成果(達成)を示す。")
    assert "、" not in got.text
    assert "(" not in got.text


def test_cjk_ratio():
    assert cjk_ratio("レベル1は成果") > 0.3
    assert cjk_ratio("process capability level 1") < 0.3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_evidence_spans_normalize.py -v`
Expected: FAIL — `ImportError: cannot import name 'normalize_for_match'`

- [ ] **Step 3: Write minimal implementation**

`core/generation/evidence_spans.py` の末尾に追記する。

```python
import unicodedata

_PUNCT_CATEGORIES = {"Po", "Ps", "Pe", "Pi", "Pf", "Pd", "Pc"}


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3040 <= code <= 0x30FF  # かな
        or 0x4E00 <= code <= 0x9FFF  # 漢字
        or 0x3400 <= code <= 0x4DBF
    )


def cjk_ratio(text: str) -> float:
    letters = [c for c in text if not c.isspace()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if _is_cjk(c)) / len(letters)


@dataclass(frozen=True)
class Normalized:
    text: str
    origin: list[int]


def normalize_for_match(text: str) -> Normalized:
    """NFKC → 小文字化 → 約物除去 → 空白の文字種別処理。逆写像を伴う。

    空白は「CJK どうしの間は除去、ラテンどうしの間は単一スペース」に畳む。
    英語の単語境界を壊すと頻出部分文字列で偽一致するため。
    """
    chars: list[str] = []
    origin: list[int] = []
    pending_space = False
    for idx, raw in enumerate(text):
        ch = unicodedata.normalize("NFKC", raw).lower()
        if not ch:
            continue
        ch = ch[0]
        if ch.isspace():
            pending_space = True
            continue
        if unicodedata.category(ch) in _PUNCT_CATEGORIES:
            continue
        if pending_space and chars:
            prev = chars[-1]
            if not _is_cjk(prev) and not _is_cjk(ch):
                chars.append(" ")
                origin.append(idx)
        pending_space = False
        chars.append(ch)
        origin.append(idx)
    return Normalized(text="".join(chars), origin=origin)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/unit/test_evidence_spans_normalize.py -v`
Expected: PASS(6件)

- [ ] **Step 5: Commit**

```bash
git add core/generation/evidence_spans.py tests/unit/test_evidence_spans_normalize.py
git commit -m "feat(citations): 照合用の正規化と元位置への逆写像を追加"
```

---

### Task 3: n-gram 照合とスパン確定

**Files:**
- Modify: `core/generation/evidence_spans.py`
- Test: `tests/unit/test_evidence_spans_match.py`

**Interfaces:**
- Consumes: Task 1, 2
- Produces: `resolve_lexical_span(claim: str, chunk_text: str) -> tuple[int, int] | None` — `chunk_text` 上の `(start, end)`。閾値未満は `None`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_evidence_spans_match.py
from core.generation.evidence_spans import resolve_lexical_span

CHUNK = (
    "プロセス能力レベル1は、実施されたプロセスの成果が達成されていることを示す。"
    "レベル2では作業成果物が適切に管理される。"
    "監視及び調整、責任と権限の定義、資源の特定と利用可能化が求められる。"
)


def test_exact_match_returns_span():
    span = resolve_lexical_span("レベル2では作業成果物が適切に管理される", CHUNK)
    assert span is not None
    start, end = span
    assert CHUNK[start:end].startswith("レベル2では作業成果物")


def test_second_claim_maps_to_different_span():
    first = resolve_lexical_span("プロセス能力レベル1は実施されたプロセスの成果が達成されている", CHUNK)
    second = resolve_lexical_span("監視及び調整、責任と権限の定義、資源の特定が求められる", CHUNK)
    assert first is not None and second is not None
    assert first[0] < second[0]


def test_paraphrase_returns_none():
    assert resolve_lexical_span("段階が上がると管理の度合いが増していく仕組みである", CHUNK) is None


def test_cross_language_returns_none():
    english = "Process capability level 1 indicates that the process achieves its outcomes."
    assert resolve_lexical_span("レベル1は成果の達成を示している", english) is None


def test_english_false_positive_is_rejected():
    chunk = (
        "The system shall provide a process for configuration management. "
        "Each process must define its own measurement framework."
    )
    # 頻出語 process / system のみを共有する非根拠文は採用しない
    assert resolve_lexical_span("The process of the system is fine.", chunk) is None


def test_english_true_match_is_accepted():
    chunk = (
        "The system shall provide a process for configuration management. "
        "Each process must define its own measurement framework."
    )
    span = resolve_lexical_span("Each process must define its own measurement framework", chunk)
    assert span is not None
    assert "measurement framework" in chunk[span[0] : span[1]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_evidence_spans_match.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_lexical_span'`

- [ ] **Step 3: Write minimal implementation**

`core/generation/evidence_spans.py` の末尾に追記する。

```python
NGRAM = 6
CJK_MIN_COVERAGE = 0.30
CJK_MIN_RUN = 8
LATIN_MIN_COVERAGE = 0.40
LATIN_MIN_RUN = 15
CJK_MAIN_THRESHOLD = 0.3


def _match_positions(claim: str, chunk: str) -> list[tuple[int, int]]:
    """(claim 内の開始位置, chunk 内の開始位置) の一致 n-gram 一覧。"""
    pairs: list[tuple[int, int]] = []
    for ci in range(len(claim) - NGRAM + 1):
        gram = claim[ci : ci + NGRAM]
        pos = chunk.find(gram)
        while pos != -1:
            pairs.append((ci, pos))
            pos = chunk.find(gram, pos + 1)
    return pairs


def _best_window(pairs: list[tuple[int, int]], claim_len: int) -> list[tuple[int, int]]:
    """chunk 上で最も一致が密な窓を選び、その窓に入る組を返す。"""
    if not pairs:
        return []
    width = max(claim_len * 2, NGRAM * 4)
    ordered = sorted(pairs, key=lambda p: p[1])
    best: list[tuple[int, int]] = []
    left = 0
    for right in range(len(ordered)):
        while ordered[right][1] - ordered[left][1] > width:
            left += 1
        window = ordered[left : right + 1]
        if len({p[0] for p in window}) > len({p[0] for p in best}):
            best = window
    return best


def _longest_run(claim_positions: set[int]) -> int:
    """連続する claim 位置の最長連鎖を文字数に直す。"""
    if not claim_positions:
        return 0
    ordered = sorted(claim_positions)
    best = run = 1
    for prev, cur in zip(ordered, ordered[1:]):
        run = run + 1 if cur == prev + 1 else 1
        best = max(best, run)
    return best + NGRAM - 1


def resolve_lexical_span(claim: str, chunk_text: str) -> tuple[int, int] | None:
    """主張文の根拠スパンを chunk_text 上の (start, end) で返す。当たらなければ None。"""
    nc = normalize_for_match(claim)
    nt = normalize_for_match(chunk_text)
    if len(nc.text) < NGRAM or len(nt.text) < NGRAM:
        return None

    window = _best_window(_match_positions(nc.text, nt.text), len(nc.text))
    if not window:
        return None

    claim_positions = {p[0] for p in window}
    total = len(nc.text) - NGRAM + 1
    coverage = len(claim_positions) / total if total else 0.0
    run = _longest_run(claim_positions)

    if cjk_ratio(nc.text) >= CJK_MAIN_THRESHOLD:
        min_coverage, min_run = CJK_MIN_COVERAGE, CJK_MIN_RUN
    else:
        min_coverage, min_run = LATIN_MIN_COVERAGE, LATIN_MIN_RUN
    if coverage < min_coverage or run < min_run:
        return None

    lo = min(p[1] for p in window)
    hi = max(p[1] for p in window) + NGRAM - 1
    return nt.origin[lo], nt.origin[min(hi, len(nt.origin) - 1)] + 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/unit/test_evidence_spans_match.py -v`
Expected: PASS(6件)

- [ ] **Step 5: Commit**

```bash
git add core/generation/evidence_spans.py tests/unit/test_evidence_spans_match.py
git commit -m "feat(citations): n-gram照合と言語別閾値で根拠スパンを確定する"
```

---

### Task 4: 引用への spans 付与(公開 API)

**Files:**
- Modify: `core/generation/evidence_spans.py`
- Test: `tests/unit/test_evidence_spans_attach.py`

**Interfaces:**
- Consumes: Task 1–3
- Produces: `attach_evidence_spans(*, answer: str, citations: list[dict], chunk_texts: dict[str, str]) -> list[dict]` — 各 citation に `spans` キー(list[dict])を足した新しいリストを返す。span の形は `{"answer_occurrence": int, "ordinal": int, "start": int, "end": int, "quote": str, "method": "lexical"}`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_evidence_spans_attach.py
from core.generation.evidence_spans import attach_evidence_spans

CHUNK = (
    "プロセス能力レベル1は、実施されたプロセスの成果が達成されていることを示す。"
    "レベル2では作業成果物が適切に管理される。"
)
CITATIONS = [{"n": 3, "chunk_id": "c1"}]
TEXTS = {"c1": CHUNK}


def test_attaches_span_with_ordinal_and_occurrence():
    answer = "レベル2では作業成果物が適切に管理される[^3]。"
    got = attach_evidence_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    assert len(got[0]["spans"]) == 1
    span = got[0]["spans"][0]
    assert span["ordinal"] == 1
    assert span["answer_occurrence"] == 0
    assert span["method"] == "lexical"
    assert CHUNK[span["start"] : span["end"]] == span["quote"]


def test_two_occurrences_get_sequential_ordinals():
    answer = (
        "プロセス能力レベル1は実施されたプロセスの成果が達成されていることを示す[^3]。"
        "レベル2では作業成果物が適切に管理される[^3]。"
    )
    got = attach_evidence_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    spans = got[0]["spans"]
    assert [s["ordinal"] for s in spans] == [1, 2]
    assert [s["answer_occurrence"] for s in spans] == [0, 1]


def test_unresolved_occurrence_does_not_shift_ordinals():
    answer = (
        "段階が上がると管理の度合いが増していく仕組みである[^3]。"  # 未特定
        "レベル2では作業成果物が適切に管理される[^3]。"  # 特定できる
    )
    got = attach_evidence_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    spans = got[0]["spans"]
    assert len(spans) == 1
    assert spans[0]["answer_occurrence"] == 1  # 2番目の出現に正しく対応する
    assert spans[0]["ordinal"] == 1


def test_missing_chunk_text_yields_empty_spans():
    answer = "レベル2では作業成果物が適切に管理される[^3]。"
    got = attach_evidence_spans(answer=answer, citations=CITATIONS, chunk_texts={})
    assert got[0]["spans"] == []


def test_original_citations_are_not_mutated():
    answer = "レベル2では作業成果物が適切に管理される[^3]。"
    attach_evidence_spans(answer=answer, citations=CITATIONS, chunk_texts=TEXTS)
    assert "spans" not in CITATIONS[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_evidence_spans_attach.py -v`
Expected: FAIL — `ImportError: cannot import name 'attach_evidence_spans'`

- [ ] **Step 3: Write minimal implementation**

`core/generation/evidence_spans.py` の末尾に追記する。

```python
from typing import Any


def attach_evidence_spans(
    *,
    answer: str,
    citations: list[dict[str, Any]],
    chunk_texts: dict[str, str],
) -> list[dict[str, Any]]:
    """各 citation に spans を付けた新しいリストを返す(引数は変更しない)。"""
    occurrences = iter_claim_occurrences(answer)
    spans_by_n: dict[int, list[dict[str, Any]]] = {}
    for occ in occurrences:
        citation = next((c for c in citations if c.get("n") == occ.n), None)
        if citation is None:
            continue
        text = chunk_texts.get(citation.get("chunk_id", ""))
        if not text:
            continue
        found = resolve_lexical_span(occ.claim, text)
        if found is None:
            continue
        start, end = found
        bucket = spans_by_n.setdefault(occ.n, [])
        bucket.append(
            {
                "answer_occurrence": occ.answer_occurrence,
                "ordinal": len(bucket) + 1,
                "start": start,
                "end": end,
                "quote": text[start:end],
                "method": "lexical",
            }
        )
    return [{**c, "spans": spans_by_n.get(c.get("n"), [])} for c in citations]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/unit/test_evidence_spans_attach.py -v`
Expected: PASS(5件)

- [ ] **Step 5: Commit**

```bash
git add core/generation/evidence_spans.py tests/unit/test_evidence_spans_attach.py
git commit -m "feat(citations): 引用へ根拠スパンを付与する公開APIを追加"
```

---

### Task 5: 生成ストリームへの接続と永続化

**Files:**
- Modify: `core/generation/stream.py`(`build_citations` 呼び出し箇所)
- Modify: `apps/api/schemas/chat.py`
- Test: `tests/integration/test_chat_spans_persist.py`

**Interfaces:**
- Consumes: `attach_evidence_spans`(Task 4)
- Produces: `done` イベントの `citations[*].spans`、および `messages` テーブルへの永続化

**Notes:** `citations` は `messages` テーブルに JSON 列として保存される(`core/storage/messages_repo.py`)。したがって `spans` を dict に含めるだけで永続化される。**マイグレーションは不要**。既存行は `spans` キーを持たないため、読み出し側で欠落を空リストとして扱う。

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_chat_spans_persist.py
"""spans が messages に保存され、再読込で戻ることを確認する。

セットアップは tests/integration/test_conversations_repo.py の書き方に倣う
(tests/integration に conftest.py は無く、各テストが tmp_path から DB を作る)。
"""

from core.storage.conversations_repo import create_conversation
from core.storage.database import connect, migrate
from core.storage.messages_repo import append_message, list_messages
from core.storage.notebooks_repo import create_notebook


def _ctx(tmp_path):
    conn = connect(tmp_path / "m.db")
    migrate(conn)
    nb = create_notebook(conn, name="N")
    conv = create_conversation(conn, notebook_id=nb.id, title="t")
    return conn, conv


def test_spans_round_trip_through_messages(tmp_path):
    conn, conv = _ctx(tmp_path)
    citations = [
        {
            "n": 1,
            "chunk_id": "c1",
            "source_id": "s1",
            "source_title": "t",
            "location": "p.1",
            "url_or_path": None,
            "snippet": "x",
            "audio_source_id": None,
            "audio_start_ms": None,
            "audio_channel": None,
            "spans": [
                {
                    "answer_occurrence": 0,
                    "ordinal": 1,
                    "start": 3,
                    "end": 9,
                    "quote": "abcdef",
                    "method": "lexical",
                }
            ],
        }
    ]
    append_message(
        conn,
        conversation_id=conv.id,
        role="assistant",
        content="answer[^1]",
        citations=citations,
        model="m",
    )
    rows = list_messages(conn, conversation_id=conv.id)
    assert rows[-1].citations[0]["spans"][0]["quote"] == "abcdef"


def test_legacy_citation_without_spans_is_readable(tmp_path):
    conn, conv = _ctx(tmp_path)
    append_message(
        conn,
        conversation_id=conv.id,
        role="assistant",
        content="answer[^1]",
        citations=[{"n": 1, "chunk_id": "c1"}],
        model="m",
    )
    rows = list_messages(conn, conversation_id=conv.id)
    assert rows[-1].citations[0].get("spans", []) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/integration/test_chat_spans_persist.py -v`
Expected: FAIL(フィクスチャ未整備、または関数名不一致)。既存テストに合わせて名前を直し、**spans 未実装が理由で落ちる状態**にしてから次へ進む。

- [ ] **Step 3: Write minimal implementation**

`core/generation/stream.py` — `citations = build_citations(...)` の直後に第1段を適用する。`hits` はこのスコープに存在する。

```python
from core.generation.evidence_spans import attach_evidence_spans

        answer = "".join(answer_parts)
        citations = build_citations(answer=answer, specs=spec_by_n)
        # 第1段(字句照合)。LLM 呼び出しなし・CPU 数ms。生成レイテンシに影響しない。
        citations = attach_evidence_spans(
            answer=answer,
            citations=citations,
            chunk_texts={h.chunk_id: h.text for h in hits},
        )
```

`apps/api/schemas/chat.py` — スキーマを明示する(既存の `citations: list[dict[str, Any]]` はそのままでも通るが、契約を型で固定する)。

```python
from typing import Literal

from pydantic import BaseModel


class EvidenceSpan(BaseModel):
    answer_occurrence: int  # 0 起算
    ordinal: int | None = None  # 1 起算。第2段(embedding)では None
    start: int
    end: int
    quote: str
    method: Literal["lexical", "embedding", "quote"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/integration/test_chat_spans_persist.py -v && uv run --no-sync pytest -q`
Expected: 新規 PASS、既存テストの回帰なし

- [ ] **Step 5: Commit**

```bash
git add core/generation/stream.py apps/api/schemas/chat.py tests/integration/test_chat_spans_persist.py
git commit -m "feat(citations): 生成完了時に根拠スパンを付与し永続化する"
```

---

### Task 6: FE — 型と枝番バッジ注入

**Files:**
- Modify: `apps/web/src/lib/api/types.ts`
- Modify: `apps/web/src/lib/utils/citations.ts`
- Test: `apps/web/tests/unit/citations.test.ts`(既存に追記)

**Interfaces:**
- Consumes: Task 5 の JSON 形
- Produces:
  - `types.ts`: `export interface EvidenceSpan { answer_occurrence: number; ordinal: number | null; start: number; end: number; quote: string; method: 'lexical' | 'embedding' | 'quote'; }` と `Citation.spans?: EvidenceSpan[]`
  - `citations.ts`: `injectCitationBadges(html: string, citations: Citation[]): string`(シグネチャ据え置き。バッジに `data-occurrence` とラベルを持たせる)

**Notes:** `renderMarkdown` は `markdown-it` を `html: false` で使うため、**レンダリング前**に HTML を差し込むとエスケープされる。したがって注入は**レンダリング後**に行い、`<code>` / `<pre>` の内側をスキップすることで BE と計数の基準面を揃える。

- [ ] **Step 1: Write the failing test**

```ts
// apps/web/tests/unit/citations.test.ts に追記
import { describe, expect, it } from 'vitest';
import { injectCitationBadges } from '../../src/lib/utils/citations';
import type { Citation } from '../../src/lib/api/types';

const cite = (n: number, spans: Citation['spans'] = []): Citation =>
  ({
    n,
    chunk_id: `c${n}`,
    source_id: 's1',
    source_title: 'タイトル',
    location: 'p.1',
    url_or_path: null,
    snippet: '',
    audio_source_id: null,
    audio_start_ms: null,
    audio_channel: null,
    spans,
  }) as Citation;

describe('injectCitationBadges — 枝番', () => {
  it('spans があれば出現ごとに枝番ラベルを振る', () => {
    const c = cite(3, [
      { answer_occurrence: 0, ordinal: 1, start: 0, end: 3, quote: 'abc', method: 'lexical' },
      { answer_occurrence: 1, ordinal: 2, start: 5, end: 8, quote: 'def', method: 'lexical' },
    ]);
    const html = injectCitationBadges('<p>A[^3]。B[^3]。</p>', [c]);
    expect(html).toContain('>3-1<');
    expect(html).toContain('>3-2<');
    expect(html).toContain('data-occurrence="0"');
    expect(html).toContain('data-occurrence="1"');
  });

  it('spans が無ければ従来どおり番号のみ', () => {
    const html = injectCitationBadges('<p>A[^3]。</p>', [cite(3)]);
    expect(html).toContain('>3<');
    expect(html).not.toContain('3-1');
  });

  it('一部の出現だけ未特定でも対応がズレない', () => {
    const c = cite(3, [
      { answer_occurrence: 1, ordinal: 1, start: 5, end: 8, quote: 'def', method: 'lexical' },
    ]);
    const html = injectCitationBadges('<p>A[^3]。B[^3]。</p>', [c]);
    // 1つ目の出現は枝番なし、2つ目が 3-1
    const first = html.indexOf('data-occurrence="0"');
    const second = html.indexOf('data-occurrence="1"');
    expect(first).toBeGreaterThan(-1);
    expect(second).toBeGreaterThan(first);
    expect(html.slice(first, second)).toContain('>3<');
    expect(html.slice(second)).toContain('>3-1<');
  });

  it('コードブロック内のマーカーは数えずバッジ化もしない', () => {
    const c = cite(1, [
      { answer_occurrence: 0, ordinal: 1, start: 0, end: 3, quote: 'abc', method: 'lexical' },
    ]);
    const html = injectCitationBadges('<p>本文[^1]。</p><pre><code>[^1]</code></pre>', [c]);
    expect(html).toContain('data-occurrence="0"');
    expect(html).not.toContain('data-occurrence="1"');
    expect(html).toContain('<code>[^1]</code>');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && npx vitest run tests/unit/citations.test.ts`
Expected: FAIL — 枝番ラベルも `data-occurrence` も出力されない

- [ ] **Step 3: Write minimal implementation**

```ts
// apps/web/src/lib/api/types.ts に追記
export interface EvidenceSpan {
  answer_occurrence: number;
  ordinal: number | null;
  start: number;
  end: number;
  quote: string;
  method: 'lexical' | 'embedding' | 'quote';
}

// 既存の Citation に追加
//   spans?: EvidenceSpan[];
```

```ts
// apps/web/src/lib/utils/citations.ts を差し替え
import type { Citation } from '$lib/api/types';

const CODE_REGION_RE = /<(code|pre)\b[\s\S]*?<\/\1>/gi;

/**
 * [^n] マーカーをバッジへ置換する。
 *
 * 計数の基準面は「コード領域を除外した本文」。BE の iter_claim_occurrences と
 * 同じ規則にすることで answer_occurrence の対応が崩れないようにしている。
 */
export function injectCitationBadges(html: string, citations: Citation[]): string {
  const byN = new Map(citations.map((c) => [c.n, c]));
  let occurrence = 0;

  const replaceOutsideCode = (segment: string): string =>
    segment.replace(/\[\^(\d+)\]/g, (_m, nStr) => {
      const n = Number(nStr);
      const c = byN.get(n);
      if (!c) return `[^${n}]`;
      const current = occurrence++;
      const span = c.spans?.find((s) => s.answer_occurrence === current);
      const label = span?.ordinal != null ? `${n}-${span.ordinal}` : `${n}`;
      const title = `${c.source_title}${c.location ? ' / ' + c.location : ''}`;
      return (
        `<button class="citation-badge" data-n="${n}" data-occurrence="${current}"` +
        ` title="${escapeAttr(title)}">${label}</button>`
      );
    });

  let out = '';
  let cursor = 0;
  for (const m of html.matchAll(CODE_REGION_RE)) {
    const at = m.index ?? 0;
    out += replaceOutsideCode(html.slice(cursor, at));
    out += m[0]; // コード領域はそのまま
    cursor = at + m[0].length;
  }
  out += replaceOutsideCode(html.slice(cursor));
  return out;
}

function escapeAttr(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}

/** Extract list of citation numbers in textual order. */
export function listCitationNumbers(text: string): number[] {
  const seen = new Set<number>();
  const out: number[] = [];
  for (const m of text.matchAll(/\[\^(\d+)\]/g)) {
    const n = Number(m[1]);
    if (!seen.has(n)) {
      seen.add(n);
      out.push(n);
    }
  }
  return out;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/web && npx vitest run tests/unit/citations.test.ts`
Expected: PASS(既存ケースを含む)

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/api/types.ts apps/web/src/lib/utils/citations.ts apps/web/tests/unit/citations.test.ts
git commit -m "feat(web): 引用バッジを枝番表示にし出現位置を持たせる"
```

---

### Task 7: FE — 配色トークンの刷新

**Files:**
- Modify: `apps/web/src/app.css`
- Modify: `apps/web/src/lib/components/ChatMessage.svelte`(`.num` と `.citation-badge` のスタイル)
- Delete: `apps/web/src/lib/components/CitationBadge.svelte`(どこからも import されていない死んだコンポーネント)
- Test: `apps/web/tests/unit/citationTheme.test.ts`(新規)

**Interfaces:**
- Consumes: なし
- Produces: CSS 変数 `--color-evidence` / `--color-evidence-soft` / `--color-evidence-faint`。`--color-citation-bg` / `--color-citation-border` は廃止

- [ ] **Step 1: Write the failing test**

```ts
// apps/web/tests/unit/citationTheme.test.ts
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const css = readFileSync(new URL('../../src/app.css', import.meta.url), 'utf8');

describe('配色トークン', () => {
  it('黄色の引用トークンは廃止されている', () => {
    expect(css).not.toContain('--color-citation-bg');
    expect(css).not.toContain('--color-citation-border');
    expect(css).not.toContain('#fff8c4');
  });

  it('根拠用トークンが定義されている', () => {
    expect(css).toContain('--color-evidence:');
    expect(css).toContain('--color-evidence-soft:');
    expect(css).toContain('--color-evidence-faint:');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && npx vitest run tests/unit/citationTheme.test.ts`
Expected: FAIL — 旧トークンが残っている

- [ ] **Step 3: Write minimal implementation**

```css
/* apps/web/src/app.css — :root 内。旧2行を置き換える */
  --color-evidence: #3563e9;
  --color-evidence-soft: rgba(53, 99, 233, 0.14);
  --color-evidence-faint: rgba(53, 99, 233, 0.06);
```

```svelte
<!-- apps/web/src/lib/components/ChatMessage.svelte の <style> — .num を置き換え、
     .citation-badge のスタイルを足す(バッジは {@html} で挿入されるため :global が要る) -->
  .num {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: var(--color-evidence-faint);
    border: 1px solid var(--color-evidence);
    color: var(--color-evidence);
    border-radius: var(--radius-sm);
    min-width: 20px;
    height: 18px;
    padding: 0 5px;
    font-size: 11px;
    font-weight: 600;
    flex-shrink: 0;
  }
  .content :global(.citation-badge) {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: var(--color-evidence-faint);
    border: 1px solid var(--color-evidence);
    color: var(--color-evidence);
    border-radius: var(--radius-sm);
    min-width: 20px;
    height: 17px;
    padding: 0 5px;
    margin: 0 2px;
    font-size: 10.5px;
    font-weight: 600;
    vertical-align: middle;
    cursor: pointer;
  }
  .content :global(.citation-badge:hover) {
    background: var(--color-evidence);
    color: #fff;
  }
```

```bash
git rm apps/web/src/lib/components/CitationBadge.svelte
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/web && npx vitest run tests/unit/citationTheme.test.ts && npm run test:unit && npm run build`
Expected: PASS、ビルドも成功(削除したコンポーネントへの参照が無いことの確認を兼ねる)

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/app.css apps/web/src/lib/components/ChatMessage.svelte apps/web/tests/unit/citationTheme.test.ts
git commit -m "feat(web): 引用の配色を黄色からアクセント系トークンへ刷新"
```

---

### Task 8: FE — チャンク本文の分割ロジック

**Files:**
- Create: `apps/web/src/lib/utils/highlight.ts`
- Test: `apps/web/tests/unit/highlight.test.ts`(新規)

**Interfaces:**
- Consumes: `EvidenceSpan`(Task 6)
- Produces: `splitBySpans(text: string, spans: EvidenceSpan[], activeOccurrence: number | null): Segment[]`。`Segment` は `{ text: string; span: EvidenceSpan | null; active: boolean }`

- [ ] **Step 1: Write the failing test**

```ts
// apps/web/tests/unit/highlight.test.ts
import { describe, expect, it } from 'vitest';
import { splitBySpans } from '../../src/lib/utils/highlight';
import type { EvidenceSpan } from '../../src/lib/api/types';

const span = (o: number, ord: number, s: number, e: number): EvidenceSpan => ({
  answer_occurrence: o,
  ordinal: ord,
  start: s,
  end: e,
  quote: '',
  method: 'lexical',
});

describe('splitBySpans', () => {
  it('スパンが無ければ1セグメント', () => {
    const got = splitBySpans('abcdef', [], null);
    expect(got).toEqual([{ text: 'abcdef', span: null, active: false }]);
  });

  it('スパン前後を分割する', () => {
    const got = splitBySpans('abcdef', [span(0, 1, 2, 4)], 0);
    expect(got.map((s) => s.text)).toEqual(['ab', 'cd', 'ef']);
    expect(got[1].active).toBe(true);
  });

  it('選択中でないスパンは active=false', () => {
    const got = splitBySpans('abcdef', [span(1, 1, 2, 4)], 0);
    expect(got[1].active).toBe(false);
  });

  it('複数スパンを開始位置順に並べる', () => {
    const got = splitBySpans('abcdefgh', [span(1, 2, 5, 7), span(0, 1, 1, 3)], 1);
    expect(got.map((s) => s.text)).toEqual(['a', 'bc', 'de', 'fg', 'h']);
    expect(got[1].active).toBe(false);
    expect(got[3].active).toBe(true);
  });

  it('範囲外・逆転したスパンは無視する', () => {
    const got = splitBySpans('abc', [span(0, 1, 5, 9), span(0, 2, 3, 1)], 0);
    expect(got).toEqual([{ text: 'abc', span: null, active: false }]);
  });

  it('重なったスパンは後のものを捨てる', () => {
    const got = splitBySpans('abcdef', [span(0, 1, 1, 4), span(1, 1, 2, 5)], 0);
    expect(got.map((s) => s.text)).toEqual(['a', 'bcd', 'ef']);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && npx vitest run tests/unit/highlight.test.ts`
Expected: FAIL — モジュールが存在しない

- [ ] **Step 3: Write minimal implementation**

```ts
// apps/web/src/lib/utils/highlight.ts
import type { EvidenceSpan } from '$lib/api/types';

export interface Segment {
  text: string;
  span: EvidenceSpan | null;
  active: boolean;
}

/**
 * チャンク本文をスパン境界で分割する。
 * activeOccurrence に一致するスパンだけ active=true(濃いマーカー)。
 */
export function splitBySpans(
  text: string,
  spans: EvidenceSpan[],
  activeOccurrence: number | null,
): Segment[] {
  const valid = spans
    .filter((s) => s.start >= 0 && s.end > s.start && s.end <= text.length)
    .sort((a, b) => a.start - b.start);

  const segments: Segment[] = [];
  let cursor = 0;
  for (const s of valid) {
    if (s.start < cursor) continue; // 重なりは先勝ち
    if (s.start > cursor) {
      segments.push({ text: text.slice(cursor, s.start), span: null, active: false });
    }
    segments.push({
      text: text.slice(s.start, s.end),
      span: s,
      active: activeOccurrence !== null && s.answer_occurrence === activeOccurrence,
    });
    cursor = s.end;
  }
  if (cursor < text.length) {
    segments.push({ text: text.slice(cursor), span: null, active: false });
  }
  return segments.length > 0 ? segments : [{ text, span: null, active: false }];
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/web && npx vitest run tests/unit/highlight.test.ts`
Expected: PASS(6件)

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/utils/highlight.ts apps/web/tests/unit/highlight.test.ts
git commit -m "feat(web): チャンク本文をスパン境界で分割するユーティリティを追加"
```

---

### Task 9: FE — 選択中引用の受け渡しとハイライト描画

**Files:**
- Modify: `apps/web/src/lib/components/ChatMessage.svelte`
- Modify: `apps/web/src/routes/notebooks/[id]/+page.svelte`
- Modify: `apps/web/src/lib/components/ChatPanel.svelte`(`onCitationClick` の受け渡しがあれば同じ形に合わせる)
- Modify: `apps/web/src/lib/components/SourceViewer.svelte`
- Test: `apps/web/tests/unit/SourceViewerHighlight.test.ts`(新規)

**Interfaces:**
- Consumes: `splitBySpans`(Task 8)、`Citation.spans`(Task 6)
- Produces:
  - `ChatMessage` の `onCitationClick(chunkId: string, sourceId: string, selection: { citation: Citation; answerOccurrence: number } | null)`
  - `SourceViewer` の新規 prop `selectedCitation: { citation: Citation; answerOccurrence: number } | null`

**Notes:** `SourceViewer` は現在 `selectedChunkId` しか受け取らないため、どの出現がクリックされたかを知らない。上記 prop を足して伝える。表アセット HTML 置換パス(`tableAssetHtml` が非 null)では**ハイライトしない**(オフセットが無効になるため)。

- [ ] **Step 1: Write the failing test**

```ts
// apps/web/tests/unit/SourceViewerHighlight.test.ts
import { describe, expect, it } from 'vitest';
import { splitBySpans } from '../../src/lib/utils/highlight';
import type { Citation } from '../../src/lib/api/types';

/**
 * SourceViewer は API 依存が重いため、描画に使う純ロジックを検証する。
 * (コンポーネント全体の実機確認は evaluator のスクリーンショットで担保する)
 */
const citation = {
  n: 3,
  chunk_id: 'c1',
  spans: [
    { answer_occurrence: 0, ordinal: 1, start: 0, end: 5, quote: 'ABCDE', method: 'lexical' },
    { answer_occurrence: 2, ordinal: 2, start: 8, end: 12, quote: 'IJKL', method: 'lexical' },
  ],
} as unknown as Citation;

describe('出典パネルのハイライト対象', () => {
  it('選択中の出現だけが active になる', () => {
    const got = splitBySpans('ABCDEFGHIJKLMN', citation.spans!, 2);
    const actives = got.filter((s) => s.active).map((s) => s.text);
    expect(actives).toEqual(['IJKL']);
  });

  it('同じチャンクの他スパンも淡色で描画対象に残る', () => {
    const got = splitBySpans('ABCDEFGHIJKLMN', citation.spans!, 2);
    const marks = got.filter((s) => s.span !== null).map((s) => s.text);
    expect(marks).toEqual(['ABCDE', 'IJKL']);
  });

  it('spans が空なら分割されない(従来表示へのフォールバック)', () => {
    const got = splitBySpans('ABCDEFGHIJKLMN', [], null);
    expect(got).toHaveLength(1);
    expect(got[0].span).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && npx vitest run tests/unit/SourceViewerHighlight.test.ts`
Expected: PASS(Task 8 の実装で通る)。**このテストは回帰用の受け皿**なので、続けて下記の実装を行い `npm run build` が通ることを確認する。

- [ ] **Step 3: Write minimal implementation**

`ChatMessage.svelte` — クリック時に出現位置を渡す。

```svelte
  interface Props {
    message: Message;
    onCitationClick: (
      chunkId: string,
      sourceId: string,
      selection: { citation: Citation; answerOccurrence: number } | null,
    ) => void;
  }

  function onContentClick(e: MouseEvent) {
    const t = e.target;
    if (t instanceof HTMLElement && t.classList.contains('citation-badge')) {
      const n = Number(t.dataset.n);
      const occurrence = Number(t.dataset.occurrence);
      const c = Number.isFinite(n) ? citationByN(n) : undefined;
      if (c) {
        onCitationClick(
          c.chunk_id,
          c.source_id,
          Number.isFinite(occurrence) ? { citation: c, answerOccurrence: occurrence } : null,
        );
      }
    }
  }
```

出典カード側(`.card` の onclick)は `onCitationClick(c.chunk_id, c.source_id, null)` に変える。

`+page.svelte` — 状態を1つ足して SourceViewer へ渡す。

```svelte
  let selectedCitation = $state<{ citation: Citation; answerOccurrence: number } | null>(null);

  // onCitationClick ハンドラ内で
  //   selectedSourceId = sourceId; selectedChunkId = chunkId; selectedCitation = selection;

  <SourceViewer {notebookId} {selectedSourceId} {selectedChunkId} {selectedCitation} />
```

`SourceViewer.svelte` — props に追加し、通常テキストの `<pre class="text">{chunk.text}</pre>` を分割描画へ置き換える(録音パス・親スライドパスの `<pre class="text">` も同じ置き換えを行う。表アセットパスは置き換えない)。

```svelte
  import { splitBySpans } from '$lib/utils/highlight';
  import type { Citation } from '$lib/api/types';

  interface Props {
    notebookId: string;
    selectedChunkId: string | null;
    selectedSourceId: string | null;
    selectedCitation: { citation: Citation; answerOccurrence: number } | null;
  }

  const activeSpans = $derived(
    selectedCitation && selectedCitation.citation.chunk_id === selectedChunkId
      ? (selectedCitation.citation.spans ?? [])
      : [],
  );
  const segments = $derived(chunk ? splitBySpans(chunk.text, activeSpans, selectedCitation?.answerOccurrence ?? null) : []);
  const unresolved = $derived(!!selectedCitation && activeSpans.length === 0);
```

```svelte
{#if unresolved}
  <p class="unresolved">この主張の根拠箇所は特定できませんでした</p>
{/if}
<pre class="text">{#each segments as seg}{#if seg.span}<mark
      class={seg.active ? 'ev active' : 'ev'}>{seg.text}</mark>{:else}{seg.text}{/if}{/each}</pre>
```

```css
  .text :global(mark.ev) {
    background: linear-gradient(transparent 62%, var(--color-evidence-faint) 62%);
    border-bottom: 2px solid color-mix(in srgb, var(--color-evidence) 35%, transparent);
    color: inherit;
  }
  .text :global(mark.ev.active) {
    background: linear-gradient(transparent 62%, var(--color-evidence-soft) 62%);
    border-bottom-color: var(--color-evidence);
  }
  .unresolved {
    margin: 0 0 var(--space-2);
    font-size: 11px;
    color: var(--color-fg-muted);
  }
```

選択中スパンへのスクロールは `$effect` で行う。

```svelte
  let textEl = $state<HTMLElement | null>(null);
  $effect(() => {
    if (!textEl || !selectedCitation) return;
    const target = textEl.querySelector('mark.ev.active');
    target?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  });
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/web && npx vitest run tests/unit/SourceViewerHighlight.test.ts && npm run test:unit && npm run build`
Expected: すべて PASS、ビルド成功

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/components/ChatMessage.svelte apps/web/src/lib/components/SourceViewer.svelte apps/web/src/routes/notebooks/\[id\]/+page.svelte apps/web/tests/unit/SourceViewerHighlight.test.ts
git commit -m "feat(web): 出典パネルで根拠スパンをマーカー下線で強調する"
```

---

### Task 10: Phase 1 ゲート — 解決率の実測 CLI

**Files:**
- Create: `scripts/measure_evidence_spans.py`
- Test: `tests/unit/test_measure_evidence_spans.py`

**Interfaces:**
- Consumes: `attach_evidence_spans`(Task 4)
- Produces: `summarize(records: list[dict]) -> dict` — `{"total": int, "resolved": int, "rate": float}`。CLI は保存済み会話を読み、第1段の解決率を出力する

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_measure_evidence_spans.py
from scripts.measure_evidence_spans import summarize


def test_summarize_counts_occurrences_not_citations():
    records = [
        {"answer": "A[^1]。B[^1]。", "citations": [{"n": 1, "spans": [{"answer_occurrence": 0}]}]},
    ]
    got = summarize(records)
    assert got["total"] == 2
    assert got["resolved"] == 1
    assert got["rate"] == 0.5


def test_summarize_handles_empty():
    assert summarize([]) == {"total": 0, "resolved": 0, "rate": 0.0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_measure_evidence_spans.py -v`
Expected: FAIL — モジュールが存在しない

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/measure_evidence_spans.py
"""第1段(字句照合)の解決率を実測する。Phase 1 ゲート用。

使い方:
    uv run --no-sync python scripts/measure_evidence_spans.py --data-dir <隔離data_dir>

本番 data_dir を指さないこと(隔離環境で実行する)。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from core.generation.evidence_spans import iter_claim_occurrences


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = 0
    resolved = 0
    for rec in records:
        occurrences = iter_claim_occurrences(rec["answer"])
        total += len(occurrences)
        seen = {
            (c["n"], s["answer_occurrence"])
            for c in rec.get("citations", [])
            for s in c.get("spans", [])
        }
        resolved += sum(1 for o in occurrences if (o.n, o.answer_occurrence) in seen)
    rate = resolved / total if total else 0.0
    return {"total": total, "resolved": resolved, "rate": rate}


def _load(db_path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT content, citations FROM messages WHERE role='assistant' AND citations IS NOT NULL"
    ).fetchall()
    conn.close()
    return [
        {"answer": r["content"], "citations": json.loads(r["citations"])}
        for r in rows
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args()
    result = summarize(_load(args.data_dir / "notebook.db"))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

> DB ファイル名は `core/config.py` の設定に合わせること(異なれば実際の名前に直す)。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/unit/test_measure_evidence_spans.py -v`
Expected: PASS(2件)

- [ ] **Step 5: Commit**

```bash
git add scripts/measure_evidence_spans.py tests/unit/test_measure_evidence_spans.py
git commit -m "feat(citations): 第1段の解決率を実測するCLIを追加"
```

---

### Task 11: Phase 1 実機検証ゲート(コード変更なし)

**Files:** なし(検証のみ)

**Interfaces:**
- Consumes: Task 1–10 の成果
- Produces: 実測値とスクリーンショット。ここで**立ち止まる**

- [ ] **Step 1: 隔離環境で起動**

```bash
# 本番 data_dir と 8765 ポートは使わない
NOTEBOOK_DATA_DIR=./.verify-data uv run --no-sync uvicorn apps.api.main:app --port 8799
cd apps/web && npm run dev
```

- [ ] **Step 2: 日本語 PDF を1本取り込み、5問質問する**

- [ ] **Step 3: 解決率を測る**

Run: `uv run --no-sync python scripts/measure_evidence_spans.py --data-dir ./.verify-data`
記録: `total` / `resolved` / `rate`

- [ ] **Step 4: スクリーンショットを撮る**

evaluator エージェントで以下3点を撮影する。自動テストの GREEN だけでは PASS としない(CLAUDE.md 禁止事項)。
1. 根拠スパンがマーカー下線で表示されている出典パネル
2. 同一チャンクに複数スパンがあり、選択中だけ濃い状態
3. 未特定時の「この主張の根拠箇所は特定できませんでした」表示

- [ ] **Step 5: 判断**

`rate` が実用水準に届かない場合、Phase 1.5 へ進む前に閾値(`CJK_MIN_COVERAGE` / `CJK_MIN_RUN`)を調整するか、設計に戻る。**満たさないまま Task 12 以降へ進まないこと。**

---

### Task 12: 第2段 — 文分割

**Files:**
- Create: `core/retrieval/span_scorer.py`
- Test: `tests/unit/test_span_scorer_split.py`

**Interfaces:**
- Consumes: なし
- Produces: `@dataclass(frozen=True) Sentence: text: str; start: int; end: int` と `split_sentences(text: str) -> list[Sentence]`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_span_scorer_split.py
from core.retrieval.span_scorer import split_sentences


def test_splits_japanese_by_kuten():
    got = split_sentences("これは一文目である。これは二文目である。")
    assert [s.text for s in got] == ["これは一文目である。", "これは二文目である。"]


def test_offsets_point_into_original():
    src = "これは一文目である。これは二文目である。"
    for s in split_sentences(src):
        assert src[s.start : s.end] == s.text


def test_does_not_oversplit_english_abbreviations():
    got = split_sentences("See Fig. 3 for details. The next sentence follows here.")
    assert len(got) == 2
    assert got[0].text.startswith("See Fig. 3")


def test_table_markdown_row_is_one_unit():
    got = split_sentences("| 項目 | 値 |\n| --- | --- |\n| A | 1 |")
    assert len(got) == 3


def test_short_fragment_merges_forward():
    got = split_sentences("うん。とても長い説明がここに続いていて十分な長さがある。")
    assert len(got) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_span_scorer_split.py -v`
Expected: FAIL — モジュールが存在しない

- [ ] **Step 3: Write minimal implementation**

```python
# core/retrieval/span_scorer.py
"""根拠スパン解決 第2段 — 主張文⇔文の埋め込み類似(バッジ押下時のみ実行)。

設計: docs/specs/2026-08-07-citation-evidence-ui-design.md §3.1.2
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MIN_SENTENCE_CHARS = 15
_BOUNDARY_RE = re.compile(r"(?<=[。．!?！？])|\n")


@dataclass(frozen=True)
class Sentence:
    text: str
    start: int
    end: int


def split_sentences(text: str) -> list[Sentence]:
    """文単位に分割する。短い断片は次と結合して過分割(e.g. / Fig. 3)を防ぐ。"""
    pieces: list[Sentence] = []
    cursor = 0
    for m in _BOUNDARY_RE.finditer(text):
        end = m.end()
        if end <= cursor:
            continue
        pieces.append(Sentence(text=text[cursor:end], start=cursor, end=end))
        cursor = end
    if cursor < len(text):
        pieces.append(Sentence(text=text[cursor:], start=cursor, end=len(text)))

    merged: list[Sentence] = []
    for piece in pieces:
        if merged and len(merged[-1].text.strip()) < MIN_SENTENCE_CHARS:
            prev = merged.pop()
            merged.append(Sentence(text=text[prev.start : piece.end], start=prev.start, end=piece.end))
        else:
            merged.append(piece)
    return [s for s in merged if s.text.strip()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/unit/test_span_scorer_split.py -v`
Expected: PASS(5件)

- [ ] **Step 5: Commit**

```bash
git add core/retrieval/span_scorer.py tests/unit/test_span_scorer_split.py
git commit -m "feat(citations): 第2段の文分割を追加"
```

---

### Task 13: 第2段 — 埋め込み類似・許可リスト・LRU

**Files:**
- Modify: `core/retrieval/span_scorer.py`
- Test: `tests/unit/test_span_scorer_score.py`

**Interfaces:**
- Consumes: `split_sentences`(Task 12)、`core/ollama/gateway.py` の `embed(*, model: str, text: str) -> list[float]`
- Produces:
  - `MULTILINGUAL_EMBEDDING_MODELS: frozenset[str]`
  - `is_cross_language(a: str, b: str) -> bool`
  - `async score_spans(*, claim: str, chunk_text: str, chunk_id: str, gateway, model: str, cache: SpanCache) -> list[dict]`
  - `class SpanCache` — LRU(上限 256)。キーは `(chunk_id, sha1(claim), model)`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_span_scorer_score.py
import pytest

from core.retrieval.span_scorer import SpanCache, is_cross_language, score_spans


class FakeGateway:
    """文ごとに決め打ちのベクトルを返すスタブ。呼び出し回数も数える。"""

    def __init__(self, vectors: dict[str, list[float]]):
        self.vectors = vectors
        self.calls = 0

    async def embed(self, *, model: str, text: str) -> list[float]:
        self.calls += 1
        for key, vec in self.vectors.items():
            if key in text:
                return vec
        return [0.0, 1.0]


CHUNK = "Level 1 indicates outcome achievement. Level 2 requires work product management."


@pytest.mark.asyncio
async def test_returns_span_for_most_similar_sentence():
    gw = FakeGateway({"レベル2": [1.0, 0.0], "Level 2": [0.98, 0.02], "Level 1": [0.0, 1.0]})
    got = await score_spans(
        claim="レベル2では作業成果物が管理される",
        chunk_text=CHUNK,
        chunk_id="c1",
        gateway=gw,
        model="bge-m3",
        cache=SpanCache(),
    )
    assert len(got) == 1
    assert "Level 2" in got[0]["quote"]
    assert got[0]["method"] == "embedding"
    assert got[0]["ordinal"] is None


@pytest.mark.asyncio
async def test_returns_empty_when_no_sentence_stands_out():
    gw = FakeGateway({"レベル2": [1.0, 0.0], "Level 2": [0.7, 0.7], "Level 1": [0.7, 0.7]})
    got = await score_spans(
        claim="レベル2では作業成果物が管理される",
        chunk_text=CHUNK,
        chunk_id="c1",
        gateway=gw,
        model="bge-m3",
        cache=SpanCache(),
    )
    assert got == []


@pytest.mark.asyncio
async def test_skips_when_model_is_not_multilingual_and_languages_differ():
    gw = FakeGateway({"レベル2": [1.0, 0.0], "Level 2": [0.98, 0.02]})
    got = await score_spans(
        claim="レベル2では作業成果物が管理される",
        chunk_text=CHUNK,
        chunk_id="c1",
        gateway=gw,
        model="nomic-embed-text",
        cache=SpanCache(),
    )
    assert got == []
    assert gw.calls == 0  # 埋め込みを1回も呼ばない


@pytest.mark.asyncio
async def test_cache_prevents_recomputation():
    gw = FakeGateway({"レベル2": [1.0, 0.0], "Level 2": [0.98, 0.02], "Level 1": [0.0, 1.0]})
    cache = SpanCache()
    kwargs = dict(
        claim="レベル2では作業成果物が管理される",
        chunk_text=CHUNK,
        chunk_id="c1",
        gateway=gw,
        model="bge-m3",
        cache=cache,
    )
    await score_spans(**kwargs)
    first = gw.calls
    await score_spans(**kwargs)
    assert gw.calls == first


def test_cache_evicts_beyond_limit():
    cache = SpanCache(limit=2)
    cache.put(("a", "1", "m"), [])
    cache.put(("b", "1", "m"), [])
    cache.put(("c", "1", "m"), [])
    assert cache.get(("a", "1", "m")) is None
    assert cache.get(("c", "1", "m")) is not None


def test_is_cross_language():
    assert is_cross_language("レベル2では管理される", "Level 2 requires management.")
    assert not is_cross_language("レベル2では管理される", "レベル2の要求事項")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/unit/test_span_scorer_score.py -v`
Expected: FAIL — `ImportError: cannot import name 'score_spans'`

- [ ] **Step 3: Write minimal implementation**

`core/retrieval/span_scorer.py` の末尾に追記する。

```python
import hashlib
import math
from collections import OrderedDict
from typing import Any, Protocol

from core.generation.evidence_spans import cjk_ratio

MULTILINGUAL_EMBEDDING_MODELS = frozenset(
    {"bge-m3", "bge-m3:latest", "multilingual-e5-large", "paraphrase-multilingual"}
)
MAX_SPANS = 3
# 相対判定: 最上位が2位より有意に離れているか。絶対閾値だけに頼らない
# (コサイン類似度の分布はモデルごとに異なるため)。
MIN_MARGIN = 0.05
MIN_ABSOLUTE = 0.30
CJK_LANGUAGE_THRESHOLD = 0.3


class EmbedGateway(Protocol):
    async def embed(self, *, model: str, text: str) -> list[float]: ...


def is_cross_language(a: str, b: str) -> bool:
    """2つのテキストの主体言語が異なるか(CJK 比率で判定)。"""
    return (cjk_ratio(a) >= CJK_LANGUAGE_THRESHOLD) != (cjk_ratio(b) >= CJK_LANGUAGE_THRESHOLD)


def _is_multilingual(model: str) -> bool:
    base = model.split(":")[0]
    return model in MULTILINGUAL_EMBEDDING_MODELS or base in MULTILINGUAL_EMBEDDING_MODELS


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class SpanCache:
    """(chunk_id, sha1(claim), model) → spans の LRU キャッシュ。"""

    def __init__(self, limit: int = 256):
        self.limit = limit
        self._store: OrderedDict[tuple[str, str, str], list[dict[str, Any]]] = OrderedDict()

    def get(self, key: tuple[str, str, str]) -> list[dict[str, Any]] | None:
        if key not in self._store:
            return None
        self._store.move_to_end(key)
        return self._store[key]

    def put(self, key: tuple[str, str, str], value: list[dict[str, Any]]) -> None:
        self._store[key] = value
        self._store.move_to_end(key)
        while len(self._store) > self.limit:
            self._store.popitem(last=False)


async def score_spans(
    *,
    claim: str,
    chunk_text: str,
    chunk_id: str,
    gateway: EmbedGateway,
    model: str,
    cache: SpanCache,
) -> list[dict[str, Any]]:
    """主張文に意味的に近い文を最大 MAX_SPANS 件返す。根拠の保証はない。"""
    key = (chunk_id, hashlib.sha1(claim.encode("utf-8")).hexdigest(), model)
    cached = cache.get(key)
    if cached is not None:
        return cached

    if is_cross_language(claim, chunk_text) and not _is_multilingual(model):
        cache.put(key, [])
        return []

    sentences = split_sentences(chunk_text)
    if not sentences:
        cache.put(key, [])
        return []

    claim_vec = await gateway.embed(model=model, text=claim)
    scored: list[tuple[float, Sentence]] = []
    for s in sentences:
        vec = await gateway.embed(model=model, text=s.text)
        scored.append((_cosine(claim_vec, vec), s))
    scored.sort(key=lambda p: p[0], reverse=True)

    top = scored[0][0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if top < MIN_ABSOLUTE or (top - runner_up) < MIN_MARGIN:
        cache.put(key, [])
        return []

    # 採用は「最上位が2位から有意に離れている」ことを条件に、絶対値も満たす上位のみ。
    spans = [
        {
            "answer_occurrence": -1,  # 呼び出し側が実際の出現位置で上書きする
            "ordinal": None,
            "start": s.start,
            "end": s.end,
            "quote": s.text,
            "method": "embedding",
        }
        for score, s in scored[:MAX_SPANS]
        if score >= MIN_ABSOLUTE
    ]
    cache.put(key, spans)
    return spans
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/unit/test_span_scorer_score.py -v`
Expected: PASS(6件)

- [ ] **Step 5: Commit**

```bash
git add core/retrieval/span_scorer.py tests/unit/test_span_scorer_score.py
git commit -m "feat(citations): 第2段の埋め込み類似・多言語許可リスト・LRUを追加"
```

---

### Task 14: 第2段の API とストリーム中ガード

**Files:**
- Modify: `apps/api/routers/chat.py`
- Modify: `apps/api/schemas/chat.py`
- Test: `tests/integration/test_span_resolve_endpoint.py`

**Interfaces:**
- Consumes: `score_spans` / `SpanCache`(Task 13)、`iter_claim_occurrences`(Task 1)
- Produces: `POST /api/messages/{message_id}/citations/{n}/spans`
  - リクエスト: `{"answer_occurrence": int}`
  - レスポンス: `{"spans": [EvidenceSpan], "method": "embedding"}`
  - 生成ストリーム実行中は `409`(FE は完了後に再試行)、15 秒でタイムアウトし `{"spans": []}`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_span_resolve_endpoint.py
"""第2段エンドポイントの契約。既存の統合テストの client フィクスチャを使う。"""


def test_returns_empty_spans_for_unknown_message(client):
    res = client.post("/api/messages/does-not-exist/citations/1/spans", json={"answer_occurrence": 0})
    assert res.status_code == 404


def test_returns_spans_shape(client, seeded_message_id):
    res = client.post(
        f"/api/messages/{seeded_message_id}/citations/1/spans",
        json={"answer_occurrence": 0},
    )
    assert res.status_code in (200, 409)
    if res.status_code == 200:
        body = res.json()
        assert body["method"] == "embedding"
        for span in body["spans"]:
            assert span["ordinal"] is None
            assert span["method"] == "embedding"
            assert span["answer_occurrence"] == 0


def test_conflicts_while_stream_running(client, seeded_message_id, running_stream):
    res = client.post(
        f"/api/messages/{seeded_message_id}/citations/1/spans",
        json={"answer_occurrence": 0},
    )
    assert res.status_code == 409
```

> `client` / `seeded_message_id` / `running_stream` は既存の統合テストに合わせて用意する。
> 生成中フラグは `apps/api/main.py` かルータのモジュール状態で管理しているものを使う。無ければ
> 「実行中の会話 id 集合」を持つ小さなレジストリをルータに足す。

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --no-sync pytest tests/integration/test_span_resolve_endpoint.py -v`
Expected: FAIL — 404 ではなくルート未定義エラー

- [ ] **Step 3: Write minimal implementation**

```python
# apps/api/schemas/chat.py に追記
class ResolveSpansRequest(BaseModel):
    answer_occurrence: int


class ResolveSpansResponse(BaseModel):
    spans: list[EvidenceSpan]
    method: str = "embedding"
```

```python
# apps/api/routers/chat.py に追記
import asyncio

from fastapi import HTTPException

from core.generation.evidence_spans import iter_claim_occurrences
from core.retrieval.span_scorer import SpanCache, score_spans

_SPAN_CACHE = SpanCache()
SPAN_RESOLVE_TIMEOUT_SEC = 15


@router.post("/messages/{message_id}/citations/{n}/spans", response_model=ResolveSpansResponse)
async def resolve_spans(message_id: str, n: int, body: ResolveSpansRequest, ...):
    message = messages_repo.get(conn, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="message not found")
    if is_stream_running(message.conversation_id):
        # 生成中は VRAM を取り合うため実行しない(翻訳と同じ扱い)
        raise HTTPException(status_code=409, detail="generation in progress")

    citation = next((c for c in message.citations if c.get("n") == n), None)
    if citation is None:
        return ResolveSpansResponse(spans=[])

    occurrence = next(
        (
            o
            for o in iter_claim_occurrences(message.content)
            if o.n == n and o.answer_occurrence == body.answer_occurrence
        ),
        None,
    )
    if occurrence is None:
        return ResolveSpansResponse(spans=[])

    claim = occurrence.claim
    if len(claim) < 20:
        # 主張文が短すぎる場合のみ、この回答を生んだ user メッセージにフォールバックする
        claim = previous_user_message_content(conn, message) or claim

    chunk = chunks_repo.get(conn, citation["chunk_id"])
    if chunk is None:
        return ResolveSpansResponse(spans=[])

    try:
        spans = await asyncio.wait_for(
            score_spans(
                claim=claim,
                chunk_text=chunk.text,
                chunk_id=citation["chunk_id"],
                gateway=embed_gateway,
                model=settings.ollama.embedding_model,
                cache=_SPAN_CACHE,
            ),
            timeout=SPAN_RESOLVE_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        return ResolveSpansResponse(spans=[])

    return ResolveSpansResponse(
        spans=[{**s, "answer_occurrence": body.answer_occurrence} for s in spans]
    )
```

> `conn` / `embed_gateway` / `settings` の受け取り方、`chunks_repo.get` の正確な名前は
> 同ファイル内の既存エンドポイントに倣うこと。`is_stream_running` /
> `previous_user_message_content` が無ければこのルータ内に小さく実装する。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --no-sync pytest tests/integration/test_span_resolve_endpoint.py -v && uv run --no-sync pytest -q`
Expected: 新規 PASS、既存の回帰なし

- [ ] **Step 5: Commit**

```bash
git add apps/api/routers/chat.py apps/api/schemas/chat.py tests/integration/test_span_resolve_endpoint.py
git commit -m "feat(citations): 第2段の遅延解決エンドポイントを追加"
```

---

### Task 15: FE — 第2段の遅延解決と「関連」表示

**Files:**
- Create: `apps/web/src/lib/api/spans.ts`
- Modify: `apps/web/src/lib/components/SourceViewer.svelte`
- Test: `apps/web/tests/unit/spansApi.test.ts`(新規)

**Interfaces:**
- Consumes: Task 14 のエンドポイント、`splitBySpans`(Task 8)
- Produces: `resolveSpans(messageId: string, n: number, answerOccurrence: number): Promise<EvidenceSpan[]>`

**Notes:** `selectedCitation` に `messageId` を足す必要がある(Task 9 の型を `{ citation, answerOccurrence, messageId }` に拡張し、`ChatMessage` から `message.id` を渡す)。

- [ ] **Step 1: Write the failing test**

```ts
// apps/web/tests/unit/spansApi.test.ts
import { afterEach, describe, expect, it, vi } from 'vitest';
import { resolveSpans } from '../../src/lib/api/spans';

afterEach(() => vi.unstubAllGlobals());

describe('resolveSpans', () => {
  it('spans を返す', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        json: async () => ({
          method: 'embedding',
          spans: [
            {
              answer_occurrence: 0,
              ordinal: null,
              start: 1,
              end: 5,
              quote: 'abcd',
              method: 'embedding',
            },
          ],
        }),
      })),
    );
    const got = await resolveSpans('m1', 3, 0);
    expect(got).toHaveLength(1);
    expect(got[0].method).toBe('embedding');
  });

  it('409(生成中)では空配列を返して例外を投げない', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 409 })));
    await expect(resolveSpans('m1', 3, 0)).resolves.toEqual([]);
  });

  it('その他のエラーでも空配列を返す(閲覧を妨げない)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500 })));
    await expect(resolveSpans('m1', 3, 0)).resolves.toEqual([]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/web && npx vitest run tests/unit/spansApi.test.ts`
Expected: FAIL — モジュールが存在しない

- [ ] **Step 3: Write minimal implementation**

```ts
// apps/web/src/lib/api/spans.ts
import type { EvidenceSpan } from '$lib/api/types';

/**
 * 第2段(埋め込み類似)の遅延解決。
 * 失敗しても閲覧を妨げないよう、例外を投げず空配列を返す。
 */
export async function resolveSpans(
  messageId: string,
  n: number,
  answerOccurrence: number,
): Promise<EvidenceSpan[]> {
  try {
    const res = await fetch(`/api/messages/${messageId}/citations/${n}/spans`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ answer_occurrence: answerOccurrence }),
    });
    if (!res.ok) return [];
    const body = await res.json();
    return body.spans ?? [];
  } catch {
    return [];
  }
}
```

`SourceViewer.svelte` — 第1段が空のときだけ第2段を呼ぶ。

```svelte
  import { resolveSpans } from '$lib/api/spans';

  let lazySpans = $state<EvidenceSpan[]>([]);
  let resolving = $state(false);

  $effect(() => {
    const sel = selectedCitation;
    lazySpans = [];
    if (!sel || (sel.citation.spans ?? []).length > 0) return;
    resolving = true;
    resolveSpans(sel.messageId, sel.citation.n, sel.answerOccurrence)
      .then((spans) => (lazySpans = spans))
      .finally(() => (resolving = false));
  });

  const activeSpans = $derived(
    selectedCitation && selectedCitation.citation.chunk_id === selectedChunkId
      ? (selectedCitation.citation.spans ?? []).length > 0
        ? selectedCitation.citation.spans!
        : lazySpans
      : [],
  );
  const isRelated = $derived(activeSpans.some((s) => s.method === 'embedding'));
```

```svelte
{#if resolving}
  <p class="resolving"><Spinner /> 根拠箇所を探しています…</p>
{:else if isRelated}
  <p class="unresolved">
    根拠箇所は特定できませんでした。この主張に関連する箇所を示しています
  </p>
{:else if unresolved}
  <p class="unresolved">この主張の根拠箇所は特定できませんでした</p>
{/if}
```

`<mark>` は method で見た目を分ける。

```svelte
<mark class={`ev ${seg.span.method === 'embedding' ? 'related' : ''} ${seg.active ? 'active' : ''}`}
  title={seg.span.method === 'embedding' ? 'この主張に関連する箇所(根拠の保証はありません)' : undefined}
>{seg.text}{#if seg.span.method === 'embedding'}<span class="rel-chip">関連</span>{/if}</mark>
```

```css
  .text :global(mark.ev.related) {
    background: linear-gradient(transparent 62%, rgba(107, 107, 107, 0.12) 62%);
    border-bottom: 2px dashed var(--color-fg-muted);
  }
  .text :global(.rel-chip) {
    font-size: 9px;
    color: var(--color-fg-muted);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 0 3px;
    margin-left: 3px;
    vertical-align: 1px;
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/web && npx vitest run tests/unit/spansApi.test.ts && npm run test:unit && npm run build`
Expected: すべて PASS、ビルド成功

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/lib/api/spans.ts apps/web/src/lib/components/SourceViewer.svelte apps/web/src/lib/components/ChatMessage.svelte apps/web/tests/unit/spansApi.test.ts
git commit -m "feat(web): 根拠未特定時に関連箇所を遅延解決して破線で示す"
```

---

### Task 16: Phase 1.5 ゲート — 偽陽性率の実測(コード変更なし)

**Files:** なし(検証のみ)

**Interfaces:**
- Consumes: Task 12–15 の成果
- Produces: 偽陽性率の実測値。**20% を超えたら第2段を既定 OFF に倒す**

- [ ] **Step 1: 隔離環境に英語 PDF を1本取り込む**

Task 11 と同じ隔離 data_dir / ポート 8799 を使う。

- [ ] **Step 2: 日本語で 20 問質問する**

質問は事実確認型(「〜の定義は」「〜の要件は」)を中心にする。

- [ ] **Step 3: 光った箇所を目視分類**

各バッジを押し、破線で示された箇所を「主張に関連する / 無関係」に分類して記録する。

- [ ] **Step 4: 判定**

無関係の割合が **20% を超えたら**、第2段を既定 OFF(ベータフラグ配下)に移す。閾値
(`MIN_MARGIN` / `MIN_ABSOLUTE`)の調整で 20% 以下に収まるならそれを採用する。

- [ ] **Step 5: 待ち時間の計測**

Ollama から埋め込みモデルをアンロードした状態で1回目のバッジ押下を計測し、15 秒
タイムアウトに収まるか確認する。収まらないならタイムアウト値を見直す。

- [ ] **Step 6: スクリーンショットと記録**

evaluator で「関連箇所の破線表示＋注記」を撮影し、実測値とあわせて記録する。

---

## 次の計画(この計画の範囲外)

Phase 1.5 のゲート通過後、以下を別計画として書く。

- **Phase 2**: 表・図の bbox 矩形 + 原本タブ(`core/sources/page_render.py`、`GET /api/sources/{id}/pages/{page}`)
- **Phase 3**: β quote モード(`citation_quote_mode` フラグ、生成プロンプト拡張)→ §6 オープン ADR 4 の判断材料
- **Phase 4**: 通常テキストの `search_for` 矩形(ハイフネーション時のフォールバック含む)
- **Phase 5**: 選択範囲翻訳(`POST /api/translate`、`core/translation/translator.py`)

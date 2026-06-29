# Sprint 9 / Task 9.2 — Megaphone Icon Size 最終調整

判定: **KEEP_18PX** / chosen_size_px: **18**
実施: 2026-06-29
spec: `docs/specs/notebook-ollama-design.md` §5.1
対象: `apps/web/src/lib/components/AppHeader.svelte`

## 結論

Spec で「サイズ: 18px (Sprint 5 の実機検証で歯車18pxと並べたとき違和感あれば16/20pxへ調整)」と
明記されている通り、**18px が最適**。Megaphone と Settings (gear) を 18px で揃えると
両者がペアのアイコンとして読める。16px / 20px はどちらも非対称となり、
どちらかのアイコンが「弱く / 強く」見える違和感が出る。

## 検証手順

1. 既存実装 (Megaphone size=18, Settings size=18) で SPA をビルドし、`uvicorn --port 8765` で配信
2. ビューポート 1920×1080 で `http://127.0.0.1:8765/` を開く
3. ヘッダ全幅と `.actions` 拡大の 2 種類でスクリーンショット
4. `AppHeader.svelte` を 16 / 20 に書き換え → `npm run build` → ブラウザリロード → スクリーンショット
   (DOM `getBoundingClientRect()` と `<svg width>` 属性で実描画サイズが切り替わったことを毎回確認)
5. 最後に 18px へ戻して再ビルド、`svelte-check` で 0 errors を確認

## 計測値 (Playwright `getBoundingClientRect`)

| サイズ | Megaphone svg | Settings svg | ボタン hit area | 並びgap |
|---|---|---|---|---|
| 16px | 16×16 | 18×18 | 34×34 (Megaphone), 34×34 (Settings) | `--space-3` |
| **18px (current)** | **18×18** | **18×18** | 34×34 / 34×34 | `--space-3` |
| 20px | 20×20 | 18×18 | 36×36 (Megaphone), 34×34 (Settings) | `--space-3` |

## 視覚比較

ヘッダ全幅 (1920px 表示の右端付近):

- 18px: `icon-size-18px.png`
- 16px: `icon-size-16px.png`
- 20px: `icon-size-20px.png`

アクション領域だけの拡大 (より判定しやすい):

- 18px: `closeup-18px.png` ← peer-pair として整って見える
- 16px: `closeup-16px.png` ← Megaphone が歯車より明らかに小さく見える
- 20px: `closeup-20px.png` ← Megaphone が歯車を上回るサイズで「未読を主張しすぎ」

## 観察

- **16px**: Megaphone が gear より一段小さく、ペアとして組まれていない印象。
  特に未読 badge-dot (6px) が icon に対して比率的に目立ちすぎ、icon が badge に
  圧倒される。「お知らせ」が二次的アクションに見えてしまう。
- **18px (current)**: gear と幾何的に等しいので並べた時にツールバー然とした統一感がある。
  両アイコンとも 34×34 の hit area に収まり、tap target 推奨 (Material/HIG の 24-32pt) を満たす。
  `--space-3` のギャップで隣接アイコンとの衝突なし。1920×1080 ディスプレイで容易に
  クリック分離可能。
- **20px**: Megaphone だけが大きく、Settings との非対称が逆方向に発生。Megaphone が
  ヘッダ右上で重く見え、首尾一貫性が崩れる。Sprint 9 で扱う「常時表示の通知アイコン」
  としては主張過多。

## エラー類

- console error: なし (検証中の `browser_console_messages` で 0 件)
- network: GET `/api/notebooks/.../events` は 200 OK (uvicorn ログで確認)
- `npm run check`: **0 errors**, 13 warnings (すべて既存・本変更と無関係)

## 最終状態

- `apps/web/src/lib/components/AppHeader.svelte`: `<Megaphone size={18} strokeWidth={1.75} />` のまま (変更なし)
- `apps/web/dist/`: 18px で再ビルド済み

## 証拠ファイル一覧

- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-29-feedback-hub-sprint9\icon-size-18px.png`
- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-29-feedback-hub-sprint9\icon-size-16px.png`
- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-29-feedback-hub-sprint9\icon-size-20px.png`
- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-29-feedback-hub-sprint9\closeup-18px.png`
- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-29-feedback-hub-sprint9\closeup-16px.png`
- `E:\00_Git\10_NotebookOllama\docs\eval\2026-06-29-feedback-hub-sprint9\closeup-20px.png`

## must_fix

なし。spec の「期待サイズ 18px」と実機判定が一致したため、ソース変更不要。

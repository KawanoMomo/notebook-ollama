---
type: spec
title: クラッシュレポート & お知らせ/フィードバックハブ
summary: "クラッシュ報告+お知らせ+ご意見を拡声器アイコンのハブに統合しGitHubへ届ける。"
aliases:
  - フィードバックハブ
  - クラッシュレポート
status: approved
status_inferred: true
date: 2026-06-28
project: NotebookOllama
area: feedback
tags:
  - spec
related:
  - "[[notebook-ollama-design]]"
---

# クラッシュレポート & お知らせ/フィードバックハブ — 設計仕様

- 対象プロジェクト: `10_NotebookOllama`
- 作成日: 2026-06-28
- 関連メモリ: [[feedback-no-data-guarantee-in-ui]], [[feedback_visual_verification]], [[feedback_compact_ui_repurpose_affordance]]
- 関連spec: `2026-05-19-notebook-ollama-design.md`

---

## 1. 概要

NotebookOllama を公開した後、エンドユーザー側で発生したエラーや要望を、開発者(KawanoMomo)の GitHub リポジトリへ届ける手段を提供する。「クラッシュレポート」単独機能ではなく、「お知らせ」「不具合を報告」「ご意見・ご要望」を1つのハブに統合する設計とする。アイコンは将来通知用途に拡張可能な **拡声器 (Megaphone)** とし、エンドユーザー(非エンジニア)にも違和感なく届くUIとする。

## 2. ゴール

- ユーザー側で発生した未捕捉例外・プロセスクラッシュを開発者へ届ける経路を作る
- 完全無料で運用できる(SaaS 月額課金を発生させない)
- ユーザーが送信内容を**目視確認・編集**してから送信する合意モデルを採用する(プライバシ・法的リスク回避)
- 公開アプリへの**PAT埋め込みを行わない**(GitHub Issue起票URLプリフィルで完結)
- 同じバグのスパム重複を抑制する
- 旗ハブ統合の将来拡張(運営お知らせ・任意フィードバック)に耐える設計とする

### 2.1 捕捉範囲の補足(2026-07-26 追補、実機FB由来)

- **SIGINT/SIGTERM はクラッシュとして記録しない。** ローカル運用ではこれらが通常の
  停止手段であり、記録すると停止のたびに未送信レポートが増える(実機で未送信7件が
  全て Ctrl+C 由来だった)。ハンドラを通らずに死んだ本当の異常終了は
  `running.lock` の unclean shutdown 検知(trap ④)が拾うため、検知漏れにはならない
- **捕捉済みエラー(取り込み失敗等)は引き続き自動収集の対象外。** ただしユーザーから
  見れば報告したい不具合そのものなので、失敗したソース行から内容を事前入力した
  レポートのプレビューを開けるようにする(`buildSourceErrorCrash`)。収集するのは
  ソース種別・拡張子・ステータス・エラー文言のみで、ファイル名や本文は載せない
  (§6 のホワイトリスト方針を踏襲)

## 3. 非ゴール

- 自動送信(ユーザー操作なしの送信)は行わない
- Sentry/GlitchTip 等の自前ホストサービスは導入しない
- 双方向の Issue 同期(返信通知等)は当面実装しない
- マルチユーザー認証・複数デバイス同期は行わない(個人ローカルアプリ)

## 4. 全体アーキテクチャ

### 4.1 データフロー (クラッシュ自動検知)

```
[エラー発生]
  ├─ ① FastAPI例外ハンドラ
  ├─ ② sys.excepthook + atexit
  ├─ ③ signal handler (SIGTERM/INT)
  ├─ ④ 起動時 unclean shutdown 検知 (running.lock + psutil)
  └─ ⑤ フロント window.onerror / unhandledrejection
       ↓
  [Hardware Collector] ハードウェア情報採取 (psutil + nvidia-smi)
       ↓
  [Redactor] ホワイトリスト方式で経路から除外 (RAGチャンク・ドキュメントは収集しない)
       ↓
  [Fingerprint] スタックトレース SHA1
       ↓ (reported.txt と照合)
  [PendingStore] ~/.notebook-ollama/crash-pending/<id>.json
       ↓
  [Frontend 即時モーダル / 起動時pendingモーダル]
       ↓
  [Preview Editor] ユーザーが編集
       ↓
  [Formatter → PrefillURL Builder] (8KB制限対応)
       ↓
  [ブラウザを別タブで開く] github.com/KawanoMomo/notebook-ollama/issues/new?title=&body=&labels=
       ↓
  [ユーザーが GitHub で Submit]
       ↓
  [ローカルに reported flag + fingerprint 記録]
```

### 4.2 データフロー (手動: 旗ハブ)

```
[ヘッダの旗アイコンクリック]
       ↓
[右側 Drawer (440px) を開く]
       ↓
[3タブ: お知らせ / 不具合 / ご意見]
       ↓
  ├ お知らせタブ → 既読フラグ更新 (localStorage)
  ├ 不具合タブ → 未送信レポート一覧 + 新規報告作成
  └ ご意見タブ → 種別・本文・感情・スクショ
       ↓
[Preview Editor] (不具合/ご意見の場合)
       ↓
[ブラウザでGitHub Issue/Discussion起票]
```

### 4.3 モジュール分割

#### バックエンド (Python)

```
core/crash_reporter/        # 純粋ロジック (FastAPI非依存)
├── __init__.py
├── collector.py            # ①②③④traps統合のregister()
├── hardware.py             # CPU/RAM/GPU情報採取
├── redactor.py             # ホワイトリスト方式PII除外
├── fingerprint.py          # スタックトレースSHA1
├── pending_store.py        # ~/.notebook-ollama/crash-pending/管理
├── reported_store.py       # 送信済みfingerprintリスト
├── formatter.py            # GitHub Issue Markdown生成
├── prefill_url.py          # 8KB制限対応URL Builder
└── lifecycle.py            # running.lock + psutil

core/feedback_hub/          # ハブ機能 (将来拡張領域)
├── __init__.py
├── notice_store.py         # お知らせデータ管理 (現MVPは静的JSON)
└── feedback_formatter.py   # ご意見・ご要望のMarkdown生成

apps/api/routers/
├── crash.py                # /api/crash/*
└── feedback_hub.py         # /api/feedback-hub/*
```

#### フロントエンド (SvelteKit)

```
apps/web/src/lib/
├── components/
│   ├── FeedbackHubDrawer.svelte            # 右側drawerの枠+タブ
│   ├── feedback-hub/
│   │   ├── NoticesTab.svelte               # お知らせ (timeline)
│   │   ├── BugReportTab.svelte             # 不具合報告 (未送信list+新規)
│   │   └── FeedbackTab.svelte              # ご意見 (種別+textarea+感情+スクショ)
│   ├── CrashDetectionModal.svelte          # 自動検知時の即時モーダル
│   ├── CrashPreviewDialog.svelte           # 送信内容プレビュー編集
│   └── OptInDialog.svelte                  # 初回オプトイン
├── stores/
│   ├── feedbackHub.svelte.ts               # drawer開閉/タブ状態
│   ├── crashReports.svelte.ts              # 未送信レポート一覧
│   └── notices.svelte.ts                   # お知らせ既読状態 (localStorage)
└── utils/
    ├── errorBoundary.ts                    # window.onerror統合
    └── screenshotCapture.ts                # html2canvas wrapper
```

## 5. 設計詳細

### 5.1 ヘッダの旗 (Megaphone) アイコン

- ライブラリ: `@lucide/svelte` の `Megaphone`
- サイズ: 18px (Sprint 5 の実機検証で歯車18pxと並べたとき違和感あれば16/20pxへ調整)
- stroke-width: 1.75
- 色: `var(--color-fg-muted)`、hover時 `var(--color-fg)`
- ヘッダ右端、既存 Settings 歯車アイコンの**左隣**に配置
- ツールチップ: 「お知らせ・フィードバック」
- **未読バッジ**: 右上 6px × 6px 円形、`#ef4444`、`box-shadow: 0 0 0 2px #fff` で白リング
  - 表示条件: お知らせ未読数 + 未送信クラッシュレポート数 > 0
  - 数値ではなくドットのみ(モダン慣例)
- クリックで右側 Drawer を開く

### 5.2 右側 Drawer (3タブハブ)

- 幅: 440px、フル高さ
- 背景: `#fff`、`box-shadow: -8px 0 32px rgba(11, 13, 18, 0.08)`
- 背景クリックで閉じる(backdrop `rgba(11, 13, 18, 0.35)`)
- ESCで閉じる(既存 `Modal.svelte` と同じパターン)
- ドロワーヘッダ: タイトル「お知らせ・フィードバック」(font-size 18px / font-weight 600 / letter-spacing -0.01em)
- 3タブ (underline tab):
  - お知らせ
  - 不具合
  - ご意見
- 各タブには未読/未送信数を pill (`background: #e5e7eb`、active 時 `#0b0d12`/`#fff`) で表示。0件時は非表示。

### 5.3 お知らせタブ (Linear式 timeline)

参考: deep-research finding 1, 2 (Linear/Vercel changelog、verifier 3-0)

- レイアウト: 単一カラム縦timeline、カードグリッドは使わない
- 日付ヘッダ:
  - font-size 12px、font-weight 500、color `#6b7280`、text-transform uppercase、letter-spacing 0.06em
  - 上下に 32px の空白 + 下に 1px solid `#e5e7eb`
  - 表記: 「2026年6月25日」(混在禁止、和暦表記で統一)
- エントリ:
  - タイトル: font-size 15px、font-weight 600、letter-spacing -0.01em
  - 本文: font-size 14px、font-weight 400、color `#374151`、line-height 1.65
  - サブセクション見出し (例: 「新機能」「改善」): font-size 11px、font-weight 600、uppercase、letter-spacing 0.06em、color `#6b7280`
  - 箇条書き: padding-left 18px、line-height 1.7
- 未読マーカー: タイトル左に直径6px の `#3b82f6` ドット、`::before` 疑似要素
- 色付きバッジタグは**使わない** (タイポと spacing で階層を作る)
- 既読管理: localStorage に `seen_notice_ids: string[]` を保持
- お知らせ取得: バックエンドの静的JSON `data/notices.json` を返す(MVP)。将来は管理画面付きの REST に拡張可能。

### 5.4 不具合を報告タブ

- 冒頭の説明文 (font-size 13px、color `#6b7280`、line-height 1.6):
  > 「アプリで発生したエラーを開発者に報告できます。送信前にプレビューで内容を確認・編集できます。」
- 「未送信のレポート」セクション見出し (font-size 11px、font-weight 600、uppercase)
- レポートリスト:
  - 各項目に: 例外型名(`#ef4444` font-weight 600)、エラー詳細(monospace 11px)、ファイルパス(monospace 11px)、発生日時(color `#9ca3af`)
  - 右側に「却下」(ghost button) と「プレビュー →」(primary button)
  - 区切り: 1px solid `#e5e7eb`
- 「手動で新規報告を作成」セクション:
  - dashed border 12px radius、`#fafafa` 背景のカード
  - 中央に Clock アイコン、説明文、「+ 新規報告を作成」 secondary button
  - クリックで空白の Preview Editor が起動

### 5.5 ご意見・ご要望タブ

参考: deep-research finding 6 (Featurebase/Sentry/Usersnap、verifier 3-0)

#### 5.5.1 種別チップ (horizontal toggle group)

- 3つのチップ: 「機能要望」「使いにくさ」「感想」
- 各チップ: padding 6px 12px、border-radius 8px、font-size 13px、font-weight 500
- 非選択: `bg: #fff`、`color: #4b5563`、`border: 1px solid #d1d5db`
- 選択: `bg: #0b0d12`、`color: #fff`、`border-color: #0b0d12`
- アイコン (Lucide, 14px) を先頭に: CheckSquare / AlertCircle / MessageSquare

#### 5.5.2 本文 textarea

- min-height: 120px
- padding: 12px 14px、font-size: 14px、border-radius: 10px
- placeholder: 種別に応じて具体例を出す(例: 「ノートブック作成時にテンプレートを選べると便利です。会議録音ノート、調査ノート、読書メモなど...」)
- focus 時: border-color `#0b0d12`

#### 5.5.3 感想入力 (Thumbs 3段階)

- レイアウト: 3つの正方形ボタン(44×44px、border-radius 10px、gap 6px)
- アイコン (Lucide):
  - ThumbsUp
  - **Minus (─)** ← 中立(deep-research反映: 横向きthumbは侮辱解釈リスクあり)
  - ThumbsDown
- 非選択: `border: 1px solid #d1d5db`、`color: #4b5563`、`bg: #fff`
- hover: `border-color: #9ca3af`、`color: #0b0d12`
- 選択: `bg: #0b0d12`、`border-color: #0b0d12`、`color: #fff`
- ラベル: 「使ってみた感想」(font-size 12px、font-weight 600)
- ヘルプ文: 「任意です。回答しなくても送信できます。」(font-size 11px、color `#6b7280`)

#### 5.5.4 スクショ添付 (任意)

- dashed border のカード、`bg: #fafafa`
- 左: Lucide `Image` アイコン + 「スクリーンショットを追加」
- 右: 「選択」secondary button
- 動作:
  - クリックでファイル選択ダイアログ
  - drag-and-drop でも受け付け
  - **「現在の画面を自動キャプチャ」**ボタンで html2canvas を起動し、現在のNotebookOllama画面のスクショを取得
- ヘルプ文: 「ドラッグ&ドロップ、またはクリックで選択。アプリ画面の現在の状態も自動キャプチャできます。」
- 取得したスクショはサムネイル表示 + 削除ボタン

#### 5.5.5 フッタアクション

- 「キャンセル」(ghost) と 「送信内容をプレビュー →」(primary)
- ドロワー下部、`border-top: 1px solid #e5e7eb`

### 5.6 クラッシュ自動検知モーダル (即時フロー)

旗ハブとは独立のフロー。①②③⑤ いずれかが発火したとき、即座に中央モーダル表示。

- Modal.svelte (既存コンポーネント) ベース、min-width 480px
- ヘッダ: 「⚠ エラーが発生しました」(color `#ef4444`)
- 本文:
  - エラー概要 (monospace 12px、`border-left: 3px solid #ef4444`)
  - 案内文(ニュートラル): 「このエラーを開発者に報告できます。**次の画面で送信内容のプレビューが表示されます。**内容を確認・編集してから送信できます。」
  - **「送信される/されない」リストは表示しない** ([[feedback-no-data-guarantee-in-ui]])
- アクション:
  - 「今は送らない」(secondary、左)
  - 「送信内容をプレビュー →」(primary、右)

### 5.7 プレビュー編集画面 (Preview Dialog)

- 大型モーダル(min-width 720px、max-height 92%)
- 中央配置(drawer内ではなく、drawerより上のzレイヤ)
- 構成:
  - タイトル input (編集可能)
  - ラベル chips (`crash-auto` `needs-triage` などプリセット、追加/削除可)
  - 本文 textarea (Markdown、monospace、min-height 320px、編集可能)
  - フッタ: 「却下」(ghost、左) / 「クリップボードにコピー」(secondary) / 「GitHubで開く →」(primary)
- 「GitHubで開く」クリックで `window.open(prefillUrl, '_blank')`
- 同時にローカルに `reported` フラグと fingerprint を記録

### 5.8 設定画面のセクション

`/settings` ページに「クラッシュレポート」セクションを追加(Ollama/プロンプト等と並列):

- セクション見出し: Megaphone アイコン + 「クラッシュレポート」 + 「NEW」バッジ(初回のみ)
- 説明文: 「エラー発生時、GitHubに不具合を報告できる機能です。送信前にプレビュー画面で内容を確認・編集できます。」
- 行1: 「クラッシュレポート機能を有効にする」toggle
- 行2: 「エラー発生時に自動でダイアログを表示」toggle (無効でもヘッダの旗から手動可)
- 行3: 「未送信レポート」 + 件数 badge + 「確認 →」button
- 行4: 「サンプルレポートを見る」 + 「プレビューを開く」button

### 5.9 初回オプトイン

アプリ初回起動時、または機能有効化前にエラー発生時、オプトインモーダル表示:

- タイトル: 「クラッシュレポート機能」
- 本文:
  - 「NotebookOllamaでエラーが発生したとき、開発者に不具合情報を報告できます。」
  - 「**送信前にプレビューが表示され、内容を確認・編集してから送信できます。**報告は任意です。」
  - 動作詳細は `<details>` で折り畳み(「動作の詳細を見る」)
- アクション: 「後で決める」(secondary) / 「有効にする」(primary)
- 「常に無効」は出さない(あとで設定画面から変更可能)

## 6. プライバシ / 法的リスク回避の原則

### 6.1 「送信される/されない」をUIで宣言しない

[[feedback-no-data-guarantee-in-ui]] 準拠。UIに保証文言を出さず、ユーザーがプレビューで実内容を確認・編集して合意したもののみが送信される合意モデルに統一する。

### 6.2 ホワイトリスト方式 Redactor

ブラックリスト(あとから伏字化)ではなく、**最初から検疫済みの内部状態のみ通す**。

#### 通す (ホワイトリスト)

**ハードウェア・環境**:
- CPU モデル名・コア数・スレッド数 (`platform.processor()`, `os.cpu_count()`)
- RAM 合計・利用可能 (`psutil.virtual_memory()`)
- GPU モデル名・VRAM・ドライババージョン (`nvidia-smi --query-gpu=name,memory.total,driver_version`)
  - **CUDA バージョンは Sprint 1 では採取しない** (上記クエリでは返らず、`nvidia-smi` ヘッダ行から best-effort で抜く実装は将来追加可能。adversarial-review 2026-06-28 option b)
- アーキテクチャ・OS バージョン (`platform.machine()`, `platform.platform()`)
- アプリ/Python/Node ビルド情報
- ディスク空き容量 (パスは除外、数値のみ)

**構造化ログのフィールド**:
- `level`, `event_name`, `timestamp`, `request_id`
- `method`, `path_pattern` (`{id}` プレースホルダのまま、クエリ・ボディなし)
- `status_code`, `duration_ms`
- `exception_type`, `exception_module`
- `error_kind` (アプリ独自分類タグ)
- カウント系 (`count`, `n_chunks`, `n_sources`, `top_k`)、数値のみ
- モデル名 (LLM model、embedding model、設定値)

**スタックトレース**:
- 関数名、アプリパッケージ内ファイル名、行番号
- `site-packages/` フレームは通す
- ユーザー HOME 配下パスは除外

#### 通さない (禁止リスト、ホワイトリスト外なので自動除外、念のため明示)

`doc_id`, `source_id`, `chunk_id`, `chunk_text`, `text`, `content`, `embedding`, `vector`, `query`, `question`, `prompt`, `response`, `answer`, `filename`, `file_path`, `title`, `transcript`, `audio_path`, `user_input`, `user_message`, `messages`, `documents`

→ これらキーが構造化ログに現れた場合、Redactor は **「禁止キー検出: <key>」とログレポートにマークを残してその行ごと破棄**。

#### 個人特定可能なハードウェア情報も除外

- ホスト名 (`platform.node()`)
- IPアドレス / MACアドレス
- ディスクパス / ドライブラベル (空き容量の**数値のみ**通す)
- シリアル番号 / UUID系

### 6.3 例外メッセージの3層防御

`RuntimeError: <ドキュメント本文 partial>` のような形での機微情報混入を防ぐ:

1. **DomainError 階層を新設** (`core/exceptions.py` の既存基底を拡張):
   - 各 DomainError は `safe_message: str` クラス属性 (固定文字列)
   - 例: `MissingQdrantCollection.safe_message = "Qdrant collection not found"`
2. **DomainError の場合のみ** `safe_message` を送信
3. **想定外の例外** (`DomainError` を継承していない) は、メッセージ本体を送らず**型名と発生箇所のみ**

## 7. バックエンド仕様

### 7.1 APIエンドポイント

```
GET    /api/crash/pending                    未送信レポート一覧
POST   /api/crash/report                     即時レポート登録 (フロント例外通知用)
POST   /api/crash/{id}/dismiss               レポート却下
GET    /api/crash/{id}/prefill-url           GitHub Issue起票URL生成
POST   /api/crash/{id}/mark-reported         「GitHubで開く」押下時呼ばれる

GET    /api/feedback-hub/notices             お知らせ一覧
GET    /api/feedback-hub/unread-count        未読数 (お知らせ + 未送信レポート合算)
POST   /api/feedback-hub/feedback            ご意見・ご要望のプレビューURL生成
```

### 7.2 Unclean shutdown 検知

```python
# 起動時 (app.startup)
lock_path = data_dir / "running.lock"
if lock_path.exists():
    pid = read_lock(lock_path)
    if not psutil.pid_exists(pid):
        # 前回 unclean shutdown
        last_log = data_dir / "logs" / "last-session.log"
        if last_log.exists():
            collect_from_log_tail(last_log, lines=100) \
                .pipe(redactor.redact_log_event) \
                .pipe(fingerprint) \
                .pipe(pending_store.save)
    # PID生きてる = uvicorn --reload の正常再起動の可能性、何もしない
write_lock(lock_path, pid=os.getpid())

# 正常終了時 (atexit + signal handler SIGTERM/SIGINT)
lock_path.unlink(missing_ok=True)
```

### 7.3 設定永続化

`core/settings_store.py` (既存) に以下を追加:

```python
class CrashReportSettings:
    enabled: bool | None = None       # None = 未決定 (初回オプトイン未完了)
    auto_prompt: bool = True          # 自動ダイアログ表示
    opted_in_at: datetime | None = None
```

## 8. フロントエンド仕様

### 8.1 スタイル / カラートークン

既存の `app.css` の CSS変数を流用 + 不足分を追加:

```css
:root {
  /* 既存 */
  --color-bg: #ffffff;
  --color-bg-elevated: #fafafa;
  --color-fg: #1a1a1a;
  --color-fg-muted: #6b7280;
  --color-border: #e5e7eb;
  --color-accent: #3563e9;

  /* 追加 (ハブ用) */
  --color-feedback-fg: #0b0d12;          /* ハブ内の見出し */
  --color-feedback-divider: #e5e7eb;     /* 1px hairline */
  --color-feedback-unread: #3b82f6;      /* 未読ドット (青) */
  --color-feedback-error-dot: #ef4444;   /* ヘッダの未読ドット */
}
```

### 8.2 状態管理 (Svelte 5 runes)

```typescript
// feedbackHub.svelte.ts
class FeedbackHubStore {
  drawerOpen = $state(false);
  activeTab = $state<'notices' | 'bugs' | 'feedback'>('notices');
  unreadCount = $derived(noticesStore.unreadCount + crashReportsStore.pendingCount);
}

// notices.svelte.ts
class NoticesStore {
  items = $state<Notice[]>([]);
  seenIds = $state<Set<string>>(new Set(JSON.parse(localStorage.getItem('seen_notice_ids') ?? '[]')));
  unreadCount = $derived(this.items.filter(n => !this.seenIds.has(n.id)).length);

  markSeen(id: string) {
    this.seenIds.add(id);
    localStorage.setItem('seen_notice_ids', JSON.stringify([...this.seenIds]));
  }
}

// crashReports.svelte.ts
class CrashReportsStore {
  pending = $state<CrashReport[]>([]);
  pendingCount = $derived(this.pending.length);
}
```

### 8.3 スクショ機能 (html2canvas)

```bash
npm install html2canvas
```

```typescript
import html2canvas from 'html2canvas';

export async function captureCurrentView(): Promise<Blob> {
  const canvas = await html2canvas(document.body, {
    backgroundColor: '#ffffff',
    scale: 1,
    logging: false,
    ignoreElements: (el) => el.classList.contains('no-screenshot'),
  });
  return new Promise(resolve => canvas.toBlob(blob => resolve(blob!), 'image/png'));
}
```

注意: GitHub Issue 起票URLにスクショは直接埋め込めないため、ユーザーが Issue ページで手動添付する必要がある。プレビュー画面に**「スクショをクリップボードにコピー」**ボタンを出し、ユーザーが GitHub Issue ページの本文に貼り付ける運用とする。

## 9. 重複Issue対策

ローカル fingerprint 方式 (brainstorming 質問6で決定):

- スタックトレースの正規化(行番号削除、関数名+モジュール名のみ)→ SHA1
- `~/.notebook-ollama/reported.txt` に1行1ハッシュで永続化
- 同一ユーザーが同じバグを送ろうとした場合: 「これは前回 報告済みです。追加情報があればコメントしてください」と案内
- **異なるユーザー同士の重複は防げない**(認証不要を優先)

### ADR ノート (2026-06-28 sprint 1 verify 後追記)

Sprint 1 の adversarial review (Task 1.2 `fingerprint` モジュール) で、以下2つの未解決の設計上の懸念が確認された。本節は「将来の貢献者が気付かずに挙動を変えないよう」明示的に記録するものである。

#### 懸念 1: site-packages / ライブラリフレームが fingerprint に含まれる

**観察された挙動**: 同一のユーザー関数から `lib_a()` を呼ぶ場合と `lib_b()` を呼ぶ場合で fingerprint が異なる。すなわち、ライブラリのバージョン bump やコールパスの微変化のたびに「新しい fingerprint」が生成され、crash-dedup が **under-merge (本来1つの Issue にまとまるべきものが分散)** する。

#### 懸念 2: basename collision による false-positive dedup

**観察された挙動**: `frame.filename.replace('\\', '/').rsplit('/', 1)[-1]` がファイル識別子を basename に縮約しているため、別ディレクトリ配下の2つの `utils.py` が **同じ fingerprint** を生む。結果として、実際には別のバグなのに「既に報告済みです」と silencing されてしまう可能性がある。仕様本文の「関数名+モジュール名のみ」という表現が、basename か dotted module path (`pkg.sub.utils`) かを曖昧にしていた点も原因。

#### 当面の決定 (accept-for-now)

Sprint 1 ではこの **両方の挙動をそのまま受け入れる**。理由:

- dedup はあくまで **ヒント (hint)** であって保証 (guarantee) ではない。仕様にも「異なるユーザー同士の重複は防げない」と既に書いてあり、ローカル dedup の精度は best-effort という前提を踏襲する。
- crash report においては **under-merge (本来同じ Issue が2つ起票される) の方が over-merge (本物の別バグが silencing される) より安全**。前者は開発者が GitHub 側でラベリング/クローズで吸収できるが、後者は永久に届かなくなる。
- 本プロジェクトのディレクトリ構造では同名 `utils.py` が複数階層に並ぶケースは稀であり、basename collision の現実的な影響は当面小さい。

#### 将来の再検討トリガー (Future trigger)

本番のクラッシュレポート運用で次のいずれかが観測された場合、本 ADR を再検討する:

- **意味のある collision**: 別バグが「既報告」として silencing されているケース → (b) basename をやめ、`sys.modules` を経由して推定した dotted module path (`pkg.sub.utils`) に切り替える。
- **churn による断片化**: ライブラリのバージョン bump やコールパス変化で同一バグの fingerprint が大量に分散しているケース → (a) `sys.prefix` / `site-packages` ヒューリスティクスで library フレームをフィルタし、ユーザーコードフレームのみで fingerprint を構築する。

**Reference**: adversarial verify result, 2026-06-28 (Sprint 1 Task 1.2 `core/crash_reporter/fingerprint.py`).

## 10. GitHub Issue URL生成 (8KB制限対応)

```python
def build_issue_url(repo: str, title: str, body: str, labels: list[str]) -> str:
    base = f"https://github.com/{repo}/issues/new"
    params = {
        "title": title,
        "body": body,
        "labels": ",".join(labels),
    }
    url = f"{base}?{urlencode(params, quote_via=quote_plus)}"

    # 8KB - 余白 = 7KB を上限とする
    MAX_URL_LEN = 7000
    if len(url) > MAX_URL_LEN:
        # 段階的にbodyを切り詰める
        for trim_lines in [50, 30, 20, 10]:
            trimmed_body = trim_log_section(body, trim_lines)
            url = f"{base}?{urlencode({**params, 'body': trimmed_body}, quote_via=quote_plus)}"
            if len(url) <= MAX_URL_LEN:
                return url
        # 最終手段: ログ部分を「ローカルファイル添付案内」に置換
        marker = "ログが長すぎてURLに収まりませんでした。ローカルファイル `<crash_id>.log` をこのIssueにドラッグ&ドロップしてください。"
        truncated_body = replace_log_section(body, marker)
        return f"{base}?{urlencode({**params, 'body': truncated_body}, quote_via=quote_plus)}"
    return url
```

## 11. テスト戦略

### 11.1 ユニットテスト (`tests/unit/crash_reporter/`)

| 対象 | テスト種別 | 内容 |
|---|---|---|
| `redactor.redact_log_event` | property-based (hypothesis) | 任意文字列を投入してもoutputに現れない |
| `redactor` 禁止キー | fuzz | 全禁止キーで値が漏れないこと |
| `fingerprint` | 等価性 | 同一traceback→同ハッシュ、異なれば異なる |
| `prefill_url` | 境界値 | 7KB境界、特殊文字、URLエンコード |
| `formatter` | snapshot | 固定入力の出力を固定化 |
| `hardware.collect()` | フォールバック | GPU/nvidia-smi不在時に `<unavailable>` |

### 11.2 統合テスト (`tests/integration/crash_reporter/`)

- `pending_store` JSON永続化、`reported_store` 追記
- API ルータ各エンドポイント
- `lifecycle` running.lock + psutil による unclean shutdown 検知

### 11.3 E2Eテスト (Playwright, `tests/e2e/`)

| シナリオ | 検証 |
|---|---|
| バックエンド500 → 即時モーダル → プレビュー → 「GitHubで開く」 | 新規タブのURLが `github.com/KawanoMomo/notebook-ollama/issues/new?...` で始まる(Issue起票自体はモック) |
| ヘッダ旗クリック → drawer 表示 → タブ切替 | 各タブ正常表示 |
| お知らせクリック → 既読更新 → localStorage反映 | 未読ドット消失 |
| 設定画面でON/OFFトグル → 500発生してもモーダル出ない | |
| 起動時 unclean shutdown 検知 → 起動時モーダル表示 | running.lockをテストで偽造 |

### 11.4 実機スクリーンショット検証

[[feedback_visual_verification]] 準拠。各モーダル・ドロワー・プレビューを Evaluator サブエージェントで撮影、報告に同梱。

## 12. Sprint分割

| Sprint | 内容 | TDD |
|---|---|---|
| 1 | `redactor` / `fingerprint` / `hardware.collect` 純粋関数群 | フル |
| 2 | `pending_store` / `reported_store` / `formatter` / `prefill_url` | フル |
| 3 | バックエンドtraps (FastAPI handler / sys.excepthook / signal / atexit) + `apps/api/routers/crash.py` | 統合テスト |
| 4 | `lifecycle.py` unclean shutdown 検知 (running.lock + psutil) | 統合テスト |
| 5 | フロント: 旗ハブ drawer 枠 + クラッシュ即時モーダル + プレビュー | E2E + 実機スクショ |
| 6 | フロント: お知らせタブ (timeline + localStorage既読) | E2E + 実機スクショ |
| 7 | フロント: 不具合タブ + 設定画面セクション + 初回オプトイン | E2E + 実機スクショ |
| 8 | フロント: ご意見タブ + スクショ (html2canvas) | E2E + 実機スクショ |
| 9 | E2E統合検証 + アイコンサイズ実機調整 + ドキュメント | Evaluator統合確認 |

## 13. 将来拡張

- **GitHub Discussion 連携**: ご意見・ご要望は当面 Issue として起票するが、Discussion カテゴリへ振り分け可能にする
- **お知らせの管理画面**: 現状静的 JSON、将来は admin 画面で記事投稿
- **複数デバイス同期**: 既読状態を backend で管理 (現状 localStorage)
- **GitHub Search API 連携**: 既存 Issue 検索による重複統合候補表示
- **ダークモード**: NotebookOllama 本体がダーク対応する際に、`--color-feedback-*` トークンを反転値に振り分け

## 14. 決定事項サマリ (brainstorming合意)

| 項目 | 決定 |
|---|---|
| 方式 | 案A: ユーザー手動送信 + 自動ログ収集 (PAT埋め込みなし) |
| トリガー | 自動(モーダル) + 手動(ヘッダボタン) |
| リポ可視性 | Public 前提 |
| 収集粒度 | 標準 (ホワイトリスト方式) |
| クラッシュ対応 | ①②③⑤ 即時 + ④ 起動時pending |
| 重複対策 | ローカル fingerprint (b) |
| 法的リスク | UIで「送信される/されない」を宣言しない |
| ハードウェア情報 | LLM性能解析のため許可 (ホスト名等は除外) |
| ヘッダアイコン | Megaphone (将来通知ハブ統合) |
| コンテナ | 右側 drawer 440px |
| changelog UI | Linear式 縦timeline + 日付ヘッダ + サブセクション |
| 視覚階層 | モノクロ + typography weight 600/400 + 1px hairline |
| 感情入力 | Thumbs 3段階 (Up / Minus / Down) |
| 未読管理 | localStorage |
| ダークモード | 当面ライトのみ |
| スクショ技術 | html2canvas |
| アイコンサイズ | Sprint 5の実機確認で最終決定 |

## 15. オープン項目

- お知らせ取得元 `data/notices.json` のスキーマ確定
- ご意見・ご要望の送信先 (GitHub Issue or Discussion) の最終判断
- `DomainError` 階層への既存例外の段階的移行計画 (一気にやらず、機能追加時に随時)
- アイコンサイズ最終値 (Sprint 5)

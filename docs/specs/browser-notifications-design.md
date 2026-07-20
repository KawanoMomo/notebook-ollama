---
type: spec
title: Browser Notifications
summary: "取込/LLM応答の完了をWeb Notifications APIでOS通知(非フォーカス時のみ)。"
aliases:
  - Browser Notifications
  - ブラウザ通知
status: approved
status_inferred: true
date: 2026-05-21
project: NotebookOllama
area: notifications
tags:
  - spec
related:
  - "[[notebook-ollama-design]]"
---

# Browser Notifications — 設計仕様書

- **作成日**: 2026-05-21
- **対象プロジェクト**: `10_NotebookOllama` (apps/web)
- **関連 spec**: [2026-05-19-notebook-ollama-design.md](./2026-05-19-notebook-ollama-design.md)

## 1. 目的

長時間のドキュメント取り込みや LLM 応答の完了に気付けるよう、ブラウザの Web Notifications API を用いた OS レベル通知を提供する。タブが非表示／非フォーカスのときのみ通知し、表示中は既存のトースト UI に委ねる。

## 2. 機能要件

### 2.1 通知発火イベント

| # | イベント | 検知箇所 | 通知 title | 通知 body | tag |
|---|---|---|---|---|---|
| F1 | チャット応答完了 | `conversationStore.send()` の `done` 受信 | 「回答完了」 | 質問先頭40文字 | `chat-done` |
| F2 | チャット応答エラー | 同 `error` 受信 / catch | 「回答エラー」 | エラー本文先頭80文字 | `chat-error` |
| F3 | ソース取り込み完了 | `eventsStore` SSE: `status=ready` への遷移 | 「取り込み完了」 | ソースタイトル | `source-ready-<id>` |
| F4 | ソース取り込み失敗 | 同 `status=error` への遷移 | 「取り込み失敗」 | `<title> — <error_msg>` | `source-error-<id>` |

「遷移」は前回 status と異なる場合のみ。同じ status の再受信では発火しない。

### 2.2 表示判定

通知を出す条件: `document.visibilityState === 'hidden' || !document.hasFocus()`

タブが前面かつフォーカス中の場合は通知を出さない（トースト UI で十分）。

### 2.3 許可フロー

- 初回 `conversationStore.send()` 呼び出し時に `Notification.requestPermission()` を1度だけ実行。
- ブラウザが既に決定済み（`granted` / `denied`）の場合は何もしない。
- 拒否時はすべての通知を黙ってスキップ（再要求はしない）。

### 2.4 クリック動作

通知クリック → `window.focus()` で該当タブをアクティブ化、`notification.close()` で閉じる。ナビゲーション（特定ソース／会話への遷移）は本スコープ外。

## 3. 非機能要件

- API 非対応環境 (`typeof Notification === 'undefined'`)・http 以外で動かない環境では黙ってスキップ。
- SSR 安全（モジュール読み込み時点で `Notification` を参照しない）。
- 設定 UI なし。OS / ブラウザの通知設定で ON/OFF 制御可能。

## 4. 設計

### 4.1 新規モジュール: `src/lib/utils/notifications.ts`

```ts
export function notificationsSupported(): boolean
export async function requestPermissionOnce(): Promise<void>
export function notify(opts: { title: string; body: string; tag?: string }): void
```

- `requestPermissionOnce()`: モジュール内 boolean で「要求済みフラグ」を保持し、リロード後再要求は許容（ブラウザ側で即決定される）。
- `notify()`: `notificationsSupported() && Notification.permission === 'granted' && (document.hidden || !document.hasFocus())` を満たすときのみ表示。`onclick` で `window.focus(); this.close()`。

### 4.2 既存変更箇所

| ファイル | 変更内容 |
|---|---|
| `lib/stores/conversation.svelte.ts` | `send()` 入口で `requestPermissionOnce()`。`done` 受信／catch 時に `notify()` |
| `lib/stores/events.svelte.ts` | 既存 SSE callback で旧 status を保持し、`ready` / `error` への新規遷移時に `notify()` |

### 4.3 通知 tag 設計

- チャット系は固定 tag（同種通知は最新で置き換え）。
- ソース系は `source-<status>-<id>` で個別表示。多数同時取り込みでも一覧可能。

## 5. 受け入れ基準

- A1: タブを別ウィンドウで非フォーカスにしてチャット送信 → 完了で OS 通知が出る
- A2: 同状態で markdown ソースをアップ → ready で通知が出る
- A3: タブが前面・フォーカス時はチャット完了・ソース完了とも通知が出ない（トーストのみ）
- A4: 通知許可を拒否したらコンソールエラーなしでスキップ
- A5: 通知クリックでブラウザタブが前面に来る

## 6. スコープ外（将来）

- 設定画面トグル
- 通知音量制御
- 通知クリック → 該当ノート／ソースへのディープリンク

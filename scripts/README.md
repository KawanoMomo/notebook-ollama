# scripts — 使い方

普段使うのは **2つだけ**です。

| やりたいこと | コマンド |
|---|---|
| **起動する** | `.\scripts\start.ps1 -OpenBrowser` |
| **停止する** | `.\scripts\stop.ps1` |

これだけで動きます。プロセスを手で探して終了させる必要はありません。

---

## start.ps1 — 起動

```powershell
.\scripts\start.ps1               # 前面で起動(Ctrl+C で停止)
.\scripts\start.ps1 -OpenBrowser  # 起動してブラウザを開く
.\scripts\start.ps1 -Background   # 裏で起動(ログは下記)
.\scripts\start.ps1 -Port 9000    # ポート変更
```

- **何度実行しても安全**です。
  - すでに起動済みなら、二重起動せずブラウザを開くだけで終了します。
  - 前回の起動が中断されてプロセスやロックが残っていても、**自動で掃除してから**起動します。
- 起動時に Ollama の疎通確認・必要モデルの確認・フロントエンドのビルド(必要時のみ)を行います。
- モデルが無い場合は **警告だけ**で起動は続行します(`ollama pull <model>` を促します)。

## stop.ps1 — 停止

```powershell
.\scripts\stop.ps1
.\scripts\stop.ps1 -Port 9000
```

- PID ファイル・リッスン中のポート・`apps.api.main` を実行中の uvicorn/python の**3経路すべて**を見て確実に停止します。
- 中断起動で残った孤児プロセスもこれで片付きます。何も動いていなければそのまま正常終了します。

---

## たまに使うもの

| スクリプト | 用途 |
|---|---|
| `dev.ps1` | 開発用。`uv run uvicorn --reload` でホットリロード起動(本番ビルド不要) |
| `install-startup.ps1` | ログオン時に自動起動するよう Windows タスクに登録 |
| `uninstall-startup.ps1` | 上記の自動起動登録を解除 |
| `install-pdf-support.ps1` | PDF 取り込み用 PyMuPDF を導入(AGPL-3.0 同意が必要) |
| `start.sh` | Linux / macOS 用の起動スクリプト(Windows では使いません) |

## ログ / データの場所

- データ: `%USERPROFILE%\.notebook-ollama\`
- ログ(`-Background` 起動時): `%USERPROFILE%\.notebook-ollama\logs\server.log` / `server-error.log`

## 補足

- Qdrant はローカルモードでストレージを**単一プロセスで専有**します。同じデータで2つ目のサーバーは起動できません(`start.ps1` が自動で旧インスタンスを片付けるので通常は意識不要)。
- `.ps1` の文字列は ASCII のみで書いています(Windows PowerShell 5.1 の文字コード由来の文字化けを避けるため)。

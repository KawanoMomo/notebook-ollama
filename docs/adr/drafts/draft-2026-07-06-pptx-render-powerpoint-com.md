---
type: adr-draft
title: PPTXの見た目再現はPowerPoint COMによる取込時PDF化
summary: "PPTXの見た目再現をPowerPoint COMで取込時PDF化+グレースフルデグレードで行う設計判断。"
aliases:
  - PPTX描画
  - PowerPoint COM
status: proposed
date: 2026-07-06
project: NotebookOllama
area: presentation
category: 外部依存/取込パイプライン
tags:
  - adr
  - draft
related:
  - "[[2026-07-06-presentation-mode-design]]"
---

# ADR-draft: PPTXの見た目再現はPowerPoint COMによる取込時PDF化+グレースフルデグレード

- **ステータス**: 提案(ドラフト・未採番)
- **カテゴリ**: 外部依存/取込パイプライン
- **日付**: 2026-07-06
- **対象プロジェクト**: NotebookOllama
- **出典**: 発表モード設計 `docs/specs/2026-07-06-presentation-mode-design.md`

## コンテキスト

発表モードでPPTXを「見た目のまま」表示したいが、ブラウザはPPTXを直接描画できない
(PDFはpdf.jsで描画可能)。変換層の選定が必要。開発機にはPowerPointがあるが、
無い環境での実行も想定するとの要件。

## 検討した選択肢

### A) PowerPoint COM(pywin32でPDFエクスポート自動化)

- メリット: 本家レンダリングで忠実度最高(フォント・図形が崩れない)
- デメリット: PowerPointインストール+対話ユーザーセッションが動作条件

### B) LibreOffice headless変換

- メリット: 無料、PowerPoint不要
- デメリット: 別途インストール必要。日本語フォントやレイアウトが崩れることがある

### C) 抽出テキストの簡易スライド風表示

- メリット: 外部依存なし
- デメリット: 図表・レイアウトが再現されず「見た目のまま」要件を満たさない

## 決定

A を採用し、取込時に一度だけ `<id>.slides.pdf` を併産する。PowerPoint未検出環境では
機能を壊さず縮退する: テキスト取込は従来どおり成功させ、「発表を開始」のみ無効化して
「PDFに書き出して取り込むと発表できます」をガイド(recording extra未導入時の503+ヒントと
同じグレースフルデグレードのパターン)。LibreOfficeフォールバックはv1非対応(必要になれば
本ADRを改訂)。COM実行はタイムアウト付きでプロセスを確実に後始末する。

## 結果

(実装後に記載)

## 教訓

(実装後に記載)

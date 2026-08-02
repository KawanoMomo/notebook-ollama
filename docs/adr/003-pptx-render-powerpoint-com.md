---
type: adr
title: PPTXの見た目再現はPowerPoint COMによる取込時PDF化
summary: "PPTXの見た目再現をPowerPoint COMで取込時PDF化+グレースフルデグレードで行う設計判断。"
aliases:
  - PPTX描画
  - PowerPoint COM
status: approved
date: 2026-07-06
adr: 003
project: NotebookOllama
area: presentation
category: external-dep
tags:
  - adr
related:
  - "[[2026-07-06-presentation-mode-design]]"
---

# ADR-003: PPTXの見た目再現はPowerPoint COMによる取込時PDF化+グレースフルデグレード

- **ステータス**: 承認
- **カテゴリ**: external-dep
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

(2026-07-20 実装・マージ済み、PR #19 — 詳細は [[ECN-008_発表モード|ECN-008]])

- 決定どおり取込時に一度だけ `<id>.slides.pdf` を併産し、`has_slides` で
  発表可否を表す実装にした(`feat(slides)`)
- **縮退の設計が効いた**。PowerPoint 未検出環境でもテキスト取込は成功し、
  「発表を開始」だけが無効化される。recording extra 未導入時の 503+ヒントと
  同じパターンで、発表を使わないユーザーは影響を受けない
- `pywin32` は `slides` extra として分離(`sys_platform == 'win32'` マーカー付き)。
  Linux/macOS のロックを壊さない
- LibreOffice フォールバックは予定どおり v1 非対応のまま。要望は出ていない


## 教訓

- **外部アプリ依存は「無い環境で機能が縮退する」形にする。** 取込そのものを
  失敗させると、その機能を使わないユーザーまで巻き込む。縮退時に
  「どうすれば使えるか」(PDFに書き出して取り込む)を案内するとサポート負荷が減る
- プラットフォーム限定の依存は extra + marker で隔離する。ベース install に
  混ぜると他OSのロックファイルが壊れる
- 「一度だけ変換して保存」は、表示のたびに変換するより単純。取込が遅くなる
  代わりに、閲覧時の失敗経路が消える


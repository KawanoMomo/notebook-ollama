<!--
  PresentationView.test.ts 用の SlideView スタブ。実物は pdf.js(canvas 描画)に依存し
  jsdom では検証できないため、ページ操作(◀▶/ホイール/ページ番号入力)のロジックだけを
  ユニットテストで確認するための空コンポーネント。実描画は evaluator の実機検証で担保する。
-->
<div data-testid="slide-stub"></div>

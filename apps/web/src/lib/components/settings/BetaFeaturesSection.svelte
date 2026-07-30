<!--
  BetaFeaturesSection — 設定画面「ベータ機能」セクション (Task 4)

  spec : docs/specs/2026-07-20-beta-feature-flags-design.md
  plan : Sprint A Task 4

  ## レイアウト (CrashReportSection.svelte 準拠)

  既存 CrashReportSection の `.head` / `.group` / `.row` / `.switch` CSS を
  流用し、縦に肥大化させない ([[feedback_compact_ui_repurpose_affordance]])。

    FlaskConical + 「ベータ機能」
    評価中の機能です。有効化するとこのアプリでのみ提供されます。
    ─────────────────────────────────────────────────────
    [Row per flag] name (+ description)              [toggle]

  ## 空件数ガード

  `betaFlags` が 0 件の場合は何も描画しない(stage === 'ga' に昇格して
  ベータフラグが尽きた場合を含む)。ナビ側 (+page.svelte) も同条件で
  ナビ項目自体を隠す。

  ## GA フラグの扱い

  `stage === 'ga'` はサーバ側でオプトイン変更を拒否するため一覧から除外する
  (`betaFlags` は features store 側で `stage === 'beta'` のみに絞り込み済み)。

  ## DI

  `features` prop で store を差し替え可能。default は global singleton。
-->
<script lang="ts">
  import { FlaskConical } from '@lucide/svelte';

  import { featuresStore, type FeaturesStore } from '$lib/stores/features.svelte';
  import { pushToast } from '$lib/components/Toast.svelte';

  interface Props {
    features?: FeaturesStore;
  }
  let { features = featuresStore }: Props = $props();

  let togglingId = $state<string | null>(null);

  async function toggle(id: string, next: boolean) {
    if (togglingId) return;
    togglingId = id;
    try {
      await features.setOptin(id, next);
    } catch (e) {
      pushToast(e instanceof Error ? e.message : String(e), 'error');
    } finally {
      togglingId = null;
    }
  }
</script>

{#if features.betaFlags.length > 0}
  <div class="head">
    <h3>
      <FlaskConical size={18} strokeWidth={1.75} aria-hidden="true" />
      ベータ機能
    </h3>
    <p class="sub">評価中の機能です。有効化するとこのアプリでのみ提供されます。</p>
  </div>

  <div class="group">
    {#each features.betaFlags as flag (flag.id)}
      <div class="row">
        <div class="lab">
          {flag.name}
          <small>{flag.description}</small>
        </div>
        <div class="ctl">
          <button
            type="button"
            class="switch"
            class:off={!flag.enabled}
            role="switch"
            aria-checked={flag.enabled}
            aria-label={flag.name}
            disabled={togglingId === flag.id}
            onclick={() => toggle(flag.id, !flag.enabled)}
          ><i></i></button>
        </div>
        {#if flag.id === 'table-figure-rag'}
          <!-- 使い方ガイド(実機FB 2026-07-26: 有効化欄に具体的な使い方を記載)。
               details で折りたたみ、既定は閉=縦に肥大化させない。
               画像は static/help/ 配下の実機スクリーンショット。 -->
          <details class="guide">
            <summary>使い方を見る（スクリーンショット付き）</summary>
            <div class="guide-body">
              <p class="guide-intro">
                PDFの<strong>表・図・ページの見た目</strong>を検索と回答に活かす機能群です。
                表は崩れないHTMLで表示され、図はAIが説明文を作って検索に乗り、
                ページ全体の視覚検索も併用できます。
              </p>

              <h4>Step 1. ベータを有効化し、視覚モデルを設定する</h4>
              <p>
                上のスイッチをONにすると、設定「モデル・Ollama」に
                <strong>視覚モデル（図の解析・OCR用）</strong>と
                <strong>視覚検索（ベータ）</strong>の項目が現れます。
                図の説明生成・スキャンPDFのOCRに使うvision対応モデル（例: llava:7b）を選択してください。
              </p>
              <img src="/help/table-figure-rag/settings-models.png" alt="設定のモデル・Ollamaパネル。視覚モデルの選択欄と視覚検索トグル" loading="lazy" />
              <p>
                同じ設定画面にはさらに<strong>視覚索引の単位</strong>（ページ全体／タイル分割）と
                <strong>検索戦略</strong>（RRF融合／視覚のみ／pixel-native）のセレクトが並びます。
                索引単位はページ全体を1枚の画像として検索する方式と、ページを分割した
                タイル単位で検索する方式を切り替えるものです。検索戦略はテキスト検索と視覚検索を
                組み合わせる<strong>RRF融合</strong>（既定）、視覚検索だけを使う<strong>視覚のみ</strong>、
                本文を使わず画像だけをモデルに渡す<strong>pixel-native</strong>から選べます。
              </p>

              <h4>Step 2. PDFを取り込み、表・図を解析する</h4>
              <p>
                PDF取込時に表と図は自動抽出されます。既存ソースに適用するには、
                下のスクリーンショットの<strong>赤枠②</strong>
                （ソースカードのタイトル右横のアイコン列・左から1番目と2番目）を使います:
                表アイコンが<strong>「表・図を再解析」</strong>、
                画像アイコンが<strong>「図を解析」</strong>（AIによる図説明の生成）です。
              </p>
              <img src="/help/table-figure-rag/source-icons.png" alt="赤枠①がソース一覧上部の視覚インデックスアイコン、赤枠②がソースカードの表・図解析アイコン" loading="lazy" />

              <h4>Step 3. 視覚インデックスを構築する（任意・実験的）</h4>
              <p>
                上のスクリーンショットの<strong>赤枠①</strong> —
                ソース一覧<strong>最上部のツールバー（「＋追加」の並び）右端、
                マイクアイコンのすぐ右隣にある四角いスキャンマーク</strong>をクリックすると、
                視覚インデックスのポップアップが開きます（下図）。
                「視覚インデックスを構築」ボタンで構築を開始してください。
                視覚インデックスを構築すると、テキストにならない図版・レイアウトも
                ページ画像として検索対象になります。構築はノートブック単位の手動実行です。
                ページ索引・タイル索引はそれぞれ独立して構築・削除でき、
                <strong>索引単位を切り替えて使うには、切り替え先の単位の索引を先に構築しておく
                必要があります</strong>（未構築のままだと自動的にテキスト検索へ切り戻ります）。
                構築時間は<strong>GPUが使える環境では1ページあたり約0.36秒</strong>、
                <strong>CPUのみの環境では1ページあたり約52秒</strong>です（進捗と残り時間目安を表示）。
                <strong>注意</strong>: 録音機能(recording)とGPU版の視覚埋め込みは同一環境で
                両立せず、<strong>視覚インデックスの構築が失敗します</strong>
                （遅くなるのではなく失敗します）。視覚埋め込みをGPUで使う場合は、
                recordingを入れない環境にしてください。
              </p>
              <img src="/help/table-figure-rag/visual-index-modal.png" alt="視覚インデックスの構築・削除モーダル" loading="lazy" />

              <h4>Step 4. チャットで質問する</h4>
              <p>
                あとは普通に質問するだけです。表はHTML表示、図は説明文つきで検索に乗り、
                視覚検索でヒットしたページは引用に<strong>「(視覚検索)」</strong>と表示されます。
                vision対応のチャットモデルを選んでいる場合は、図やページの画像そのものも
                回答の材料として渡されます。<strong>検索戦略をpixel-nativeにした場合は、
                チャットモデルがvision対応でないとエラーになります</strong>
                （設定画面でvision対応モデルに変更するか、検索戦略を
                「視覚のみ」または「RRF融合」に戻してください）。
              </p>
              <img src="/help/table-figure-rag/citation-visual.png" alt="チャットの引用にp.5(視覚検索)と表示されている例" loading="lazy" />

              <p class="guide-note">
                注意: 図の解析・OCR・視覚インデックスはローカルのAIモデルで処理するため時間がかかります。
                初回は視覚埋め込みモデルのダウンロード（約4GB）が発生します。
              </p>
            </div>
          </details>
        {/if}
      </div>
    {/each}
  </div>
{/if}

<style>
  .head {
    margin-bottom: 14px;
  }

  h3 {
    margin: 0 0 var(--space-1);
    font-size: 17px;
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }

  .sub {
    color: var(--color-fg-muted);
    font-size: 12px;
    margin: 0;
    line-height: 1.6;
  }

  .group {
    margin-top: 12px;
  }

  .row {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 10px 18px;
    align-items: center;
    padding: 10px 0;
  }

  .row + .row {
    border-top: 1px solid #f0f0f2;
  }

  .lab {
    font-size: 13px;
  }

  .lab small {
    display: block;
    color: var(--color-fg-muted);
    font-size: 11px;
    margin-top: 2px;
    font-weight: 400;
    line-height: 1.5;
  }

  .ctl {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    justify-content: flex-end;
  }

  /* AudioSettingsSection / CrashReportSection と同じ switch トークン */
  .switch {
    width: 40px;
    height: 23px;
    border-radius: 999px;
    background: var(--color-accent);
    position: relative;
    flex: none;
    border: none;
    padding: 0;
    cursor: pointer;
  }

  .switch.off {
    background: #c8c8cd;
  }

  .switch:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .switch i {
    position: absolute;
    top: 2px;
    width: 19px;
    height: 19px;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
    right: 2px;
    transition: right 0.12s, left 0.12s;
  }

  .switch.off i {
    right: auto;
    left: 2px;
  }

  .guide {
    grid-column: 1 / -1;
    margin-top: 2px;
  }

  .guide summary {
    cursor: pointer;
    font-size: 12px;
    color: var(--color-accent);
    user-select: none;
  }

  .guide-body {
    margin-top: 10px;
    padding: 12px 14px;
    border: 1px solid #f0f0f2;
    border-radius: var(--radius-md);
    font-size: 12px;
    line-height: 1.7;
    color: var(--color-fg);
  }

  .guide-body h4 {
    margin: 14px 0 4px;
    font-size: 12.5px;
  }

  .guide-body h4:first-of-type {
    margin-top: 8px;
  }

  .guide-body p {
    margin: 0 0 6px;
  }

  .guide-intro {
    color: var(--color-fg-muted);
  }

  .guide-body img {
    display: block;
    max-width: 100%;
    border: 1px solid #e4e4e8;
    border-radius: var(--radius-md);
    margin: 6px 0 4px;
  }

  .guide-note {
    color: var(--color-fg-muted);
    font-size: 11px;
    margin-top: 10px;
  }
</style>

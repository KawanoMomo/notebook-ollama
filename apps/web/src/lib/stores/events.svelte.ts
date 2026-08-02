import { openNotebookEvents, type SourceStatusEvent } from "$lib/api/events";
import type { Source } from "$lib/api/types";
import type { VisualIndexUnit } from "$lib/api/visualIndex";
import { currentNotebookStore } from "./currentNotebook.svelte";
import { notify } from "$lib/utils/notifications";

export interface ConvStep {
  step: string;
  step_label: string;
  progress: number;
}

export interface VisualIndexProgress {
  done: number;
  total: number;
  // 観測ペースからの残り時間目安(秒)。ページ間の進み(done差分)を2点以上
  // 観測できるまでは null(CPU推論では1ページ数十秒かかるため、目安表示は
  // ADRドラフト visual-embedding-ondemand-transformers の要件)。
  etaSeconds: number | null;
}

export interface VisualIndexOutcome {
  // "complete" = 1件以上索引できた / "error" = 対象はあったが1件も索引でき
  // なかった / "noop" = 対象が0件だった(タイル格子等のパラメータを変えても
  // 既に索引済みのソースは再構築対象にならず、無言で何もしないまま「完了」
  // を装うのを防ぐための区分。最終レビュー I3)。
  kind: "complete" | "error" | "noop";
  // SSE イベントは同一 {kind} でも別の発生を区別できないため、発生時刻を
  // change-detection のキーとして使う(購読側 $effect が「新しい完了/失敗」を検知する)。
  at: number;
  // 部分失敗(半滅)の件数。kind:"complete" でも1件以上あれば「完了」の
  // 見た目の裏でスキップされたページがあることを示す(最終レビュー I4)。
  // ペイロードに無ければ 0。
  skippedPages: number;
}

export interface EventsStore {
  start(notebookId: string): void;
  stop(): void;
  convStepFor(sourceId: string): ConvStep | undefined;
  /**
   * 図解析フェーズの残り時間目安(秒)。観測開始以降のペースから算出し、
   * 2点目の進捗を受け取るまでは null。図1件あたり数秒かかるうえ数千件に
   * 及ぶことがあり、n/N だけでは「あと何時間か」が判断できないため
   * (実機FB 2026-07-26)。
   */
  figureEtaFor(sourceId: string): number | null;
  visualIndexProgressFor(unit: VisualIndexUnit): VisualIndexProgress | null;
  /** どちらかの索引単位が構築中かどうか(ツールバーの aria-busy / スピナー用)。 */
  readonly visualIndexBusy: boolean;
  visualIndexOutcomeFor(unit: VisualIndexUnit): VisualIndexOutcome | null;
}

export function createEventsStore(): EventsStore {
  let close: (() => void) | null = null;
  const lastStatus = new Map<string, string>();
  // Latest pipeline step per source_id, driven by SSE payloads that carry `step`.
  let convSteps = $state<Record<string, ConvStep>>({});
  // 視覚インデックス構築ジョブはノートブック単位(ソース単位の activeJobs 機構とは
  // 別系統)なので、進捗/結果を専用の state として持つ(events.ts は全イベントを
  // 単一の "source_status" SSE イベント名で運ぶため、type で分岐する)。
  // 索引単位ごとに進捗と ETA 基準点を持つ。ページ索引とタイル索引は
  // 独立に走らせられるため、シングルトンだと進捗が混線し ETA が壊れる。
  let visualIndexProgress = $state<Map<VisualIndexUnit, VisualIndexProgress>>(new Map());
  let visualIndexOutcome = $state<Map<VisualIndexUnit, VisualIndexOutcome>>(new Map());
  let visualBaselines = new Map<VisualIndexUnit, { at: number; done: number }>();
  // 図解析の ETA 基準点(ソース単位)。視覚インデックスと同じ考え方だが、
  // こちらは複数ソースが同時に走りうるので source_id ごとに持つ。
  const figureBaselines = new Map<string, { at: number; done: number }>();
  let figureEtas = $state<Record<string, number>>({});

  return {
    convStepFor(sourceId) {
      return convSteps[sourceId];
    },
    figureEtaFor(sourceId) {
      return figureEtas[sourceId] ?? null;
    },
    visualIndexProgressFor(unit) {
      return visualIndexProgress.get(unit) ?? null;
    },
    get visualIndexBusy() {
      return visualIndexProgress.size > 0;
    },
    visualIndexOutcomeFor(unit) {
      return visualIndexOutcome.get(unit) ?? null;
    },
    start(notebookId) {
      close?.();
      lastStatus.clear();
      convSteps = {};
      visualIndexProgress = new Map();
      visualIndexOutcome = new Map();
      visualBaselines = new Map();
      figureBaselines.clear();
      figureEtas = {};
      close = openNotebookEvents(notebookId, (ev: SourceStatusEvent) => {
        // 視覚インデックスジョブのイベントには source_id が無いため、
        // 通常のソース状態パッチに入る前に分岐して処理する。
        if (ev.type === "visual_index_progress") {
          const unit = (ev.unit as VisualIndexUnit) ?? "page";
          const done = typeof ev.done === "number" ? ev.done : 0;
          const total = typeof ev.total === "number" ? ev.total : 0;
          const base = visualBaselines.get(unit);
          let etaSeconds: number | null = null;
          if (base) {
            const advanced = done - base.done;
            const elapsedMs = Date.now() - base.at;
            if (advanced > 0 && elapsedMs > 0) {
              etaSeconds = Math.round(((total - done) * (elapsedMs / advanced)) / 1000);
            }
          } else {
            visualBaselines.set(unit, { at: Date.now(), done });
          }
          const next = new Map(visualIndexProgress);
          next.set(unit, { done, total, etaSeconds });
          visualIndexProgress = next;
          return;
        }
        if (
          ev.type === "visual_index_complete" ||
          ev.type === "visual_index_error" ||
          ev.type === "visual_index_noop"
        ) {
          const unit = (ev.unit as VisualIndexUnit) ?? "page";
          const nextProgress = new Map(visualIndexProgress);
          nextProgress.delete(unit);
          visualIndexProgress = nextProgress;
          visualBaselines.delete(unit);
          const kind: VisualIndexOutcome["kind"] =
            ev.type === "visual_index_complete"
              ? "complete"
              : ev.type === "visual_index_noop"
                ? "noop"
                : "error";
          const skippedPages =
            typeof ev.skipped_pages === "number" ? ev.skipped_pages : 0;
          const nextOutcome = new Map(visualIndexOutcome);
          nextOutcome.set(unit, { kind, at: Date.now(), skippedPages });
          visualIndexOutcome = nextOutcome;
          return;
        }
        // Record the latest pipeline step for this source (if the payload carries one).
        if (typeof ev.step === "string") {
          convSteps = {
            ...convSteps,
            [ev.source_id]: {
              step: ev.step,
              step_label: typeof ev.step_label === "string" ? ev.step_label : "",
              progress: typeof ev.progress === "number" ? ev.progress : 0,
            },
          };
        }
        // patch the source in currentNotebookStore
        const existing = currentNotebookStore.sources.find(
          (s) => s.id === ev.source_id,
        );
        if (!existing) return;
        const prev = lastStatus.get(ev.source_id) ?? existing.status;
        lastStatus.set(ev.source_id, ev.status);
        const chunkCount =
          typeof ev.chunk_count === "number" ? ev.chunk_count : existing.chunk_count;
        const embedded =
          typeof ev.embedded === "number" ? ev.embedded : undefined;
        // 図解析の進捗。ペイロードに含まれるイベントでのみ更新し、含まれない
        // 通常イベント(embedding 等)では既存値を維持する。
        const figuresDone =
          typeof ev.figures_done === "number" ? ev.figures_done : undefined;
        const figuresTotal =
          typeof ev.figures_total === "number" ? ev.figures_total : undefined;
        if (figuresDone !== undefined && figuresTotal !== undefined) {
          const now = Date.now();
          const base = figureBaselines.get(ev.source_id);
          if (base === undefined) {
            figureBaselines.set(ev.source_id, { at: now, done: figuresDone });
          } else {
            const advanced = figuresDone - base.done;
            const elapsedMs = now - base.at;
            if (advanced > 0 && elapsedMs > 0) {
              figureEtas = {
                ...figureEtas,
                [ev.source_id]: Math.round(
                  ((figuresTotal - figuresDone) * (elapsedMs / advanced)) / 1000,
                ),
              };
            }
          }
          if (figuresDone >= figuresTotal) {
            // フェーズ完了。次フェーズ(埋め込み)の表示を汚さないよう畳む。
            figureBaselines.delete(ev.source_id);
            const { [ev.source_id]: _drop, ...rest } = figureEtas;
            figureEtas = rest;
          }
        }
        currentNotebookStore.upsertSource({
          ...existing,
          status: ev.status as typeof existing.status,
          chunk_count: chunkCount,
          embedded,
          ...(figuresDone !== undefined ? { figures_done: figuresDone } : {}),
          ...(figuresTotal !== undefined ? { figures_total: figuresTotal } : {}),
          // 失敗時の本文と対処法。error イベントでのみ届く。
          ...(typeof ev.error_msg === 'string' ? { error_msg: ev.error_msg } : {}),
          ...(typeof ev.error_remediation === 'string'
            ? { error_remediation: ev.error_remediation }
            : {}),
          // 要約/ADRジョブの進行状態。ペイロードに含まれる場合のみ上書きし、
          // 含まれない従来イベント(取り込みパイプライン等)では既存値を維持する。
          // 明示 null は「中断→未生成へ復帰」の配信(cancel エンドポイント)。
          ...(typeof ev.summary_status === 'string' || ev.summary_status === null
            ? { summary_status: ev.summary_status as Source['summary_status'] }
            : {}),
          ...(typeof ev.adr_status === 'string'
            ? { adr_status: ev.adr_status as Source['adr_status'] }
            : {}),
          // READY イベントは本文を同梱する(BE契約)。再取得なしで即時表示する。
          ...(typeof ev.summary === 'string' ? { summary: ev.summary } : {}),
          ...(typeof ev.adr_draft === 'string' ? { adr_draft: ev.adr_draft } : {}),
          ...(typeof ev.adr_template === 'string'
            ? { adr_template: ev.adr_template as Source['adr_template'] }
            : {}),
          ...(typeof ev.adr_confidence === 'string'
            ? { adr_confidence: ev.adr_confidence as Source['adr_confidence'] }
            : {}),
        });
        if (prev !== ev.status) {
          const title = existing.title ?? existing.origin ?? "ソース";
          if (ev.status === "ready") {
            notify({
              title: "取り込み完了",
              body: title,
              tag: `source-ready-${ev.source_id}`,
            });
          } else if (ev.status === "error") {
            const errMsg = typeof ev.error_msg === "string" ? ev.error_msg : "";
            const detail = errMsg ? ` — ${errMsg}` : "";
            notify({
              title: "取り込み失敗",
              body: `${title}${detail}`,
              tag: `source-error-${ev.source_id}`,
            });
          }
          if (ev.status === "ready" || ev.status === "error") {
            // 終端状態: SSE payload には title 等のソース実データや親子リンクが
            // 含まれないため、upsertSource の patch だけでは古いプレースホルダ
            // (録音の optimistic source 等)が残る。sources/links を再取得して
            // 反映する(store 側で世代ガード + 多重発火の coalesce 済み)。
            void currentNotebookStore.refreshSources();
          }
        }
      });
    },
    stop() {
      close?.();
      lastStatus.clear();
      convSteps = {};
      visualIndexProgress = new Map();
      visualIndexOutcome = new Map();
      visualBaselines = new Map();
      figureBaselines.clear();
      figureEtas = {};
      close = null;
    },
  };
}

export const eventsStore = createEventsStore();

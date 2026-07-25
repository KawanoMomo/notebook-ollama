import { openNotebookEvents, type SourceStatusEvent } from "$lib/api/events";
import type { Source } from "$lib/api/types";
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
}

export interface VisualIndexOutcome {
  ok: boolean;
  // SSE イベントは同一 {ok} でも別の発生を区別できないため、発生時刻を
  // change-detection のキーとして使う(購読側 $effect が「新しい完了/失敗」を検知する)。
  at: number;
}

export interface EventsStore {
  start(notebookId: string): void;
  stop(): void;
  convStepFor(sourceId: string): ConvStep | undefined;
  readonly visualIndexProgress: VisualIndexProgress | null;
  readonly visualIndexOutcome: VisualIndexOutcome | null;
}

export function createEventsStore(): EventsStore {
  let close: (() => void) | null = null;
  const lastStatus = new Map<string, string>();
  // Latest pipeline step per source_id, driven by SSE payloads that carry `step`.
  let convSteps = $state<Record<string, ConvStep>>({});
  // 視覚インデックス構築ジョブはノートブック単位(ソース単位の activeJobs 機構とは
  // 別系統)なので、進捗/結果を専用の state として持つ(events.ts は全イベントを
  // 単一の "source_status" SSE イベント名で運ぶため、type で分岐する)。
  let visualIndexProgress = $state<VisualIndexProgress | null>(null);
  let visualIndexOutcome = $state<VisualIndexOutcome | null>(null);

  return {
    convStepFor(sourceId) {
      return convSteps[sourceId];
    },
    get visualIndexProgress() {
      return visualIndexProgress;
    },
    get visualIndexOutcome() {
      return visualIndexOutcome;
    },
    start(notebookId) {
      close?.();
      lastStatus.clear();
      convSteps = {};
      visualIndexProgress = null;
      visualIndexOutcome = null;
      close = openNotebookEvents(notebookId, (ev: SourceStatusEvent) => {
        // 視覚インデックスジョブのイベントには source_id が無いため、
        // 通常のソース状態パッチに入る前に分岐して処理する。
        if (ev.type === "visual_index_progress") {
          visualIndexProgress = {
            done: typeof ev.done === "number" ? ev.done : 0,
            total: typeof ev.total === "number" ? ev.total : 0,
          };
          return;
        }
        if (ev.type === "visual_index_complete") {
          visualIndexProgress = null;
          visualIndexOutcome = { ok: true, at: Date.now() };
          return;
        }
        if (ev.type === "visual_index_error") {
          visualIndexProgress = null;
          visualIndexOutcome = { ok: false, at: Date.now() };
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
        currentNotebookStore.upsertSource({
          ...existing,
          status: ev.status as typeof existing.status,
          chunk_count: chunkCount,
          embedded,
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
      visualIndexProgress = null;
      visualIndexOutcome = null;
      close = null;
    },
  };
}

export const eventsStore = createEventsStore();

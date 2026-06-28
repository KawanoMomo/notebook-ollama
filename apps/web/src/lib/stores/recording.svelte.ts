import { recordingsApi } from '$lib/api/recordings';
import { currentNotebookStore } from './currentNotebook.svelte';
import type { CurrentNotebookStore } from './currentNotebook.svelte';
import type { Source } from '$lib/api/types';

export interface LiveCaption {
  id: string;
  label: string;
  text: string;
  start_ms: number;
  is_final: boolean;
}

export interface RecordingStore {
  readonly recording: boolean;
  readonly recordingId: string | null;
  readonly sourceId: string | null;
  readonly notebookId: string | null;
  liveCaptionEnabled: boolean;
  readonly liveCaptionActive: boolean;
  readonly elapsedMs: number;
  readonly captions: LiveCaption[];
  readonly micLevel: number;
  readonly sysLevel: number;
  readonly error: string | null;
  start(notebookId: string): Promise<void>;
  stop(): Promise<void>;
  toggleLiveCaption(): void;
}

const MAX_CAPTIONS = 200;

/** dB (-80..0) を 0..1 のメータ比率へ。-80dB=0、0dB=1。 */
function dbToLevel(db: number): number {
  const clamped = Math.max(-80, Math.min(0, db));
  return (clamped + 80) / 80;
}

export function createRecordingStore(
  api = recordingsApi,
  nbStore: CurrentNotebookStore = currentNotebookStore,
): RecordingStore {
  let recording = $state(false);
  let recordingId = $state<string | null>(null);
  let sourceId = $state<string | null>(null);
  let notebookId = $state<string | null>(null);
  let liveCaptionEnabled = $state(true);
  let liveCaptionActive = $state(false);
  let elapsedMs = $state(0);
  let captions = $state<LiveCaption[]>([]);
  let micLevel = $state(0);
  let sysLevel = $state(0);
  let error = $state<string | null>(null);

  let timer: ReturnType<typeof setInterval> | null = null;
  let startedAt = 0;
  let ws: WebSocket | null = null;

  function clearTimer() {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  }

  function closeWs() {
    if (ws) {
      // onclose は破棄処理を呼ばないよう外しておく
      ws.onmessage = null;
      ws.onerror = null;
      ws.onclose = null;
      try {
        ws.close();
      } catch {
        // ignore
      }
      ws = null;
    }
  }

  function resetTransient() {
    clearTimer();
    closeWs();
    recording = false;
    recordingId = null;
    sourceId = null;
    notebookId = null;
    liveCaptionActive = false;
    elapsedMs = 0;
    captions = [];
    micLevel = 0;
    sysLevel = 0;
    startedAt = 0;
  }

  function handleMessage(raw: string) {
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return;
    }
    const type = msg.type;
    if (type === 'caption') {
      const cap: LiveCaption = {
        id: String(msg.id ?? ''),
        label: String(msg.label ?? ''),
        text: String(msg.text ?? ''),
        start_ms: Number(msg.start_ms ?? 0),
        is_final: Boolean(msg.is_final),
      };
      const idx = captions.findIndex((c) => c.id === cap.id);
      if (idx >= 0) {
        captions = captions.map((c, i) => (i === idx ? cap : c));
      } else {
        const next = [...captions, cap];
        captions = next.length > MAX_CAPTIONS ? next.slice(-MAX_CAPTIONS) : next;
      }
    } else if (type === 'level') {
      const channel = String(msg.channel ?? '');
      const db = Number(msg.rms_db ?? -80);
      const level = dbToLevel(db);
      if (channel === 'mic') {
        micLevel = level;
      } else if (channel === 'system') {
        sysLevel = level;
      }
    } else if (type === 'error') {
      error = String(msg.msg ?? 'recording error');
    }
  }

  function connectWs(rid: string) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(
      `${proto}://${location.host}/ws/recordings/${rid}/live`,
    );
    socket.onmessage = (e) => handleMessage(e.data as string);
    socket.onerror = () => {
      error = 'ライブ字幕の接続でエラーが発生しました';
    };
    ws = socket;
  }

  return {
    get recording() {
      return recording;
    },
    get recordingId() {
      return recordingId;
    },
    get sourceId() {
      return sourceId;
    },
    get notebookId() {
      return notebookId;
    },
    get liveCaptionEnabled() {
      return liveCaptionEnabled;
    },
    set liveCaptionEnabled(v: boolean) {
      liveCaptionEnabled = v;
    },
    get liveCaptionActive() {
      return liveCaptionActive;
    },
    get elapsedMs() {
      return elapsedMs;
    },
    get captions() {
      return captions;
    },
    get micLevel() {
      return micLevel;
    },
    get sysLevel() {
      return sysLevel;
    },
    get error() {
      return error;
    },
    async start(nbId) {
      if (recording) return;
      error = null;
      const started = await api.start(nbId, { live_caption: liveCaptionEnabled });
      recording = true;
      recordingId = started.recording_id;
      sourceId = started.source_id;
      notebookId = nbId;
      liveCaptionActive = started.live_caption;
      captions = [];
      micLevel = 0;
      sysLevel = 0;
      elapsedMs = 0;
      startedAt = Date.now();
      clearTimer();
      timer = setInterval(() => {
        elapsedMs = Date.now() - startedAt;
      }, 200);
      connectWs(started.recording_id);
    },
    async stop() {
      const nbId = notebookId;
      const rid = recordingId;
      const sid = sourceId; // resetTransient() が null 化する前に捕捉
      // タイマーと WS は即座に止める (UI を録音中表示のまま固めない)
      clearTimer();
      closeWs();
      try {
        if (nbId && rid) {
          await api.stop(nbId, rid);
          // 停止成功後、サイドバーに録音ソースを楽観的に追加する。
          // 以降の SSE(source_status) がこの source を既存として status/chunk_count/embedded を
          // パッチし、最終的に ready へ遷移してパネルが消える。
          if (sid) {
            const now = new Date().toISOString();
            const optimistic: Source = {
              id: sid,
              notebook_id: nbId,
              kind: 'recording',
              title: null,
              origin: '録音',
              status: 'parsing',
              error_msg: null,
              bytes: null,
              page_count: null,
              chunk_count: null,
              created_at: now,
              updated_at: now,
            };
            nbStore.upsertSource(optimistic);
          }
        }
      } catch (e) {
        error = e instanceof Error ? e.message : String(e);
      } finally {
        resetTransient();
      }
    },
    toggleLiveCaption() {
      liveCaptionEnabled = !liveCaptionEnabled;
    },
  };
}

export const recordingStore = createRecordingStore();

export interface ErrorBody {
  code: string;
  message: string;
  detail: string | null;
  remediation: string | null;
}

export interface ErrorResponse {
  error: ErrorBody;
}

export interface Notebook {
  id: string;
  name: string;
  description: string | null;
  default_model: string | null;
  created_at: string;
  updated_at: string;
  source_count: number;
}

export interface NotebookCreate {
  name: string;
  description?: string;
  default_model?: string;
}

export interface NotebookUpdate {
  name?: string;
  description?: string;
  /** null を明示送信するとノート既定をクリアし全体既定にフォールバックする。 */
  default_model?: string | null;
}

export type SourceStatus =
  | "pending"
  | "parsing"
  | "chunking"
  | "embedding"
  | "ready"
  | "error";

export type SourceKind =
  | "pdf"
  | "markdown"
  | "web"
  | "docx"
  | "pptx"
  | "xlsx"
  | "txt"
  | "recording";

export type SummaryStatus = 'generating' | 'ready' | 'error';
export type AdrStatus = 'generating' | 'ready' | 'error' | 'skipped';

export interface Source {
  id: string;
  notebook_id: string;
  kind: SourceKind;
  title: string | null;
  origin: string | null;
  status: SourceStatus;
  error_msg: string | null;
  bytes: number | null;
  page_count: number | null;
  chunk_count: number | null;
  has_audio?: boolean;
  /** 発表モード: スライドページ抽出済み (pdf/pptx)。backend: `has_slides`。 */
  has_slides?: boolean;
  /** Transient field populated from SSE during the embedding phase. */
  embedded?: number | null;
  duration_ms?: number | null;
  summary?: string | null;
  summary_status?: SummaryStatus | null;
  adr_draft?: string | null;
  adr_status?: AdrStatus | null;
  adr_template?: string | null;
  adr_confidence?: string | null;
  adr_generated_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Citation {
  n: number;
  chunk_id: string;
  source_id: string;
  source_title: string;
  location: string;
  url_or_path: string | null;
  snippet: string;
  audio_source_id: string | null;
  audio_start_ms: number | null;
  audio_channel: string | null;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  model: string | null;
  created_at: string;
}

export interface Conversation {
  id: string;
  notebook_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface ModelInfo {
  name: string;
  size_bytes: number | null;
  context_window: number | null;
  modified_at: string;
  kind: "chat" | "embedding" | "both" | "unknown";
  recommended_for: string[];
  embedding_dim: number | null;
}

export interface NotebookDefault {
  notebook_id: string;
  name: string;
  default_model: string | null;
}

export interface ModelsResponse {
  models: ModelInfo[];
  defaults_by_notebook: NotebookDefault[];
}

export interface OllamaSettings {
  endpoint: string;
  default_model: string;
  embedding_model: string;
  embedding_dim: number | null;
  request_timeout_seconds: number;
  chat_read_timeout_seconds: number;
}

export interface OllamaSettingsUpdate {
  default_model: string;
}

export interface GenerationSettings {
  context_budget_ratio: number;
  response_budget_tokens: number;
}

export interface RetrievalSettings {
  top_k: number;
  top_k_max: number;
  min_history_turns: number;
}

export interface AudioSettings {
  mic_device_index: number | null;
  system_device_index: number | null;
  whisper_model: string;
  device: "cuda" | "cpu";
  compute_type: "float16" | "int8_float16" | "int8";
  live_caption_default: boolean;
  agc_enabled: boolean;
  diarization_enabled: boolean;
  max_speakers: number | null;
  voiceprint_naming: boolean;
  name_inference_llm: boolean;
  name_threshold: number;
  storage_format: "aac" | "opus" | "mp3" | "wav";
  storage_bitrate_kbps: number;
  keep_audio: boolean;
  auto_title: boolean;
}

export type VoiceInputMode = 'off' | 'push_to_talk' | 'hands_free';

export interface VoiceInputSettings {
  mode: VoiceInputMode;
  ptt_key: string;
}

/**
 * クラッシュレポート機能のユーザ設定 (spec §7.3)。
 *
 * backend: `core/crash_reporter/settings.py::CrashReportSettings`
 * (settings.json の `crash_report` セクションに永続化)。
 *
 * - `enabled`     : `true` = 送信オプトイン済 / `false` = 明示的オプトアウト /
 *                   `null` = 未決定 (初回オプトインダイアログをまだ出していない)。
 * - `auto_prompt` : クラッシュ検知時に自動でオプトインダイアログを出すかどうか。
 *                   `false` でも未送信レポートはローカルに溜まり、設定画面や
 *                   フィードバックハブの「不具合」タブから手動で確認できる。
 * - `opted_in_at` : オプトイン (または明示的オプトアウト) を記録した時刻
 *                   (ISO 8601 文字列、未決定なら `null`)。
 */
export interface CrashReportSettings {
  enabled: boolean | null;
  auto_prompt: boolean;
  opted_in_at: string | null;
}

export interface AppSettings {
  ollama: OllamaSettings;
  generation: GenerationSettings;
  retrieval: RetrievalSettings;
  audio: AudioSettings;
  /**
   * クラッシュレポート設定。
   *
   * NOTE (Sprint 7 Task 7.2): backend `GET /api/settings` レスポンスへの追加は
   * 別タスク。現状の backend ではこのフィールドは含まれないため optional とし、
   * settings store 側で `?? DEFAULT_CRASH_REPORT` でフォールバックする。
   */
  crash_report?: CrashReportSettings;
  voice_input?: VoiceInputSettings | null;
  /** 開発者モード(spec 2026-07-02)。旧BEでは無いこともあるため optional。 */
  dev?: DevSettings;
}

export interface DevSettings {
  enabled: boolean;
  log_capacity_bytes: number;
}

export interface Stats {
  notebook_count: number;
  source_count: number;
  chunk_count: number;
  data_dir: string;
}

/** プロンプト挿入機能 (docs/specs/2026-06-26-prompt-injection-design.md) */
export interface FixedPromptSlotOut {
  title: string;
  body: string;
  icon_url: string | null;
}

export interface DropdownPromptOut {
  id: string;
  title: string;
  body: string;
}

export interface PromptsOut {
  fixed: FixedPromptSlotOut[]; // 常に長さ 3
  dropdown: DropdownPromptOut[];
}

export interface RetrievalHit {
  chunk_id: string;
  source_title: string;
  location: string;
  score: number;
}

export interface ReindexProgress {
  done: number;
  total: number;
}

export interface ReindexComplete {
  model: string;
  dim: number;
}

export interface ReindexError {
  message: string;
}

/* -------------------------------------------------------------------------- */
/* クラッシュレポート & お知らせ/フィードバックハブ                            */
/* spec: docs/specs/2026-06-28-crash-report-feedback-hub-design.md            */
/* backend: apps/api/routers/crash.py, apps/api/routers/feedback_hub.py       */
/* -------------------------------------------------------------------------- */

/** クラッシュ検知元 (spec §4.1)。backend `core/crash_reporter/pending_store.Source` と一致。 */
export type CrashSource =
  | "fastapi"
  | "excepthook"
  | "signal"
  | "atexit"
  | "frontend"
  | "unclean_shutdown";

/**
 * ハードウェアスナップショット。`core/crash_reporter/hardware.collect()` の戻り値。
 * 採取に失敗したキーは `"<unavailable>"` 文字列にフォールバックするため、
 * 数値が期待される値も `number | string` 共用体で表現する。
 *
 * NOTE: backend `_build_frontend_crash` は `dict(hardware or {})` を書き込むため、
 * frontend 由来のクラッシュではフィールドが部分的 / 空になり得る。
 * 全フィールド optional とし、consumer 側で `?? "<unavailable>"` 等のガードを義務付ける。
 */
export interface CrashHardware {
  cpu_model?: string;
  cpu_cores?: number | string;
  cpu_threads?: number | string;
  ram_total_gb?: number | string;
  ram_available_gb?: number | string;
  gpu_model?: string;
  gpu_vram_mb?: number | string;
  driver_version?: string;
  disk_free_gb?: number | string;
  os_platform?: string;
  python_version?: string;
}

/**
 * 未送信クラッシュレポート 1 件。
 * backend: `apps/api/routers/crash.py::PendingCrashOut`
 * (= `core/crash_reporter/pending_store.PendingCrash` dataclass の HTTP 表現)。
 */
export interface PendingCrash {
  id: string;
  fingerprint: string;
  /** ISO-8601 UTC (例: `"2026-06-28T00:00:00Z"`)。 */
  created_at: string;
  exception_type: string;
  exception_message: string;
  trace: string[];
  hardware: CrashHardware;
  /** 検疫済みの構造化ログ末尾。任意キーのため `unknown` 値で型付けする。 */
  log_tail: Array<Record<string, unknown>>;
  source: CrashSource;
}

/**
 * GitHub Issue 起票 prefill URL レスポンス。
 * backend: `apps/api/routers/crash.py::PrefillUrlOut`。
 * `truncated=true` の場合は log_tail が 8KB 制限内に収まるよう切り詰められている。
 */
export interface PrefillUrlResponse {
  url: string;
  truncated: boolean;
}

/** お知らせのサブセクション (見出し + 箇条書き、spec §5.3)。 */
export interface NoticeSubsection {
  heading: string;
  items: string[];
}

/**
 * 1 件のお知らせ。
 * backend: `apps/api/routers/feedback_hub.py::NoticeOut`
 * (= `core/feedback_hub/notice_store.Notice` dataclass)。
 */
export interface Notice {
  id: string;
  /** ISO-8601 `YYYY-MM-DD` (辞書順 = 時系列順)。 */
  date: string;
  title: string;
  /** Markdown 本文。 */
  body: string;
  subsections?: NoticeSubsection[] | null;
}

/**
 * 未読 / 未送信件数。
 * backend: `apps/api/routers/feedback_hub.py::UnreadCountOut`。
 * MVP では未送信クラッシュレポート数のみ。お知らせ未読は FE 側 localStorage で管理。
 */
export interface UnreadCount {
  count: number;
}

/** フィードバック分類。backend: `feedback_hub.KindLiteral` / `VALID_KINDS`。 */
export type FeedbackKind = "feature" | "complaint" | "impression";

/** 感情シグナル。backend: `feedback_hub.SentimentLiteral` / `VALID_SENTIMENTS`。 */
export type Sentiment = "up" | "neutral" | "down";

/**
 * フィードバック送信ペイロード。
 * backend: `apps/api/routers/feedback_hub.py::FeedbackIn`。
 * `screenshot_b64` は URL に直接埋め込めない (8KB 制限) ため、サーバには送るが
 * GitHub Issue prefill URL には載らない。
 */
export interface FeedbackInput {
  kind: FeedbackKind;
  body: string;
  sentiment?: Sentiment | null;
  screenshot_b64?: string | null;
}

/* -------------------------------------------------------------------------- */
/* 発表モード (プレゼンテーション連動録音)                                      */
/* backend: apps/api/routers/links.py, apps/api/routers/recordings.py         */
/* -------------------------------------------------------------------------- */

/** ソース親子リンク。backend: `apps/api/schemas/source.py::SourceLink`。 */
export interface SourceLink {
  id: string;
  notebook_id: string;
  parent_source_id: string;
  child_source_id: string;
  relation: 'presentation' | 'manual';
  meta: Record<string, unknown> | null;
  created_at: string;
}

/**
 * 進行中の録音セッション照会結果 (リロード復帰用、spec §6 中断・異常系)。
 * backend: `apps/api/schemas/recording.py::ActiveRecording`。
 * セッションが無い場合、backend は 204 を返し `client.ts` の `request<T>` は
 * `undefined` を返す。
 */
export interface ActiveRecording {
  recording_id: string;
  source_id: string;
  presentation_source_id: string | null;
  last_page: number | null;
  /** 録音経過時間(ms)。recordingStore.adopt が経過タイマー再開の起点に使う。 */
  elapsed_ms: number;
  /** セッション開始時の live_caption 設定。recordingStore.adopt へ素通しする。 */
  live_caption: boolean;
}

/**
 * スライド資料の該当ページで発言された録音チャンク 1 件(逆引き、Task 11)。
 * backend: `apps/api/schemas/source.py::SlideUtteranceItem`。
 */
export interface SlideUtteranceItem {
  child_source_id: string;
  child_title: string | null;
  chunk_id: string;
  start_ms: number | null;
  end_ms: number | null;
  speaker: string | null;
  text: string;
}

/**
 * ページ単位にグループ化した発言一覧。
 * backend: `GET /api/notebooks/{nid}/sources/{sid}/slide-utterances` のレスポンス要素。
 */
export interface SlideUtterancePage {
  page: number;
  items: SlideUtteranceItem[];
}

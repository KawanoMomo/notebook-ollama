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

export interface AppSettings {
  ollama: OllamaSettings;
  generation: GenerationSettings;
  retrieval: RetrievalSettings;
  audio: AudioSettings;
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

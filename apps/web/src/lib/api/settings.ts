import { request } from './client';
import type {
  AppSettings,
  AudioSettings,
  CrashReportSettings,
  OllamaSettings,
  OllamaSettingsUpdate,
  Stats,
  VoiceInputSettings,
} from './types';

export const settingsApi = {
  get: () => request<AppSettings>('/api/settings'),
  stats: () => request<Stats>('/api/stats'),
  putAudio: (audio: AudioSettings) =>
    request<AudioSettings>('/api/settings/audio', {
      method: 'PUT',
      body: JSON.stringify(audio),
    }),
  putOllama: (body: OllamaSettingsUpdate) =>
    request<OllamaSettings>('/api/settings/ollama', {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  putVisionModel: (model: string) =>
    request<{ vision_model: string }>('/api/settings/vision-model', {
      method: 'PUT',
      body: JSON.stringify({ model }),
    }),
  switchEmbedding: (model: string) =>
    request<unknown>('/api/settings/embedding/switch', {
      method: 'POST',
      body: JSON.stringify({ model }),
    }),
  putOllamaTimeouts: (request_timeout_seconds: number, chat_read_timeout_seconds: number) =>
    request<{ request_timeout_seconds: number; chat_read_timeout_seconds: number }>(
      '/api/settings/ollama/timeouts',
      {
        method: 'PUT',
        body: JSON.stringify({ request_timeout_seconds, chat_read_timeout_seconds }),
      },
    ),
  /** 開発者モードの更新(spec §9.2)。容量はBE側で 1MB..200MB にクランプされる。 */
  putDev: (enabled: boolean, log_capacity_bytes?: number) =>
    request<{ enabled: boolean; log_capacity_bytes: number }>('/api/settings/dev', {
      method: 'PUT',
      body: JSON.stringify({ enabled, log_capacity_bytes }),
    }),
  /** 生成設定の更新(応答トークン上限 = num_predict / 自動継続回数)。 */
  putGeneration: (response_budget_tokens: number, auto_continue_max?: number) =>
    request<{
      context_budget_ratio: number;
      response_budget_tokens: number;
      auto_continue_max: number;
    }>('/api/settings/generation', {
      method: 'PUT',
      body: JSON.stringify({ response_budget_tokens, auto_continue_max }),
    }),
  /**
   * クラッシュレポート設定の更新 (spec §7.3 / Sprint 7 Task 7.2)。
   *
   * backend endpoint `PUT /api/settings/crash-report` を想定。
   * patch は部分更新を許容するが、現状の backend 設計 (`save_section`
   * パターン) では full body を期待するため、呼び出し側 (settings store)
   * で「現行値 + patch」をマージしてから渡す。
   *
   * NOTE: 本エンドポイントの実装は Sprint 7 のバックエンド追補タスク
   * (`apps/api/routers/settings.py` に `put_crash_report` を追加) で完了予定。
   * 現在は frontend 側の結線のみ。
   */
  putCrashReport: (body: Partial<CrashReportSettings>) =>
    request<CrashReportSettings>('/api/settings/crash-report', {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  putVoiceInput: (body: VoiceInputSettings) =>
    request<VoiceInputSettings>('/api/settings/voice-input', {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
};

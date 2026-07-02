import { request } from './client';
import type {
  AppSettings,
  AudioSettings,
  OllamaSettings,
  OllamaSettingsUpdate,
  Stats,
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
};

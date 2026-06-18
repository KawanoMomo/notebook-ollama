import { request } from './client';
import type { AppSettings, AudioSettings, Stats } from './types';

export const settingsApi = {
  get: () => request<AppSettings>('/api/settings'),
  stats: () => request<Stats>('/api/stats'),
  putAudio: (audio: AudioSettings) =>
    request<AudioSettings>('/api/settings/audio', {
      method: 'PUT',
      body: JSON.stringify(audio),
    }),
};

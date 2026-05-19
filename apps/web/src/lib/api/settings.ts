import { request } from './client';
import type { AppSettings, Stats } from './types';

export const settingsApi = {
  get: () => request<AppSettings>('/api/settings'),
  stats: () => request<Stats>('/api/stats'),
};

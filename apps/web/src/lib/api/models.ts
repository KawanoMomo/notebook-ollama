import { request } from './client';
import type { ModelsResponse } from './types';

export const modelsApi = {
  list: () => request<ModelsResponse>('/api/models'),
};

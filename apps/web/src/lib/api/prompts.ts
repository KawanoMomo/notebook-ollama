import { request } from './client';
import type { DropdownPromptOut, PromptsOut } from './types';

export const promptsApi = {
  get: () => request<PromptsOut>('/api/prompts'),

  // 固定スロット
  putFixed: (slot: 0 | 1 | 2, title: string, body: string) =>
    request<PromptsOut>(`/api/prompts/fixed/${slot}`, {
      method: 'PUT',
      body: JSON.stringify({ title, body }),
    }),
  deleteFixed: (slot: 0 | 1 | 2) =>
    request<PromptsOut>(`/api/prompts/fixed/${slot}`, { method: 'DELETE' }),

  // アイコン(multipart/form-data なので Content-Type は自動)
  uploadIcon: (slot: 0 | 1 | 2, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<PromptsOut>(`/api/prompts/fixed/${slot}/icon`, {
      method: 'POST',
      body: form,
    });
  },
  deleteIcon: (slot: 0 | 1 | 2) =>
    request<PromptsOut>(`/api/prompts/fixed/${slot}/icon`, { method: 'DELETE' }),

  // プルダウン CRUD
  addDropdown: (title: string, body: string) =>
    request<DropdownPromptOut>('/api/prompts/dropdown', {
      method: 'POST',
      body: JSON.stringify({ title, body }),
    }),
  updateDropdown: (id: string, title: string, body: string) =>
    request<DropdownPromptOut>(`/api/prompts/dropdown/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ title, body }),
    }),
  deleteDropdown: (id: string) =>
    request<void>(`/api/prompts/dropdown/${id}`, { method: 'DELETE' }),
  reorderDropdown: (ids: string[]) =>
    request<PromptsOut>('/api/prompts/dropdown/order', {
      method: 'PUT',
      body: JSON.stringify({ ids }),
    }),
};

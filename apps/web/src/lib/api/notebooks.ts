import { request } from './client';
import type { Notebook, NotebookCreate, NotebookUpdate } from './types';

export const notebooksApi = {
  list: () => request<Notebook[]>('/api/notebooks'),
  get: (id: string) => request<Notebook>(`/api/notebooks/${id}`),
  create: (body: NotebookCreate) =>
    request<Notebook>('/api/notebooks', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  update: (id: string, body: NotebookUpdate) =>
    request<Notebook>(`/api/notebooks/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  delete: (id: string) =>
    request<void>(`/api/notebooks/${id}`, { method: 'DELETE' }),
};

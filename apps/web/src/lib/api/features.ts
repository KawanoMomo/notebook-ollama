/**
 * ベータ機能フラグ API クライアント。
 *
 * Matches backend `apps/api/routers/features.py` 1:1.
 *
 * Endpoints:
 * - `GET /api/features`        — list()
 * - `PUT /api/features/{id}`   — setOptin(id, enabled)
 *
 * Spec: docs/specs/2026-07-20-beta-feature-flags-design.md
 */
import { request } from './client';
import type { FeatureFlagInfo } from './types';

export const featuresApi = {
  list: () => request<{ features: FeatureFlagInfo[] }>('/api/features'),

  setOptin: (id: string, enabled: boolean) =>
    request<{ features: FeatureFlagInfo[] }>(`/api/features/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
    }),
};

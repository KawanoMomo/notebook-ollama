/**
 * crash API client.
 *
 * Matches backend `apps/api/routers/crash.py` 1:1.
 *
 * Endpoints:
 * - `GET    /api/crash/pending`                — listPending()
 * - `POST   /api/crash/report`                 — reportFrontendCrash(payload)
 * - `POST   /api/crash/{id}/dismiss`           — dismiss(id)  [204]
 * - `GET    /api/crash/{id}/prefill-url`       — getPrefillUrl(id)
 * - `POST   /api/crash/{id}/mark-reported`     — markReported(id)
 *
 * Spec: docs/specs/2026-06-28-crash-report-feedback-hub-design.md
 */
import { request } from './client';
import type { CrashSource, PendingCrash, PrefillUrlResponse } from './types';

/**
 * Frontend-originated crash payload for `POST /api/crash/report`.
 *
 * Matches backend `CrashReportIn` (apps/api/routers/crash.py):
 * - `message` is required (1..4000 chars enforced server-side).
 * - `stack` is the raw JS Error.stack string (up to ~20KB).
 * - `hardware` is a free-form dict (browser-side: typically `{ ua, gpu, ... }`).
 * - `source` defaults to `"frontend"` server-side; allow callers to override
 *   from the full `CrashSource` registry (a CLI integration may report
 *   `"signal"` etc. via this same endpoint in the future).
 */
export interface CrashReportInput {
  message: string;
  stack?: string;
  hardware?: Record<string, unknown>;
  source?: CrashSource;
}

export const crashApi = {
  listPending: () => request<PendingCrash[]>('/api/crash/pending'),

  reportFrontendCrash: (payload: CrashReportInput) =>
    request<PendingCrash>('/api/crash/report', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  dismiss: (id: string) =>
    request<void>(`/api/crash/${id}/dismiss`, { method: 'POST' }),

  getPrefillUrl: (id: string) =>
    request<PrefillUrlResponse>(`/api/crash/${id}/prefill-url`),

  /**
   * Backend returns `{ ok: true }` but callers don't use it — typed as
   * `void` to keep the surface minimal. The JSON is parsed and discarded
   * by the `request<void>()` typing.
   */
  markReported: (id: string) =>
    request<void>(`/api/crash/${id}/mark-reported`, { method: 'POST' }),
};

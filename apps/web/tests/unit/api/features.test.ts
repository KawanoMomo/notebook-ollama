/**
 * features API client tests (Task 4).
 *
 * Spec: docs/specs/2026-07-20-beta-feature-flags-design.md
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '$lib/api/client';
import { featuresApi } from '$lib/api/features';
import type { FeatureFlagInfo } from '$lib/api/types';

const originalFetch = global.fetch;
const fetchMock = () => global.fetch as ReturnType<typeof vi.fn>;

const sampleFlag: FeatureFlagInfo = {
  id: 'table-figure-rag',
  name: '表・図検索強化',
  description: 'PDFの表・図を抽出し、検索と回答に反映するベータ機能',
  stage: 'beta',
  enabled: false,
};

const jsonResponse = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const errorResponse = (status: number, code: string, message: string): Response =>
  new Response(
    JSON.stringify({ error: { code, message, detail: null, remediation: null } }),
    { status, headers: { 'Content-Type': 'application/json' } },
  );

describe('featuresApi.list', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('GETs /api/features and returns { features }', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse({ features: [sampleFlag] }));
    const out = await featuresApi.list();
    expect(fetchMock()).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock().mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/features');
    expect(init?.method ?? 'GET').toBe('GET');
    expect(out).toEqual({ features: [sampleFlag] });
  });

  it('returns features: [] when backend has no flags', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse({ features: [] }));
    const out = await featuresApi.list();
    expect(out.features).toEqual([]);
  });

  it('throws ApiError on 500', async () => {
    fetchMock().mockResolvedValueOnce(errorResponse(500, 'internal', 'boom'));
    await expect(featuresApi.list()).rejects.toBeInstanceOf(ApiError);
  });
});

describe('featuresApi.setOptin', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('PUTs /api/features/{id} with { enabled } and returns the updated list', async () => {
    const updated = { ...sampleFlag, enabled: true };
    fetchMock().mockResolvedValueOnce(jsonResponse({ features: [updated] }));
    const out = await featuresApi.setOptin('table-figure-rag', true);
    const [url, init] = fetchMock().mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/features/table-figure-rag');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body as string)).toEqual({ enabled: true });
    expect(out).toEqual({ features: [updated] });
  });

  it('sends enabled=false to opt out', async () => {
    fetchMock().mockResolvedValueOnce(
      jsonResponse({ features: [{ ...sampleFlag, enabled: false }] }),
    );
    await featuresApi.setOptin('table-figure-rag', false);
    const [, init] = fetchMock().mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ enabled: false });
  });

  it('throws ApiError on 400 for a GA flag (server rejects optin change)', async () => {
    // 実装: core/feature_service.py::set_optin が ErrorCode.VALIDATION_FAILED
    // ("validation.failed") を送出し、apps/api/main.py の status_map で 400 に写像される。
    fetchMock().mockResolvedValueOnce(
      errorResponse(400, 'validation.failed', 'GA機能のオプトインは変更できません'),
    );
    await expect(featuresApi.setOptin('some-ga-flag', true)).rejects.toMatchObject({
      status: 400,
    });
  });

  it('throws ApiError on 404 for an unknown flag id', async () => {
    fetchMock().mockResolvedValueOnce(
      errorResponse(404, 'storage.not_found', 'unknown feature flag: nope'),
    );
    await expect(featuresApi.setOptin('nope', true)).rejects.toMatchObject({ status: 404 });
  });
});

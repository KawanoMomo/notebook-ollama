/**
 * crash API client tests (Sprint 5 Task 5.2).
 *
 * Boundary coverage checklist (Sprint 1-3 lessons):
 * - Empty / missing optional fields (stack=undefined, hardware=undefined).
 * - Unicode CJK + emoji preserved through JSON serialization.
 * - Parametrize over the full CrashSource enum (no hand-rolled subset).
 * - Oversize string serialization (no client-side truncation; server-side concern).
 * - 4xx + 5xx error paths surface as thrown ApiError.
 * - Path interpolation with uuid-shaped id (hex 32 chars).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '$lib/api/client';
import { crashApi, type CrashReportInput } from '$lib/api/crash';
import type {
  CrashHardware,
  CrashSource,
  PendingCrash,
  PrefillUrlResponse,
} from '$lib/api/types';

const originalFetch = global.fetch;
const fetchMock = () => global.fetch as ReturnType<typeof vi.fn>;

/** All values of `CrashSource` (must equal `CrashSource` exactly — guards drift). */
const ALL_CRASH_SOURCES: CrashSource[] = [
  'fastapi',
  'excepthook',
  'signal',
  'atexit',
  'frontend',
  'unclean_shutdown',
];

const hw: CrashHardware = {
  cpu_model: 'Intel i9-12900KF',
  cpu_cores: 16,
  cpu_threads: 24,
  ram_total_gb: 32,
  ram_available_gb: 18.5,
  gpu_model: 'NVIDIA RTX 2080 Ti',
  gpu_vram_mb: 11264,
  driver_version: '551.86',
  disk_free_gb: 512,
  os_platform: 'Windows-11-10.0.26200',
  python_version: '3.12.4',
};

const samplePending: PendingCrash = {
  id: 'a'.repeat(32),
  fingerprint: 'b'.repeat(40),
  created_at: '2026-06-28T00:00:00Z',
  exception_type: 'FrontendError',
  exception_message: 'boom',
  trace: ['at fn (file.js:1:1)'],
  hardware: hw,
  log_tail: [],
  source: 'frontend',
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

describe('crashApi.listPending', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('GETs /api/crash/pending and returns the array', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse([samplePending]));
    const out = await crashApi.listPending();
    expect(fetchMock()).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock().mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/crash/pending');
    // GET is implicit — no method override means undefined (fetch default).
    expect(init?.method ?? 'GET').toBe('GET');
    expect(out).toEqual([samplePending]);
  });

  it('returns [] when backend returns []', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse([]));
    const out = await crashApi.listPending();
    expect(out).toEqual([]);
  });

  it('throws ApiError on 500', async () => {
    fetchMock().mockResolvedValueOnce(errorResponse(500, 'internal', 'boom'));
    await expect(crashApi.listPending()).rejects.toBeInstanceOf(ApiError);
  });
});

describe('crashApi.reportFrontendCrash', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('POSTs /api/crash/report with JSON body', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse(samplePending, 201));
    const payload: CrashReportInput = {
      message: 'TypeError: cannot read x',
      stack: 'at fn (file.js:1:1)',
      hardware: { ua: 'Mozilla/5.0' },
      source: 'frontend',
    };
    const out = await crashApi.reportFrontendCrash(payload);
    const [url, init] = fetchMock().mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/crash/report');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual(payload);
    expect(out).toEqual(samplePending);
  });

  it('serializes unicode CJK + emoji in message/stack without escaping loss', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse(samplePending));
    const cjkEmoji = 'クラッシュした 💥 にゃーん';
    await crashApi.reportFrontendCrash({ message: cjkEmoji, stack: cjkEmoji });
    const [, init] = fetchMock().mock.calls[0] as [string, RequestInit];
    const parsed = JSON.parse(init.body as string);
    expect(parsed.message).toBe(cjkEmoji);
    expect(parsed.stack).toBe(cjkEmoji);
  });

  it('omits absent optional fields rather than sending undefined', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse(samplePending));
    await crashApi.reportFrontendCrash({ message: 'm' });
    const [, init] = fetchMock().mock.calls[0] as [string, RequestInit];
    const parsed = JSON.parse(init.body as string);
    expect(parsed).toEqual({ message: 'm' });
    expect('stack' in parsed).toBe(false);
    expect('hardware' in parsed).toBe(false);
    expect('source' in parsed).toBe(false);
  });

  it.each(ALL_CRASH_SOURCES)(
    'accepts source=%s (parametrized over full CrashSource enum)',
    async (source) => {
      fetchMock().mockResolvedValueOnce(jsonResponse({ ...samplePending, source }));
      const out = await crashApi.reportFrontendCrash({ message: 'm', source });
      const [, init] = fetchMock().mock.calls[0] as [string, RequestInit];
      expect(JSON.parse(init.body as string).source).toBe(source);
      expect(out.source).toBe(source);
    },
  );

  it('forwards oversize message string verbatim (server enforces 4000 limit)', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse(samplePending));
    const big = 'x'.repeat(10_000);
    await crashApi.reportFrontendCrash({ message: big });
    const [, init] = fetchMock().mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string).message.length).toBe(10_000);
  });

  it('throws ApiError on 422 validation failure', async () => {
    fetchMock().mockResolvedValueOnce(
      errorResponse(422, 'validation.body', 'message: ensure this value has at most 4000 characters'),
    );
    await expect(
      crashApi.reportFrontendCrash({ message: '' }),
    ).rejects.toMatchObject({ status: 422 });
  });
});

describe('crashApi.dismiss', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('POSTs /api/crash/{id}/dismiss and returns void on 204', async () => {
    fetchMock().mockResolvedValueOnce(new Response(null, { status: 204 }));
    const id = 'a'.repeat(32);
    const out = await crashApi.dismiss(id);
    const [url, init] = fetchMock().mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/api/crash/${id}/dismiss`);
    expect(init.method).toBe('POST');
    expect(out).toBeUndefined();
  });

  it('throws ApiError on 404', async () => {
    fetchMock().mockResolvedValueOnce(errorResponse(404, 'crash.not_found', 'crash zzz not found'));
    await expect(crashApi.dismiss('zzz')).rejects.toMatchObject({ status: 404 });
  });
});

describe('crashApi.getPrefillUrl', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('GETs /api/crash/{id}/prefill-url and returns PrefillUrlResponse', async () => {
    const body: PrefillUrlResponse = {
      url: 'https://github.com/KawanoMomo/NotebookOllama/issues/new?title=x&body=y',
      truncated: false,
    };
    fetchMock().mockResolvedValueOnce(jsonResponse(body));
    const id = 'a'.repeat(32);
    const out = await crashApi.getPrefillUrl(id);
    const [url, init] = fetchMock().mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/api/crash/${id}/prefill-url`);
    expect(init?.method ?? 'GET').toBe('GET');
    expect(out).toEqual(body);
  });

  it('preserves truncated=true', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse({ url: 'https://x', truncated: true }));
    const out = await crashApi.getPrefillUrl('a');
    expect(out.truncated).toBe(true);
  });

  it('throws ApiError on 404', async () => {
    fetchMock().mockResolvedValueOnce(errorResponse(404, 'crash.not_found', 'gone'));
    await expect(crashApi.getPrefillUrl('zzz')).rejects.toMatchObject({ status: 404 });
  });
});

describe('crashApi.markReported', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('POSTs /api/crash/{id}/mark-reported', async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse({ ok: true }));
    const id = 'a'.repeat(32);
    // Typed as void — runtime value is whatever JSON the server returned
    // ({ok: true}), but callers MUST NOT rely on it. We only assert the
    // call shape and that the call resolves without throwing.
    await crashApi.markReported(id);
    const [url, init] = fetchMock().mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/api/crash/${id}/mark-reported`);
    expect(init.method).toBe('POST');
  });

  it('throws ApiError on 500', async () => {
    fetchMock().mockResolvedValueOnce(errorResponse(500, 'reported.store.write_failed', 'disk full'));
    await expect(crashApi.markReported('a')).rejects.toMatchObject({ status: 500 });
  });
});

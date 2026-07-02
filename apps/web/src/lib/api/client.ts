import type { ErrorResponse } from './types';

export class ApiError extends Error {
  constructor(
    public readonly code: string,
    public readonly status: number,
    message: string,
    public readonly detail: string | null = null,
    public readonly remediation: string | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export interface RequestOptions extends RequestInit {
  query?: Record<string, string | number | boolean | undefined>;
}

export async function request<T = unknown>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { query, ...init } = options;
  let url = path;
  if (query) {
    const params = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined) params.set(k, String(v));
    }
    const qs = params.toString();
    if (qs) url = `${path}?${qs}`;
  }
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  let response: Response;
  try {
    response = await fetch(url, { ...init, headers });
  } catch (cause) {
    throw new ApiError(
      'network.unreachable',
      0,
      'Network request failed',
      cause instanceof Error ? cause.message : String(cause),
    );
  }
  if (response.status === 204) {
    return undefined as T;
  }
  const contentType = response.headers.get('Content-Type') ?? '';
  const isJson = contentType.includes('application/json');
  if (!response.ok) {
    if (isJson) {
      // apps/api/routers/{crash,audio,recordings}.py raise plain FastAPI
      // HTTPException in a few not-found paths, which serializes as
      // `{"detail": "..."}` rather than the AppError envelope
      // `{"error": {code, message, ...}}` the rest of the API uses. Handle
      // both shapes instead of assuming `body.error` is always present.
      const body = (await response.json()) as ErrorResponse | { detail?: unknown };
      const err = 'error' in body ? body.error : undefined;
      if (err) {
        throw new ApiError(err.code, response.status, err.message, err.detail, err.remediation);
      }
      const detail =
        'detail' in body && typeof body.detail === 'string' ? body.detail : null;
      throw new ApiError(
        'http.error',
        response.status,
        detail ?? `HTTP ${response.status}`,
        detail,
      );
    }
    const text = await response.text();
    throw new ApiError(
      'http.error',
      response.status,
      `HTTP ${response.status}`,
      text || null,
    );
  }
  if (isJson) {
    return (await response.json()) as T;
  }
  return (await response.text()) as unknown as T;
}

import { accelerationApi, type AccelerationResponse } from '$lib/api/acceleration';

/**
 * Sprint 3 / Task 3.5 — Acceleration tab read-only store.
 *
 * Holds the resolved ``HwProfile`` + ``BackendPlan`` + Phase 1 gate fetched
 * from ``GET /api/settings/acceleration``. Phase 1 is read-only: there is
 * no ``put*`` method. ``load()`` is also the "Re-detect" handler — the
 * Phase 1 contract is "restart required for a full re-probe", but issuing
 * ``load()`` re-fetches the cached lifespan-time snapshot which is what
 * the [Re-detect] button surfaces today.
 */

export interface AccelerationStore {
  readonly data: AccelerationResponse | null;
  readonly loading: boolean;
  readonly error: string | null;
  load(): Promise<void>;
}

export function createAccelerationStore(api = accelerationApi): AccelerationStore {
  let data = $state<AccelerationResponse | null>(null);
  let loading = $state(false);
  let error = $state<string | null>(null);

  return {
    get data() {
      return data;
    },
    get loading() {
      return loading;
    },
    get error() {
      return error;
    },
    async load() {
      loading = true;
      error = null;
      try {
        data = await api.get();
      } catch (e) {
        error = e instanceof Error ? e.message : String(e);
      } finally {
        loading = false;
      }
    },
  };
}

export const accelerationStore = createAccelerationStore();

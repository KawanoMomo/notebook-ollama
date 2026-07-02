# ジョブ状態可視化 + Optimistic UI 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ノート詳細ページに進行中ジョブ(取り込み/要約/ADR)の永続ステータスバーを追加し、録音開始/停止ボタンを optimistic UI 化する。

**Architecture:** 新しいストア/SSE接続は追加しない。フロントのSSEハンドラが捨てている `summary_status`/`adr_status` を patch するよう修正した上で、既存 `currentNotebookStore.sources` から `$derived` で進行中ジョブ一覧を導出し、新規 `JobStatusBar.svelte` が表示する。録音は `recordingStore` に `starting`/`stopping` の同期的 pending 状態を追加する。

**Tech Stack:** SvelteKit 5 (runes: `$state`/`$derived`), vitest + @testing-library/svelte, Playwright (evaluator agent による実機検証)

**Spec:** `docs/specs/2026-07-02-job-status-bar-optimistic-ui-design.md` (承認済み)

## Global Constraints

- ブランチ: `spec/async-job-status-optimistic-ui` で作業する(master 直接作業禁止)
- **GUI変更は vitest GREEN だけで PASS 判定しない。Playwright 実機スクリーンショット検証(Task 5)が必須**(ユーザー恒久指示)
- バックエンド(Python)は変更しない。SSEペイロードには `summary_status`/`adr_status` が既に含まれている(`core/summary/summarizer.py:70-75`、`core/adr/adr_job.py:77-84` が発行済み)
- フロントのテスト実行: `cd apps/web && npx vitest run <file>` (bash から実行。PowerShell 直接の npm はStrictMode問題あり)
- コミットメッセージは日本語可、松尾: `feat:`/`fix:`/`test:` プレフィックス

## File Structure

| ファイル | 操作 | 責務 |
|---|---|---|
| `apps/web/src/lib/stores/events.svelte.ts` | Modify | SSEハンドラ。`summary_status`/`adr_status` を patch に追加 |
| `apps/web/src/lib/stores/currentNotebook.svelte.ts` | Modify | `ActiveJob` 型と `activeJobs` $derived getter を追加 |
| `apps/web/src/lib/components/JobStatusBar.svelte` | Create | ジョブ表示バー(presentation component、props でジョブ配列を受ける) |
| `apps/web/src/routes/notebooks/[id]/+page.svelte` | Modify | topbar 直下に JobStatusBar を配置、convStep を合成 |
| `apps/web/src/lib/stores/recording.svelte.ts` | Modify | `starting`/`stopping` state 追加、start/stop の optimistic 化 |
| `apps/web/src/lib/components/SourcesPanel.svelte` | Modify | rec-icon ボタンの starting 対応 |
| `apps/web/src/lib/components/RecordingControls.svelte` | Modify | 停止ボタンの stopping 対応 |
| `apps/web/tests/unit/stores/events.test.ts` | Create | SSE patch のユニットテスト |
| `apps/web/tests/unit/currentNotebook.test.ts` | Modify | activeJobs のユニットテスト追加 |
| `apps/web/tests/unit/JobStatusBar.test.ts` | Create | バー表示のコンポーネントテスト |
| `apps/web/tests/unit/stores/recording.test.ts` | Modify | starting/stopping のユニットテスト追加 |

---

### Task 1: SSEハンドラに summary_status / adr_status の patch を追加

現状 `events.svelte.ts` の SSE ハンドラは `status`/`chunk_count`/`embedded` しか `upsertSource` に渡さず、ペイロードの `summary_status`/`adr_status` を捨てている。このため要約/ADR完了がストアに届かない(生成中スピナーが止まらない潜在バグ)。

**Files:**
- Modify: `apps/web/src/lib/stores/events.svelte.ts`
- Create: `apps/web/tests/unit/stores/events.test.ts`

**Interfaces:**
- Consumes: `currentNotebookStore.upsertSource(s: Source)` (既存)
- Produces: SSEイベントの `summary_status`/`adr_status` フィールドが `currentNotebookStore.sources` に反映される(Task 2 の activeJobs がこれに依存)

- [ ] **Step 1: 失敗するテストを書く**

`apps/web/tests/unit/stores/events.test.ts` を新規作成:

```typescript
/**
 * events ストアの SSE ハンドラが summary_status / adr_status を
 * currentNotebookStore へ patch することを検証する。
 * 設計: docs/specs/2026-07-02-job-status-bar-optimistic-ui-design.md
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Source } from '$lib/api/types';
import type { SourceStatusEvent } from '$lib/api/events';

// openNotebookEvents をモックし、ハンドラ(onEvent)を捕捉して手動でイベントを流す
let capturedOnEvent: ((ev: SourceStatusEvent) => void) | null = null;
vi.mock('$lib/api/events', () => ({
  openNotebookEvents: vi.fn(
    (_id: string, onEvent: (ev: SourceStatusEvent) => void) => {
      capturedOnEvent = onEvent;
      return () => {};
    },
  ),
}));

// モック定義後に import する(hoisting のため dynamic import を使う)
const { eventsStore } = await import('$lib/stores/events.svelte');
const { currentNotebookStore } = await import('$lib/stores/currentNotebook.svelte');

function makeSource(overrides: Partial<Source> = {}): Source {
  return {
    id: 'src1',
    notebook_id: 'nb1',
    kind: 'recording',
    title: '議事録 A',
    origin: '録音',
    status: 'ready',
    error_msg: null,
    bytes: null,
    page_count: null,
    chunk_count: 8,
    created_at: 't',
    updated_at: 't',
    summary_status: 'generating',
    adr_status: 'generating',
    ...overrides,
  };
}

beforeEach(() => {
  capturedOnEvent = null;
  currentNotebookStore.clear();
});

afterEach(() => {
  eventsStore.stop();
  currentNotebookStore.clear();
});

describe('events store — summary_status / adr_status patch', () => {
  it('ペイロードに summary_status があればストアの source へ反映する', () => {
    currentNotebookStore.upsertSource(makeSource());
    eventsStore.start('nb1');
    capturedOnEvent!({
      source_id: 'src1',
      status: 'ready',
      summary_status: 'ready',
    });
    expect(currentNotebookStore.sources[0].summary_status).toBe('ready');
    // adr_status はペイロードに無いので既存値を維持
    expect(currentNotebookStore.sources[0].adr_status).toBe('generating');
  });

  it('ペイロードに adr_status があればストアの source へ反映する', () => {
    currentNotebookStore.upsertSource(makeSource());
    eventsStore.start('nb1');
    capturedOnEvent!({
      source_id: 'src1',
      status: 'ready',
      adr_status: 'ready',
    });
    expect(currentNotebookStore.sources[0].adr_status).toBe('ready');
    expect(currentNotebookStore.sources[0].summary_status).toBe('generating');
  });

  it('どちらも無いペイロードでは両フィールドの既存値を維持する', () => {
    currentNotebookStore.upsertSource(makeSource());
    eventsStore.start('nb1');
    capturedOnEvent!({ source_id: 'src1', status: 'ready' });
    expect(currentNotebookStore.sources[0].summary_status).toBe('generating');
    expect(currentNotebookStore.sources[0].adr_status).toBe('generating');
  });
});
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd apps/web && npx vitest run tests/unit/stores/events.test.ts`
Expected: FAIL — `summary_status` が `'ready'` にならず `'generating'` のまま(1・2番目のテストが落ちる。3番目はパスする)

- [ ] **Step 3: 最小実装**

`apps/web/src/lib/stores/events.svelte.ts` の `upsertSource` 呼び出し(現在の54-59行)を修正:

```typescript
        currentNotebookStore.upsertSource({
          ...existing,
          status: ev.status as typeof existing.status,
          chunk_count: chunkCount,
          embedded,
          // 要約/ADRジョブの進行状態。ペイロードに含まれる場合のみ上書きし、
          // 含まれない従来イベント(取り込みパイプライン等)では既存値を維持する。
          ...(typeof ev.summary_status === 'string'
            ? { summary_status: ev.summary_status as Source['summary_status'] }
            : {}),
          ...(typeof ev.adr_status === 'string'
            ? { adr_status: ev.adr_status as Source['adr_status'] }
            : {}),
        });
```

ファイル先頭の import に `Source` 型を追加:

```typescript
import type { Source } from '$lib/api/types';
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd apps/web && npx vitest run tests/unit/stores/events.test.ts`
Expected: PASS (3 tests)

- [ ] **Step 5: 既存テストの回帰確認**

Run: `cd apps/web && npx vitest run`
Expected: 全テスト PASS

- [ ] **Step 6: コミット**

```bash
git add apps/web/src/lib/stores/events.svelte.ts apps/web/tests/unit/stores/events.test.ts
git commit -m "fix(web): SSEハンドラが summary_status / adr_status を捨てていた問題を修正

バックエンド (summarizer.py / adr_job.py) は両フィールドをSSEで発行して
いるが、フロントの upsertSource が status/chunk_count/embedded しか
patch しないため、要約/ADR完了がストアに届かず生成中表示が止まらな
かった。ペイロードに含まれる場合のみ上書きする。"
```

---

### Task 2: currentNotebookStore に activeJobs derived getter を追加

**Files:**
- Modify: `apps/web/src/lib/stores/currentNotebook.svelte.ts`
- Modify: `apps/web/tests/unit/currentNotebook.test.ts` (テスト追加)

**Interfaces:**
- Consumes: `sources` ($state、既存)
- Produces: `export interface ActiveJob { sourceId: string; kind: 'ingest' | 'summary' | 'adr'; label: string }` と `readonly activeJobs: ActiveJob[]`。Task 3 の JobStatusBar と +page.svelte がこれに依存。

- [ ] **Step 1: 失敗するテストを書く**

`apps/web/tests/unit/currentNotebook.test.ts` の末尾に追加(既存の import / describe 構造は変更しない。既存テストが `createCurrentNotebookStore` を import していない場合は import を追加する):

```typescript
import { createCurrentNotebookStore } from '$lib/stores/currentNotebook.svelte';
import type { Source } from '$lib/api/types';

function makeJobSource(overrides: Partial<Source> = {}): Source {
  return {
    id: 'src1',
    notebook_id: 'nb1',
    kind: 'pdf',
    title: '設計書.pdf',
    origin: null,
    status: 'ready',
    error_msg: null,
    bytes: null,
    page_count: null,
    chunk_count: null,
    created_at: 't',
    updated_at: 't',
    ...overrides,
  };
}

describe('currentNotebookStore.activeJobs', () => {
  it('ready のみのソースでは空配列', () => {
    const store = createCurrentNotebookStore();
    store.upsertSource(makeJobSource());
    expect(store.activeJobs).toEqual([]);
  });

  it('取り込み中 (parsing/embedding 等) は ingest ジョブになる', () => {
    const store = createCurrentNotebookStore();
    store.upsertSource(makeJobSource({ status: 'parsing' }));
    expect(store.activeJobs).toEqual([
      { sourceId: 'src1', kind: 'ingest', label: '設計書.pdf: 取り込み中' },
    ]);
  });

  it('summary_status/adr_status が generating なら各ジョブになる(同一ソースで複数可)', () => {
    const store = createCurrentNotebookStore();
    store.upsertSource(
      makeJobSource({ summary_status: 'generating', adr_status: 'generating' }),
    );
    expect(store.activeJobs).toEqual([
      { sourceId: 'src1', kind: 'summary', label: '設計書.pdf: 要約生成中' },
      { sourceId: 'src1', kind: 'adr', label: '設計書.pdf: ADR生成中' },
    ]);
  });

  it('error / skipped は進行中として扱わない', () => {
    const store = createCurrentNotebookStore();
    store.upsertSource(
      makeJobSource({
        status: 'error',
        summary_status: 'error',
        adr_status: 'skipped',
      }),
    );
    expect(store.activeJobs).toEqual([]);
  });

  it('title が無ければ origin、それも無ければ「ソース」をラベルに使う', () => {
    const store = createCurrentNotebookStore();
    store.upsertSource(
      makeJobSource({ title: null, origin: '録音', status: 'parsing' }),
    );
    expect(store.activeJobs[0].label).toBe('録音: 取り込み中');
  });
});
```

(既に同名の import がテストファイル冒頭にある場合は重複させないこと)

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd apps/web && npx vitest run tests/unit/currentNotebook.test.ts`
Expected: FAIL — `store.activeJobs is undefined`

- [ ] **Step 3: 最小実装**

`apps/web/src/lib/stores/currentNotebook.svelte.ts` に追加。

interface 定義(`CurrentNotebookStore` の上)に追加:

```typescript
/** JobStatusBar に表示する進行中ジョブ1件。 */
export interface ActiveJob {
  sourceId: string;
  kind: 'ingest' | 'summary' | 'adr';
  label: string;
}
```

`CurrentNotebookStore` interface に追加(`readonly error: string | null;` の下):

```typescript
  /** 進行中ジョブ一覧(取り込み/要約/ADR)。JobStatusBar が購読する。 */
  readonly activeJobs: ActiveJob[];
```

factory 内、`let error = $state<string | null>(null);` の下に追加:

```typescript
  // 進行中ジョブの導出。判定条件は spec 2026-07-02 に基づく:
  // status ∈ {pending,parsing,chunking,embedding} / summary_status==='generating'
  // / adr_status==='generating'。error/skipped は進行中として扱わない。
  const INGEST_ACTIVE = new Set(['pending', 'parsing', 'chunking', 'embedding']);
  const activeJobs = $derived.by<ActiveJob[]>(() => {
    const jobs: ActiveJob[] = [];
    for (const s of sources) {
      const name = s.title ?? s.origin ?? 'ソース';
      if (INGEST_ACTIVE.has(s.status)) {
        jobs.push({ sourceId: s.id, kind: 'ingest', label: `${name}: 取り込み中` });
      }
      if (s.summary_status === 'generating') {
        jobs.push({ sourceId: s.id, kind: 'summary', label: `${name}: 要約生成中` });
      }
      if (s.adr_status === 'generating') {
        jobs.push({ sourceId: s.id, kind: 'adr', label: `${name}: ADR生成中` });
      }
    }
    return jobs;
  });
```

return オブジェクトに getter を追加(`get error()` の下):

```typescript
    get activeJobs() {
      return activeJobs;
    },
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd apps/web && npx vitest run tests/unit/currentNotebook.test.ts`
Expected: PASS (既存テスト含む全件)

- [ ] **Step 5: コミット**

```bash
git add apps/web/src/lib/stores/currentNotebook.svelte.ts apps/web/tests/unit/currentNotebook.test.ts
git commit -m "feat(web): currentNotebookStore に進行中ジョブの activeJobs getter を追加"
```

---

### Task 3: JobStatusBar コンポーネントとページ組み込み

**Files:**
- Create: `apps/web/src/lib/components/JobStatusBar.svelte`
- Modify: `apps/web/src/routes/notebooks/[id]/+page.svelte`
- Create: `apps/web/tests/unit/JobStatusBar.test.ts`

**Interfaces:**
- Consumes: `ActiveJob` (Task 2)、`ConvStep` (`$lib/stores/events.svelte` 既存 export)、`Spinner.svelte` (既存、props: `size?: number`)
- Produces: `JobStatusBar` props: `jobs: Array<ActiveJob & { step?: ConvStep }>`。presentation component であり、ストアへの直接依存を持たない(テスト容易性のため。ストアとの接続は +page.svelte 側で行う)。

- [ ] **Step 1: 失敗するテストを書く**

`apps/web/tests/unit/JobStatusBar.test.ts` を新規作成:

```typescript
/**
 * JobStatusBar — 進行中ジョブの永続表示バー。
 * 設計: docs/specs/2026-07-02-job-status-bar-optimistic-ui-design.md
 */
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/svelte';
import JobStatusBar from '$lib/components/JobStatusBar.svelte';

afterEach(() => cleanup());

describe('JobStatusBar', () => {
  it('ジョブ0件では何も描画しない', () => {
    const { container } = render(JobStatusBar, { jobs: [] });
    expect(container.querySelector('.jobbar')).toBeNull();
  });

  it('ジョブごとにラベルを1行ずつ表示する', () => {
    render(JobStatusBar, {
      jobs: [
        { sourceId: 's1', kind: 'summary', label: '議事録.docx: 要約生成中' },
        { sourceId: 's1', kind: 'adr', label: '議事録.docx: ADR生成中' },
      ],
    });
    expect(screen.getByText('議事録.docx: 要約生成中')).toBeDefined();
    expect(screen.getByText('議事録.docx: ADR生成中')).toBeDefined();
  });

  it('step があれば step_label と進捗%を併記する', () => {
    render(JobStatusBar, {
      jobs: [
        {
          sourceId: 's1',
          kind: 'ingest',
          label: '録音: 取り込み中',
          step: { step: 'stt', step_label: '文字起こし中', progress: 0.4 },
        },
      ],
    });
    expect(screen.getByText(/文字起こし中/)).toBeDefined();
    expect(screen.getByText(/40%/)).toBeDefined();
  });

  it('スクリーンリーダー向けに role=status を持つ', () => {
    render(JobStatusBar, {
      jobs: [{ sourceId: 's1', kind: 'summary', label: 'x: 要約生成中' }],
    });
    expect(screen.getByRole('status')).toBeDefined();
  });
});
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd apps/web && npx vitest run tests/unit/JobStatusBar.test.ts`
Expected: FAIL — `Cannot find module '$lib/components/JobStatusBar.svelte'`

- [ ] **Step 3: コンポーネント実装**

`apps/web/src/lib/components/JobStatusBar.svelte` を新規作成:

```svelte
<script lang="ts">
  import Spinner from './Spinner.svelte';
  import type { ActiveJob } from '$lib/stores/currentNotebook.svelte';
  import type { ConvStep } from '$lib/stores/events.svelte';

  interface Props {
    jobs: Array<ActiveJob & { step?: ConvStep }>;
  }
  let { jobs }: Props = $props();
</script>

{#if jobs.length > 0}
  <div class="jobbar" role="status" aria-live="polite">
    {#each jobs as j (j.kind + ':' + j.sourceId)}
      <span class="job">
        <Spinner size={12} />
        <span class="label">
          {j.label}{#if j.step?.step_label}（{j.step.step_label}{#if j.step.progress > 0}
              {Math.round(j.step.progress * 100)}%{/if}）{/if}
        </span>
      </span>
    {/each}
  </div>
{/if}

<style>
  .jobbar {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-4);
    padding: 6px var(--space-5);
    background: var(--color-bg-elevated);
    border-bottom: 1px solid var(--color-border);
    font-size: 12px;
    color: var(--color-fg);
  }
  .job {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--color-accent);
  }
  .label {
    color: var(--color-fg);
  }
</style>
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd apps/web && npx vitest run tests/unit/JobStatusBar.test.ts`
Expected: PASS (4 tests)

- [ ] **Step 5: ページへ組み込む**

`apps/web/src/routes/notebooks/[id]/+page.svelte` を修正。

script の import に追加:

```typescript
  import JobStatusBar from '$lib/components/JobStatusBar.svelte';
```

script 内(`const selectedModel = $derived(...)` の下あたり)に追加:

```typescript
  // 進行中ジョブに録音変換パイプラインの step 情報(あれば)を合成する。
  // summary/adr ジョブは step を発行しないため ingest のみ対象。
  const jobRows = $derived(
    currentNotebookStore.activeJobs.map((j) => ({
      ...j,
      step: j.kind === 'ingest' ? eventsStore.convStepFor(j.sourceId) : undefined,
    })),
  );
```

マークアップ: `</div>`(topbar の閉じタグ、現在の116行)の直後・`{#if currentNotebookStore.loading}` の前に追加:

```svelte
  <JobStatusBar jobs={jobRows} />
```

- [ ] **Step 6: 全テスト回帰 + 型チェック**

Run: `cd apps/web && npx vitest run && npx svelte-check --tsconfig ./tsconfig.json 2>&1 | tail -5`
Expected: vitest 全 PASS。svelte-check で新規エラーなし(既存エラーがある場合は増えていないこと)

- [ ] **Step 7: コミット**

```bash
git add apps/web/src/lib/components/JobStatusBar.svelte "apps/web/src/routes/notebooks/[id]/+page.svelte" apps/web/tests/unit/JobStatusBar.test.ts
git commit -m "feat(web): 進行中ジョブの永続ステータスバー JobStatusBar を追加

topbar 直下に取り込み/要約/ADR の進行中ジョブを常時表示する。
0件のときは非表示でレイアウトに影響しない。録音変換の step 情報
(convStepFor) があれば進捗%を併記する。"
```

---

### Task 4: recordingStore の optimistic UI (starting / stopping)

**Files:**
- Modify: `apps/web/src/lib/stores/recording.svelte.ts`
- Modify: `apps/web/src/lib/components/SourcesPanel.svelte`
- Modify: `apps/web/src/lib/components/RecordingControls.svelte`
- Modify: `apps/web/tests/unit/stores/recording.test.ts` (テスト追加)

**Interfaces:**
- Consumes: 既存 `RecordingStore` (`recording`, `start()`, `stop()`)
- Produces: `readonly starting: boolean` / `readonly stopping: boolean` を `RecordingStore` interface に追加。UI コンポーネントがこれに依存。

- [ ] **Step 1: 失敗するテストを書く**

`apps/web/tests/unit/stores/recording.test.ts` の describe 内に追加:

```typescript
  it('start は API 応答前に starting=true、応答後に recording=true / starting=false', async () => {
    let resolveStart!: (v: unknown) => void;
    const api = {
      start: vi.fn().mockReturnValue(
        new Promise((res) => {
          resolveStart = res;
        }),
      ),
      stop: vi.fn(),
    };
    const store = createRecordingStore(api as never, noopNbStore);

    const p = store.start('nb1');
    // await 前 = API 応答前: optimistic に starting が立ち、recording はまだ false
    expect(store.starting).toBe(true);
    expect(store.recording).toBe(false);

    resolveStart({
      recording_id: 'r1',
      source_id: 's1',
      status: 'recording',
      live_caption: false,
    });
    await p;
    expect(store.starting).toBe(false);
    expect(store.recording).toBe(true);
  });

  it('api.start 失敗時は starting=false に戻り recording は false のまま(例外は伝播)', async () => {
    const api = {
      start: vi.fn().mockRejectedValue(new Error('mic busy')),
      stop: vi.fn(),
    };
    const store = createRecordingStore(api as never, noopNbStore);
    await expect(store.start('nb1')).rejects.toThrow('mic busy');
    expect(store.starting).toBe(false);
    expect(store.recording).toBe(false);
  });

  it('stop は API 応答前に stopping=true、完了後に stopping=false', async () => {
    let resolveStop!: (v: unknown) => void;
    const api = {
      start: vi.fn().mockResolvedValue({
        recording_id: 'r1',
        source_id: 's1',
        status: 'recording',
        live_caption: false,
      }),
      stop: vi.fn().mockReturnValue(
        new Promise((res) => {
          resolveStop = res;
        }),
      ),
    };
    const store = createRecordingStore(api as never, noopNbStore);
    await store.start('nb1');

    const p = store.stop();
    expect(store.stopping).toBe(true);

    resolveStop({ recording_id: 'r1', source_id: 's1', status: 'processing', paths: {} });
    await p;
    expect(store.stopping).toBe(false);
    expect(store.recording).toBe(false);
  });

  it('starting 中の二重 start は no-op', async () => {
    let resolveStart!: (v: unknown) => void;
    const api = {
      start: vi.fn().mockReturnValue(
        new Promise((res) => {
          resolveStart = res;
        }),
      ),
      stop: vi.fn(),
    };
    const store = createRecordingStore(api as never, noopNbStore);
    const p = store.start('nb1');
    void store.start('nb1'); // 二重呼び出し
    expect(api.start).toHaveBeenCalledTimes(1);
    resolveStart({
      recording_id: 'r1',
      source_id: 's1',
      status: 'recording',
      live_caption: false,
    });
    await p;
  });
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `cd apps/web && npx vitest run tests/unit/stores/recording.test.ts`
Expected: FAIL — `store.starting is undefined`

- [ ] **Step 3: ストア実装**

`apps/web/src/lib/stores/recording.svelte.ts` を修正。

`RecordingStore` interface に追加(`readonly recording: boolean;` の下):

```typescript
  /** start() の API 応答待ち。クリック直後の optimistic pending 表示に使う。 */
  readonly starting: boolean;
  /** stop() の API 応答待ち。 */
  readonly stopping: boolean;
```

factory 内の state 宣言に追加(`let recording = $state(false);` の下):

```typescript
  let starting = $state(false);
  let stopping = $state(false);
```

return オブジェクトに getter を追加(`get recording()` の下):

```typescript
    get starting() {
      return starting;
    },
    get stopping() {
      return stopping;
    },
```

`start()` を修正(optimistic: API 呼び出し前に同期的に starting を立て、成否に関わらず finally で戻す):

```typescript
    async start(nbId) {
      if (recording || starting) return;
      error = null;
      // optimistic pending: API 応答を待たずにボタンを即座に反応させる。
      // 失敗時は finally で戻り、recording は false のままなのでロールバック不要。
      starting = true;
      try {
        const started = await api.start(nbId, { live_caption: liveCaptionEnabled });
        recording = true;
        recordingId = started.recording_id;
        sourceId = started.source_id;
        notebookId = nbId;
        liveCaptionActive = started.live_caption;
        captions = [];
        micLevel = 0;
        sysLevel = 0;
        elapsedMs = 0;
        startedAt = Date.now();
        micMuted = false;
        systemMuted = false;
        clearTimer();
        timer = setInterval(() => {
          elapsedMs = Date.now() - startedAt;
        }, 200);
        intentionalClose = false; // 新規接続。onclose での自動再接続を許可する
        reconnectAttempts = 0;
        connectWs(started.recording_id);
      } finally {
        starting = false;
      }
    },
```

`stop()` を修正(先頭に stopping ガードと optimistic セット、finally で解除):

```typescript
    async stop() {
      if (stopping) return;
      stopping = true;
      const nbId = notebookId;
      const rid = recordingId;
      const sid = sourceId; // resetTransient() が null 化する前に捕捉
      // タイマーと WS は即座に止める (UI を録音中表示のまま固めない)
      clearTimer();
      closeWs();
      try {
        if (nbId && rid) {
          await api.stop(nbId, rid);
          // 停止成功後、サイドバーに録音ソースを楽観的に追加する。
          // 以降の SSE(source_status) がこの source を既存として status/chunk_count/embedded を
          // パッチし、最終的に ready へ遷移してパネルが消える。
          if (sid) {
            const now = new Date().toISOString();
            const optimistic: Source = {
              id: sid,
              notebook_id: nbId,
              kind: 'recording',
              title: null,
              origin: '録音',
              status: 'parsing',
              error_msg: null,
              bytes: null,
              page_count: null,
              chunk_count: null,
              created_at: now,
              updated_at: now,
            };
            nbStore.upsertSource(optimistic);
          }
        }
      } catch (e) {
        error = e instanceof Error ? e.message : String(e);
      } finally {
        stopping = false;
        resetTransient();
      }
    },
```

- [ ] **Step 4: テストが通ることを確認**

Run: `cd apps/web && npx vitest run tests/unit/stores/recording.test.ts`
Expected: PASS (既存テスト含む全件)

- [ ] **Step 5: 録音開始ボタン (SourcesPanel) の pending 表示**

`apps/web/src/lib/components/SourcesPanel.svelte` を修正。

import に `Spinner` を追加:

```typescript
  import Spinner from './Spinner.svelte';
```

rec-icon ボタン(現在の249-258行)を修正:

```svelte
    <button
      class="rec-icon"
      class:active={recordingStore.recording}
      title="録音"
      aria-label="録音"
      aria-busy={recordingStore.starting}
      onclick={startRecording}
      disabled={recordingStore.recording || recordingStore.starting}
    >
      {#if recordingStore.starting}
        <Spinner size={16} />
      {:else}
        <Mic size="16" />
      {/if}
    </button>
```

- [ ] **Step 6: 停止ボタン (RecordingControls) の pending 表示**

`apps/web/src/lib/components/RecordingControls.svelte` を修正。

import に `Spinner` を追加:

```typescript
  import Spinner from './Spinner.svelte';
```

stopbtn(現在の42-44行)を修正:

```svelte
      <button class="stopbtn" onclick={stop} disabled={recordingStore.stopping}>
        {#if recordingStore.stopping}
          <Spinner size={12} /> 停止中…
        {:else}
          <Square size="12" fill="currentColor" /> 停止
        {/if}
      </button>
```

style の `.stopbtn` の下に追加:

```css
  .stopbtn:disabled {
    opacity: 0.6;
    cursor: default;
  }
```

- [ ] **Step 7: 全テスト回帰**

Run: `cd apps/web && npx vitest run`
Expected: 全テスト PASS

- [ ] **Step 8: コミット**

```bash
git add apps/web/src/lib/stores/recording.svelte.ts apps/web/src/lib/components/SourcesPanel.svelte apps/web/src/lib/components/RecordingControls.svelte apps/web/tests/unit/stores/recording.test.ts
git commit -m "feat(web): 録音開始/停止ボタンを optimistic UI 化

クリック直後(バックエンド応答前)に starting/stopping の pending 状態を
同期的に立て、スピナー+disabled で「受理された」ことを即座に示す。
失敗時は finally で確実に解除し、ボタンが固まらないことを保証する。"
```

---

### Task 5: Playwright 実機検証 (必須ゲート)

**Files:**
- Create: `docs/eval/2026-07-02-job-status-bar/report.md` (evaluator が生成)
- Create: `docs/eval/2026-07-02-job-status-bar/*.png` (スクリーンショット)

**Interfaces:**
- Consumes: Task 1-4 の全実装(ビルド済みフロントエンド + 起動済みサーバー)
- Produces: PASS/FAIL 判定付きレポート。**FAIL の場合は原因を修正して再検証するまで Task 5 は完了しない。**

- [ ] **Step 1: フロントエンドをビルドしサーバーを起動**

```bash
cd apps/web && npm run build
cd ../.. && (uv run --no-sync uvicorn apps.api.main:app --host 127.0.0.1 --port 8765 &)
sleep 4 && curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8765/api/notebooks
```

Expected: `200`
(注: 既に別プロセスがポート8765で動作中の場合は、そのプロセスがユーザーの録音処理中でないことを `~/.notebook-ollama/logs/` で確認してから停止すること)

- [ ] **Step 2: evaluator agent による実機検証**

evaluator agent (agentType: evaluator) に以下を依頼する:

> 対象: http://127.0.0.1:8765/ (NotebookOllama)
> 検証項目 (spec: docs/specs/2026-07-02-job-status-bar-optimistic-ui-design.md):
> 1. ノートを開き、任意のソースで要約生成(またはADR生成)を開始 → topbar 直下にステータスバーが表示され「<ソース名>: 要約生成中」が見えること(スクショ)
> 2. 生成完了後にバーが自動的に消えること(スクショ)。SourceCard 側の生成中スピナーも完了時に止まること
> 3. 録音開始ボタン(マイクアイコン)をクリックした瞬間にスピナー+disabled になること(スクショ。クリック直後 200ms 以内にキャプチャ)
> 4. 録音停止ボタンをクリックした瞬間に「停止中…」表示になること(スクショ)
> 5. route interception で POST /api/notebooks/*/recordings を 500 に固定 → 録音開始が失敗してもボタンが固まらず(disabled が解除され)、エラートーストが出ること(スクショ)
> レポート: docs/eval/2026-07-02-job-status-bar/report.md に証拠画像付きで保存

Expected: 全項目 PASS。FAIL があれば superpowers:systematic-debugging で原因を特定し、修正 → 再検証。

- [ ] **Step 3: 検証結果をコミット**

```bash
git add docs/eval/2026-07-02-job-status-bar/
git commit -m "test(eval): JobStatusBar + optimistic 録音ボタンの実機検証レポート"
```

---

## Self-Review (完了済み)

1. **Spec coverage**: SSEハンドラpatch→Task 1、activeJobs 判定条件(enum準拠)→Task 2、JobStatusBar(0件非表示/convStep併記/チャット除外)→Task 3、録音 start/stop optimistic+ロールバック→Task 4、Playwright 3項目+route interception→Task 5。スコープ外項目(症状②、キュー化)はどのタスクにも含めていない。
2. **Placeholder scan**: TBD/TODO/「適切に」なし。全ステップに実コードあり。
3. **Type consistency**: `ActiveJob` は Task 2 で定義し Task 3 が import。`ConvStep` は既存 export を参照。`starting`/`stopping` は Task 4 内で interface→実装→UI の順に一貫。

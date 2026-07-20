/**
 * RecordingControls — 発表モード中の「発表を終了」導線。
 * 仕様: docs/specs/2026-07-06-presentation-mode-design.md, Task 9 brief.
 *
 * presentationStore.active のときは停止ボタンのラベルが「発表を終了」に変わり、
 * クリックで即 stop せず確認 Modal を挟んでから presentationStore.end() を呼ぶ。
 * active=false のときは従来どおり即 stop() する(挙動不変)。
 *
 * モックパターンは tests/unit/layout-wiring.test.ts / AppHeader.test.ts の
 * vi.hoisted + vi.mock を踏襲。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';

const mockRec = vi.hoisted(() => ({
  recordingStore: {
    recording: true,
    starting: false,
    stopping: false,
    elapsedMs: 0,
    liveCaptionEnabled: true,
    liveCaptionActive: false,
    micLevel: 0,
    sysLevel: 0,
    micMuted: false,
    systemMuted: false,
    stop: vi.fn(async () => {}),
    toggleLiveCaption: vi.fn(),
    toggleMute: vi.fn(),
  },
}));
vi.mock('$lib/stores/recording.svelte', () => mockRec);

const mockPres = vi.hoisted(() => ({
  presentationStore: {
    active: false,
    end: vi.fn(async () => {}),
  },
}));
vi.mock('$lib/stores/presentation.svelte', () => mockPres);

import RecordingControls from '$lib/components/RecordingControls.svelte';

beforeEach(() => {
  mockRec.recordingStore.recording = true;
  mockRec.recordingStore.stopping = false;
  mockRec.recordingStore.stop.mockReset().mockResolvedValue(undefined);
  mockPres.presentationStore.active = false;
  mockPres.presentationStore.end.mockReset().mockResolvedValue(undefined);
});

afterEach(() => cleanup());

describe('RecordingControls — 発表を終了', () => {
  it('presentationStore.active=true: 「発表を終了」表示→クリックで確認Modal→「終了する」でend()を呼ぶ', async () => {
    mockPres.presentationStore.active = true;
    render(RecordingControls, { props: { notebookId: 'nb1' } });

    const stopBtn = screen.getByText('発表を終了');
    await fireEvent.click(stopBtn);

    // 確認前は end()/stop() どちらも呼ばれない(即stopしない)
    expect(mockPres.presentationStore.end).not.toHaveBeenCalled();
    expect(mockRec.recordingStore.stop).not.toHaveBeenCalled();

    const dialog = screen.getByRole('dialog');
    expect(dialog.textContent).toContain('発表を終了');
    expect(dialog.textContent).toContain('録音を停止してソース化します');

    const confirmBtn = screen.getByText('終了する');
    await fireEvent.click(confirmBtn);

    expect(mockPres.presentationStore.end).toHaveBeenCalledTimes(1);
    // end() は recordingStore.stop() を内包する契約(presentationStore側)なので
    // RecordingControls 自身が二重に stop() を呼んではいけない
    expect(mockRec.recordingStore.stop).not.toHaveBeenCalled();
  });

  it('presentationStore.active=false: 従来どおり「停止」のまま、クリックでModalなしに即stop()する', async () => {
    render(RecordingControls, { props: { notebookId: 'nb1' } });

    expect(screen.queryByText('発表を終了')).toBeNull();
    const stopBtn = screen.getByText('停止');
    await fireEvent.click(stopBtn);

    expect(screen.queryByRole('dialog')).toBeNull();
    expect(mockRec.recordingStore.stop).toHaveBeenCalledTimes(1);
    expect(mockPres.presentationStore.end).not.toHaveBeenCalled();
  });
});

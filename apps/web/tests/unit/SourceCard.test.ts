import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import SourceCard from '$lib/components/SourceCard.svelte';
import type { Source } from '$lib/api/types';

afterEach(() => cleanup());

function makeSource(overrides: Partial<Source> = {}): Source {
  return {
    id: 'src1',
    notebook_id: 'nb1',
    kind: 'recording',
    title: '会議メモ',
    origin: '録音',
    status: 'embedding',
    error_msg: null,
    bytes: null,
    page_count: null,
    chunk_count: 5,
    has_audio: true,
    embedded: 2,
    duration_ms: 60000,
    created_at: 't',
    updated_at: 't',
    ...overrides,
  };
}

function baseProps(source: Source, extra: Record<string, unknown> = {}) {
  return {
    source,
    selected: false,
    onToggle: vi.fn(),
    onSelect: vi.fn(),
    onRetry: vi.fn(),
    onReembed: vi.fn(),
    onDelete: vi.fn(),
    ...extra,
  };
}

describe('SourceCard recording stop/play', () => {
  it('shows the stop button while a recording is converting and calls onStopConversion', async () => {
    const onStopConversion = vi.fn();
    render(SourceCard, baseProps(makeSource({ status: 'embedding' }), { onStopConversion }));

    const stop = screen.getByLabelText('変換を停止');
    expect(stop.tagName).toBe('BUTTON');
    await fireEvent.click(stop);
    expect(onStopConversion).toHaveBeenCalledTimes(1);
  });

  it('does not show the stop button once the recording is ready', () => {
    render(SourceCard, baseProps(makeSource({ status: 'ready', chunk_count: 5 }), {
      onStopConversion: vi.fn(),
    }));
    expect(screen.queryByLabelText('変換を停止')).toBeNull();
  });

  it('shows the play button for a recording with audio and reveals an <audio> on click', async () => {
    const { container } = render(
      SourceCard,
      baseProps(makeSource({ status: 'ready', chunk_count: 5, has_audio: true })),
    );
    const play = screen.getByLabelText('録音を再生');
    expect(container.querySelector('audio')).toBeNull(); // collapsed initially
    await fireEvent.click(play);
    const audio = container.querySelector('audio');
    expect(audio).not.toBeNull();
    expect(audio?.getAttribute('src')).toBe(
      '/api/notebooks/nb1/sources/src1/audio?channel=mic',
    );
  });

  it('switches the audio channel to system (相手)', async () => {
    const { container } = render(
      SourceCard,
      baseProps(makeSource({ status: 'ready', chunk_count: 5, has_audio: true })),
    );
    await fireEvent.click(screen.getByLabelText('録音を再生'));
    await fireEvent.click(screen.getByText('相手'));
    expect(container.querySelector('audio')?.getAttribute('src')).toBe(
      '/api/notebooks/nb1/sources/src1/audio?channel=system',
    );
  });

  it('hides play when the recording has no audio', () => {
    render(SourceCard, baseProps(makeSource({ status: 'ready', has_audio: false })));
    expect(screen.queryByLabelText('録音を再生')).toBeNull();
  });

  it('shows neither stop nor play for a non-recording source', () => {
    render(
      SourceCard,
      baseProps(makeSource({ kind: 'pdf', status: 'ready', has_audio: false, chunk_count: 3 }), {
        onStopConversion: vi.fn(),
      }),
    );
    expect(screen.queryByLabelText('変換を停止')).toBeNull();
    expect(screen.queryByLabelText('録音を再生')).toBeNull();
  });
});

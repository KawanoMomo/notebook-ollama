import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import PromptToolbar from '$lib/components/PromptToolbar.svelte';
import type { PromptsOut } from '$lib/api/types';

afterEach(() => cleanup());

function makePrompts(over: Partial<PromptsOut> = {}): PromptsOut {
  return {
    fixed: [
      { title: '', body: '', icon_url: null },
      { title: '', body: '', icon_url: null },
      { title: '', body: '', icon_url: null },
    ],
    dropdown: [],
    ...over,
  };
}

function baseProps(prompts: PromptsOut | null, extra: Record<string, unknown> = {}) {
  return {
    prompts,
    streaming: false,
    sourcesSelected: 1,
    onSend: vi.fn(),
    ...extra,
  };
}

describe('PromptToolbar — degraded mode (renders nothing)', () => {
  it('renders nothing when prompts is null (load failed)', () => {
    const { container } = render(PromptToolbar, baseProps(null));
    expect(container.querySelector('.prompt-toolbar')).toBeNull();
  });

  it('renders nothing when all 3 slots are empty and dropdown is empty', () => {
    const { container } = render(PromptToolbar, baseProps(makePrompts()));
    expect(container.querySelector('.prompt-toolbar')).toBeNull();
  });

  it('renders nothing when a slot has only title but no body (incomplete)', () => {
    const incomplete = makePrompts({
      fixed: [
        { title: '要約', body: '', icon_url: null }, // body 空 = 未設定扱い
        { title: '', body: '', icon_url: null },
        { title: '', body: '', icon_url: null },
      ],
    });
    const { container } = render(PromptToolbar, baseProps(incomplete));
    expect(container.querySelector('.prompt-toolbar')).toBeNull();
  });
});

describe('PromptToolbar — fixed buttons', () => {
  it('renders only the configured fixed slots', () => {
    const p = makePrompts({
      fixed: [
        { title: '要約', body: '3行で要約', icon_url: null },
        { title: '', body: '', icon_url: null },
        { title: '翻訳', body: '英語に翻訳', icon_url: null },
      ],
    });
    render(PromptToolbar, baseProps(p));
    expect(screen.getByLabelText('要約')).toBeDefined();
    expect(screen.getByLabelText('翻訳')).toBeDefined();
    expect(screen.queryAllByRole('button').filter(
      (b) => (b as HTMLButtonElement).className.includes('fixed-slot'),
    )).toHaveLength(2);
  });

  it('renders the title head character when icon_url is null', () => {
    const p = makePrompts({
      fixed: [
        { title: '要約', body: '3行で要約', icon_url: null },
        { title: '', body: '', icon_url: null },
        { title: '', body: '', icon_url: null },
      ],
    });
    render(PromptToolbar, baseProps(p));
    const btn = screen.getByLabelText('要約');
    expect(btn.textContent).toContain('要');
  });

  it('renders an <img> when icon_url is provided', () => {
    const p = makePrompts({
      fixed: [
        { title: '要約', body: '3行で要約', icon_url: '/api/prompts/icons/x.png' },
        { title: '', body: '', icon_url: null },
        { title: '', body: '', icon_url: null },
      ],
    });
    const { container } = render(PromptToolbar, baseProps(p));
    const img = container.querySelector('img');
    expect(img).not.toBeNull();
    expect(img?.getAttribute('src')).toBe('/api/prompts/icons/x.png');
  });

  it('clicking a fixed button calls onSend with body', async () => {
    const onSend = vi.fn();
    const p = makePrompts({
      fixed: [
        { title: '要約', body: '3行で要約', icon_url: null },
        { title: '', body: '', icon_url: null },
        { title: '', body: '', icon_url: null },
      ],
    });
    render(PromptToolbar, baseProps(p, { onSend }));
    await fireEvent.click(screen.getByLabelText('要約'));
    expect(onSend).toHaveBeenCalledWith('3行で要約');
  });
});

describe('PromptToolbar — dropdown', () => {
  it('does not show the dropdown when empty (even with fixed buttons set)', () => {
    const p = makePrompts({
      fixed: [
        { title: '要約', body: '3行で要約', icon_url: null },
        { title: '', body: '', icon_url: null },
        { title: '', body: '', icon_url: null },
      ],
      dropdown: [],
    });
    const { container } = render(PromptToolbar, baseProps(p));
    expect(container.querySelector('select')).toBeNull();
  });

  it('renders a select with the dropdown items', () => {
    const p = makePrompts({
      dropdown: [
        { id: 'a', title: '翻訳', body: '英語に' },
        { id: 'b', title: '校正', body: '誤字脱字' },
      ],
    });
    const { container } = render(PromptToolbar, baseProps(p));
    const sel = container.querySelector('select') as HTMLSelectElement;
    expect(sel).not.toBeNull();
    const options = Array.from(sel.querySelectorAll('option')).map((o) => o.textContent);
    expect(options).toContain('翻訳');
    expect(options).toContain('校正');
  });

  it('the issue button is disabled when nothing is selected', () => {
    const p = makePrompts({
      dropdown: [{ id: 'a', title: '翻訳', body: '英語に' }],
    });
    render(PromptToolbar, baseProps(p));
    const issue = screen.getByRole('button', { name: /発行/ }) as HTMLButtonElement;
    expect(issue.disabled).toBe(true);
  });

  it('clicking 発行 with a selection sends the body and resets the select', async () => {
    const onSend = vi.fn();
    const p = makePrompts({
      dropdown: [
        { id: 'a', title: '翻訳', body: '英語に翻訳' },
        { id: 'b', title: '校正', body: '誤字脱字' },
      ],
    });
    const { container } = render(PromptToolbar, baseProps(p, { onSend }));
    const sel = container.querySelector('select') as HTMLSelectElement;
    await fireEvent.change(sel, { target: { value: 'a' } });
    const issue = screen.getByRole('button', { name: /発行/ }) as HTMLButtonElement;
    expect(issue.disabled).toBe(false);
    await fireEvent.click(issue);
    expect(onSend).toHaveBeenCalledWith('英語に翻訳');
    expect(sel.value).toBe('');
  });
});

describe('PromptToolbar — disabled propagation', () => {
  function withFixedButton(): PromptsOut {
    return makePrompts({
      fixed: [
        { title: '要約', body: '3行で要約', icon_url: null },
        { title: '', body: '', icon_url: null },
        { title: '', body: '', icon_url: null },
      ],
      dropdown: [{ id: 'a', title: '翻訳', body: '英語に' }],
    });
  }

  it('disables all interactive elements when streaming=true', () => {
    const onSend = vi.fn();
    render(
      PromptToolbar,
      baseProps(withFixedButton(), { streaming: true, onSend }),
    );
    const btn = screen.getByLabelText('要約') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('disables all interactive elements when sourcesSelected=0', () => {
    const onSend = vi.fn();
    render(
      PromptToolbar,
      baseProps(withFixedButton(), { sourcesSelected: 0, onSend }),
    );
    const btn = screen.getByLabelText('要約') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });
});

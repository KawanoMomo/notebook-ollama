import { describe, expect, it } from 'vitest';
import { renderMarkdown } from '$lib/utils/markdown';

describe('renderMarkdown', () => {
  it('renders headings', () => {
    expect(renderMarkdown('# Hello')).toContain('<h1>Hello</h1>');
  });

  it('escapes raw HTML', () => {
    expect(renderMarkdown('<script>x</script>')).not.toContain('<script>');
  });

  it('renders code blocks with highlighting', () => {
    const html = renderMarkdown('```python\nprint("hi")\n```');
    expect(html).toContain('<pre>');
    expect(html).toContain('code');
  });
});

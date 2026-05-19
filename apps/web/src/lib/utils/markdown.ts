import MarkdownIt from 'markdown-it';
import hljs from 'highlight.js';

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: false,
  highlight: (str, lang) => {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(str, { language: lang, ignoreIllegals: true }).value;
      } catch {
        // fall through
      }
    }
    return hljs.highlightAuto(str).value;
  },
});

export function renderMarkdown(src: string): string {
  return md.render(src);
}

export function renderInline(src: string): string {
  return md.renderInline(src);
}

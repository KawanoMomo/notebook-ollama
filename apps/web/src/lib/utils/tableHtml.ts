const ALLOWED = new Set(['TABLE', 'THEAD', 'TBODY', 'TR', 'TH', 'TD']);

export function sanitizeTableHtml(html: string): string {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const walk = (node: Element): void => {
    for (const child of Array.from(node.children)) {
      walk(child);
      if (!ALLOWED.has(child.tagName)) {
        child.replaceWith(...Array.from(child.childNodes));
      } else {
        for (const attr of Array.from(child.attributes)) {
          if (!['rowspan', 'colspan'].includes(attr.name)) child.removeAttribute(attr.name);
        }
      }
    }
  };
  walk(doc.body);
  return doc.body.innerHTML;
}

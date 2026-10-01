export interface TocItem { id: string; label: string; level: number }

export function markdownHeadings(markdown: string): TocItem[] {
  return markdown.split('\n').flatMap((line) => {
    const match = /^(#{2,3})\s+(.+)$/.exec(line.trim());
    if (!match) return [];
    const label = match[2]!.replace(/[*_`]/g, '').trim();
    return [{ id: slugify(label), label, level: match[1]!.length }];
  });
}

export function slugify(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'section';
}

export function HelpArticleToc({ items }: { items: TocItem[] }) {
  if (items.length < 2) return null;
  return <nav className="help-article__toc" aria-label="On this page"><strong>On this page</strong>{items.map((item) => <a key={item.id} className={item.level === 3 ? 'is-nested' : ''} href={`#${item.id}`}>{item.label}</a>)}</nav>;
}

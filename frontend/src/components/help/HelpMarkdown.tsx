import { Fragment, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { slugify } from '@/components/help/HelpArticleToc';

function inline(value: string): ReactNode[] {
  const parts = value.split(/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g).filter(Boolean);
  return parts.map((part, index) => {
    if (part.startsWith('`') && part.endsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>;
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>;
    const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part);
    if (link) {
      const label = link[1]!; const href = link[2]!;
      if (href.startsWith('/')) return <Link key={index} to={href}>{label}</Link>;
      if (/^https?:\/\//.test(href)) return <a key={index} href={href} target="_blank" rel="noreferrer">{label}</a>;
      return <Fragment key={index}>{label}</Fragment>;
    }
    return <Fragment key={index}>{part}</Fragment>;
  });
}

export function HelpMarkdown({ markdown }: { markdown: string }) {
  const lines = markdown.replace(/\r\n/g, '\n').split('\n');
  const nodes: ReactNode[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index]!.trimEnd();
    if (!line.trim()) { index += 1; continue; }
    const heading = /^(#{1,4})\s+(.+)$/.exec(line);
    if (heading) {
      const level = heading[1]!.length; const label = heading[2]!.replace(/[*_`]/g, '').trim(); const id = slugify(label);
      if (level === 1) nodes.push(<h2 className="help-article__body-title" key={index}>{inline(label)}</h2>);
      else if (level === 2) nodes.push(<h2 id={id} key={index}>{inline(label)}</h2>);
      else nodes.push(<h3 id={id} key={index}>{inline(label)}</h3>);
      index += 1; continue;
    }
    if (/^```/.test(line)) {
      const code: string[] = []; index += 1;
      while (index < lines.length && !/^```/.test(lines[index]!.trim())) { code.push(lines[index]!); index += 1; }
      index += 1; nodes.push(<pre key={`code-${index}`}><code>{code.join('\n')}</code></pre>); continue;
    }
    if (/^[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^[-*]\s+/.test(lines[index]!.trim())) { items.push(lines[index]!.trim().replace(/^[-*]\s+/, '')); index += 1; }
      nodes.push(<ul key={`ul-${index}`}>{items.map((item, itemIndex) => <li key={itemIndex}>{inline(item)}</li>)}</ul>); continue;
    }
    if (/^\d+\.\s+/.test(line.trim())) {
      const items: string[] = [];
      while (index < lines.length && /^\d+\.\s+/.test(lines[index]!.trim())) { items.push(lines[index]!.trim().replace(/^\d+\.\s+/, '')); index += 1; }
      nodes.push(<ol key={`ol-${index}`}>{items.map((item, itemIndex) => <li key={itemIndex}>{inline(item)}</li>)}</ol>); continue;
    }
    const paragraph: string[] = [line.trim()]; index += 1;
    while (index < lines.length && lines[index]!.trim() && !/^(#{1,4})\s+|^[-*]\s+|^\d+\.\s+|^```/.test(lines[index]!.trim())) { paragraph.push(lines[index]!.trim()); index += 1; }
    nodes.push(<p key={`p-${index}`}>{inline(paragraph.join(' '))}</p>);
  }
  return <div className="help-article__body">{nodes}</div>;
}

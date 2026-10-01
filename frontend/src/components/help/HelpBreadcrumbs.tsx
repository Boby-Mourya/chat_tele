import { ChevronRight } from 'lucide-react';
import { Link } from 'react-router-dom';

export function HelpBreadcrumbs({ items }: { items: Array<{ label: string; to?: string }> }) {
  return <nav className="help-breadcrumbs" aria-label="Breadcrumb">
    {items.map((item, index) => <span key={`${item.label}-${index}`}>{index ? <ChevronRight aria-hidden="true" /> : null}{item.to ? <Link to={item.to}>{item.label}</Link> : <strong aria-current="page">{item.label}</strong>}</span>)}
  </nav>;
}

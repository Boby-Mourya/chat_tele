import { SearchX } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import { EmptyState } from '@/components/ui';

export function HelpEmptyState({ query }: { query?: string }) {
  const location = useLocation();
  const from = encodeURIComponent(location.pathname + location.search);
  return <div className="help-empty"><EmptyState icon={SearchX} title="No matching Help articles" description={query ? `We couldn't find an official guide for “${query}”. Try fewer words, ask Help AI, or contact support.` : 'There are no guides available here for your current role.'} action={<div className="help-empty__actions"><Link className="button button--secondary button--md" to="/help/ask">Ask Help AI</Link><Link className="button button--primary button--md" to={`/help/support?from=${from}`}>Contact support</Link></div>} /></div>;
}

import { ExternalLink, LifeBuoy, Mail } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';
import { Card } from '@/components/ui';
import type { HelpSupportDestination } from '@/lib/help-types';

export function HelpSupportCard({ support }: { support: HelpSupportDestination }) {
  const location = useLocation();
  const supportRoute = `/help/support?from=${encodeURIComponent(location.pathname + location.search)}`;
  return <Card className="help-support-card">
    <span className="help-support-card__icon"><LifeBuoy /></span>
    <div><h3>Still need help?</h3><p>Send a support request with safe diagnostic context, or use your configured support contact.</p><span className="help-support-card__email"><Mail />{support.email}</span></div>
    <div className="help-support-card__actions"><Link className="button button--primary button--md" to={supportRoute}>Contact support</Link>{support.externalUrl ? <a className="button button--secondary button--md" href={support.externalUrl} target="_blank" rel="noreferrer">Support site <ExternalLink /></a> : null}</div>
  </Card>;
}

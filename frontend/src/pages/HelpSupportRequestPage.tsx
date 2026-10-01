import { Calendar, Mail, ShieldCheck } from 'lucide-react';
import { useParams } from 'react-router-dom';
import { HelpBreadcrumbs } from '@/components/help/HelpBreadcrumbs';
import { Badge, Card } from '@/components/ui';
import { helpApi } from '@/lib/help-api';
import { useApi } from '@/lib/use-api';

export function HelpSupportRequestPage() {
  const { requestId = '' } = useParams(); const result = useApi(() => helpApi.supportRequest(requestId), [requestId]);
  if (result.loading) return <div className="page help-page"><p>Loading support request…</p></div>;
  if (!result.data) return <div className="page help-page"><Card className="help-error"><h2>Support request not found</h2><p>{result.error ?? 'This request is not available to your workspace role.'}</p></Card></div>;
  const item = result.data;
  return <div className="page help-page"><HelpBreadcrumbs items={[{ label: 'Help', to: '/help' }, { label: 'Support', to: '/help/support' }, { label: item.subject }]} /><Card className="help-request-detail"><div className="help-request-detail__header"><div><span className="page-kicker">Request {item.id}</span><h2>{item.subject}</h2></div><Badge tone={item.status === 'closed' ? 'success' : 'brand'}>{item.status}</Badge></div><div className="help-request-detail__meta"><span><Calendar />Submitted {new Date(item.createdAt).toLocaleString()}</span><span><Mail />{item.supportDestination}</span><span><ShieldCheck />{Object.keys(item.diagnostics).length ? 'Safe diagnostics included' : 'No diagnostics included'}</span></div><div className="help-request-detail__message"><strong>Category: {item.category}</strong><p>{item.message}</p></div></Card></div>;
}

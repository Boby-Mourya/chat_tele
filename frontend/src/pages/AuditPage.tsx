import { AlertTriangle, Download, RefreshCw, Search, ShieldCheck } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useToast } from '@/components/providers';
import { Badge, Button, Card, EmptyState, PageLoader } from '@/components/ui';
import {
  auditApi,
  type AuditCategory,
  type AuditEvent,
  type AuditOutcome,
  type AuditSeverity,
} from '@/lib/audit-api';
import { relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';
import '@/pages/AuditPage.css';

const categories: Array<AuditCategory | ''> = [
  '', 'security', 'workspace', 'access', 'agent', 'conversation', 'education', 'lead', 'crm',
  'channel', 'billing', 'api', 'integration', 'system',
];

function tone(value: string): 'brand' | 'warning' | 'success' | 'purple' | 'neutral' {
  if (value === 'critical' || value === 'failure' || value === 'denied') return 'warning';
  if (value === 'success') return 'success';
  if (value === 'security' || value === 'access') return 'purple';
  if (value === 'info') return 'brand';
  return 'neutral';
}

function label(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function hasPayload(event: AuditEvent): boolean {
  return Object.keys(event.before).length > 0
    || Object.keys(event.after).length > 0
    || Object.keys(event.metadata).length > 0;
}

function downloadBlob(blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `northstar-audit-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function AuditPage() {
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState<AuditCategory | ''>('');
  const [severity, setSeverity] = useState<AuditSeverity | ''>('');
  const [outcome, setOutcome] = useState<AuditOutcome | ''>('');
  const [exporting, setExporting] = useState(false);
  const { pushToast } = useToast();
  const filters = useMemo(() => ({ search, category, severity, outcome, limit: 200 }), [search, category, severity, outcome]);
  const result = useApi(() => auditApi.list(filters), [search, category, severity, outcome]);
  const events = result.data;

  if (result.loading && !events) return <PageLoader />;
  if (!events) {
    return <div className="page audit-page"><Card><h3>Audit trail could not be loaded</h3><p>{result.error ?? 'Try again.'}</p><Button variant="secondary" icon={RefreshCw} onClick={result.reload}>Retry</Button></Card></div>;
  }

  const warningCount = events.filter((event) => event.severity === 'warning' || event.severity === 'critical').length;
  const deniedCount = events.filter((event) => event.outcome === 'denied' || event.outcome === 'failure').length;
  const latest = events[0];

  const exportCsv = async () => {
    setExporting(true);
    try {
      downloadBlob(await auditApi.exportCsv(filters));
      pushToast('Audit CSV exported');
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Audit export failed', 'error');
    } finally {
      setExporting(false);
    }
  };

  return <div className="page audit-page">
    <div className="page-heading page-heading--split">
      <div><h2>Audit</h2><p>Review security-sensitive and operational changes for the active workspace without exposing request secrets.</p></div>
      <div className="heading-actions">
        <Button variant="secondary" icon={RefreshCw} onClick={result.reload}>Refresh</Button>
        <Button variant="secondary" icon={Download} disabled={exporting} onClick={() => void exportCsv()}>{exporting ? 'Exporting…' : 'Export CSV'}</Button>
      </div>
    </div>

    <div className="stat-grid audit-stats">
      <Card className="stat-card analytics-stat"><div className="stat-card__icon stat-card__icon--blue"><ShieldCheck /></div><span>Visible events</span><strong>{events.length}</strong><small><em>Current workspace + tenant-wide</em></small></Card>
      <Card className="stat-card analytics-stat"><div className="stat-card__icon stat-card__icon--orange"><AlertTriangle /></div><span>Warnings / critical</span><strong>{warningCount}</strong><small><em>Needs closer review</em></small></Card>
      <Card className="stat-card analytics-stat"><div className="stat-card__icon stat-card__icon--purple"><ShieldCheck /></div><span>Denied / failed</span><strong>{deniedCount}</strong><small><em>Authorization or mutation failures</em></small></Card>
      <Card className="stat-card analytics-stat"><div className="stat-card__icon stat-card__icon--green"><RefreshCw /></div><span>Latest event</span><strong>{latest ? relativeTime(latest.createdAt) : 'None'}</strong><small><em>{latest ? label(latest.category) : 'No durable events yet'}</em></small></Card>
    </div>

    <Card className="audit-filter-card">
      <div className="audit-filters">
        <label className="audit-search"><Search /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search action, entity, request ID…" aria-label="Search audit events" /></label>
        <select value={category} onChange={(event) => setCategory(event.target.value as AuditCategory | '')} aria-label="Audit category">
          {categories.map((value) => <option key={value || 'all'} value={value}>{value ? label(value) : 'All categories'}</option>)}
        </select>
        <select value={severity} onChange={(event) => setSeverity(event.target.value as AuditSeverity | '')} aria-label="Audit severity">
          <option value="">All severities</option><option value="info">Info</option><option value="warning">Warning</option><option value="critical">Critical</option>
        </select>
        <select value={outcome} onChange={(event) => setOutcome(event.target.value as AuditOutcome | '')} aria-label="Audit outcome">
          <option value="">All outcomes</option><option value="success">Success</option><option value="denied">Denied</option><option value="failure">Failure</option>
        </select>
      </div>
    </Card>

    {events.length === 0 ? <EmptyState icon={ShieldCheck} title="No audit events match these filters" description="Authenticated mutations will appear here after they are recorded by the durable audit trail." /> : <div className="audit-list">
      {events.map((event) => <Card className="audit-event" key={event.id}>
        <div className="audit-event__header">
          <div><span className="audit-event__icon"><ShieldCheck /></span><span><strong>{event.action}</strong><small>{event.entityType} · {event.entityId}</small></span></div>
          <div><Badge tone={tone(event.category)}>{label(event.category)}</Badge><Badge tone={tone(event.severity)}>{label(event.severity)}</Badge><Badge tone={tone(event.outcome)}>{label(event.outcome)}</Badge></div>
        </div>
        <div className="audit-event__meta">
          <span><strong>When</strong>{new Date(event.createdAt).toLocaleString()} ({relativeTime(event.createdAt)})</span>
          <span><strong>Actor</strong>{event.actorUserId ?? 'System'}</span>
          <span><strong>Workspace</strong>{event.workspaceId ?? 'Tenant-wide'}</span>
          <span><strong>Request</strong>{event.requestId ?? '—'}</span>
          <span><strong>IP</strong>{event.ipAddress ?? '—'}</span>
        </div>
        {hasPayload(event) ? <details className="audit-event__details"><summary>Safe event details</summary><pre>{JSON.stringify({ before: event.before, after: event.after, metadata: event.metadata }, null, 2)}</pre></details> : null}
      </Card>)}
    </div>}
  </div>;
}

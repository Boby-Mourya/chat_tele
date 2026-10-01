import { LeadLayoutEditor } from '@/components/lead-layout-editor';
import { LeadDetailsEditor } from '@/components/lead-details-editor';
import { defaultLayout, leadColumnValue, leadLayoutApi, type LeadLayout } from '@/lib/lead-layout-api';
import './LeadsPage.css';
import { ChevronDown, Download, Filter, RefreshCw, Search, ShieldCheck, UserRound, UsersRound } from 'lucide-react';
import { useMemo, useState } from 'react';
import { CRMDeliveryAttempts } from '@/components/crm-delivery-attempts';
import { useToast } from '@/components/providers';
import { Badge, Button, Card, EmptyState, PageLoader } from '@/components/ui';
import { api } from '@/lib/api';
import { getVerificationView } from '@/lib/crm-delivery-status';
import { leadCrmApi } from '@/lib/lead-crm-api';
import { relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';
import type { Lead, PageResult } from '@/types';

import { leadStatuses as commonStatuses } from '@/lib/lead-status';

interface LeadFilters {
  page: number;
  pageSize: number;
  search: string;
  status: string;
}

async function loadLeads(filters: LeadFilters): Promise<PageResult<Lead>> {
  try {
    return await leadCrmApi.leads(filters);
  } catch {
    // Keep the richer CRM query when the API is running, while preserving the
    // application's configured demo fallback during standalone Vite previews.
    const fallback = await api.leads.list();
    const search = filters.search.trim().toLowerCase();
    const filtered = fallback.items.filter((lead) => {
      const matchesSearch = !search || `${lead.name ?? ''} ${lead.email ?? ''} ${lead.phone ?? ''}`.toLowerCase().includes(search);
      const matchesStatus = filters.status === 'all' || lead.status === filters.status;
      return matchesSearch && matchesStatus;
    });
    const start = (filters.page - 1) * filters.pageSize;
    return {
      items: filtered.slice(start, start + filters.pageSize),
      total: filtered.length,
      page: filters.page,
      pageSize: filters.pageSize,
    };
  }
}

function statusTone(status: string): 'brand' | 'warning' | 'success' | 'purple' | 'neutral' {
  if (status === 'new' || status === 'identified') return 'brand';
  if (status === 'contacted' || status === 'engaged') return 'warning';
  if (status === 'qualified') return 'purple';
  if (status === 'converted') return 'success';
  return 'neutral';
}

function deliveryTone(status: string): 'brand' | 'warning' | 'success' | 'purple' | 'neutral' {
  if (status === 'verified') return 'success';
  if (['failed', 'dead_letter', 'mapping_error', 'auth_required'].includes(status)) return 'warning';
  if (['queued', 'processing', 'retrying', 'rate_limited'].includes(status)) return 'brand';
  return 'neutral';
}

export function LeadsPage() {
  const layoutResult = useApi(() => leadLayoutApi.get());
  const [savedLayout, setSavedLayout] = useState<LeadLayout | null>(null);
  const layout = savedLayout ?? layoutResult.data ?? defaultLayout;
  const [customizing, setCustomizing] = useState(false);
  const [editing, setEditing] = useState<Lead | null>(null);
  const [exporting, setExporting] = useState(false);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('all');
  const [page, setPage] = useState(1);
  const leads = useApi(() => loadLeads({ page, pageSize: 50, search, status }), [page, search, status]);
  const agents = useApi(() => api.agents.list());
  const [selected, setSelected] = useState<Lead | null>(null);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [updating, setUpdating] = useState<string>();
  const [retrying, setRetrying] = useState<string>();
  const { pushToast } = useToast();

  const deliveries = useApi(
    () => selected ? leadCrmApi.deliveriesForLead(selected.id) : Promise.resolve([]),
    [selected?.id],
  );
  const activity = useApi(
    () => selected ? leadCrmApi.activityForLead(selected.id) : Promise.resolve([]),
    [selected?.id],
  );

  const records = useMemo(
    () => (leads.data?.items ?? []).map((lead) => ({ ...lead, status: overrides[lead.id] ?? lead.status })),
    [leads.data, overrides],
  );
  const agentNames = useMemo(() => new Map((agents.data ?? []).map((agent) => [agent.id, agent.name])), [agents.data]);

  const updateStatus = async (lead: Lead, nextStatus: string) => {
    const previous = overrides[lead.id] ?? lead.status;
    setOverrides((current) => ({ ...current, [lead.id]: nextStatus }));
    setUpdating(lead.id);
    try {
      const saved = await api.leads.updateStatus(lead.id, nextStatus);
      setOverrides((current) => ({ ...current, [lead.id]: saved.status }));
      pushToast(saved.status === 'qualified'
        ? `${lead.name || 'Lead'} marked Qualified. Resolved leads sync automatically using your CRM settings.`
        : `${lead.name || 'Lead'} marked ${saved.status}`);
      if (selected?.id === lead.id) { deliveries.reload(); activity.reload(); }
    } catch (error) {
      setOverrides((current) => ({ ...current, [lead.id]: previous }));
      pushToast(error instanceof Error ? error.message : 'Could not update this lead', 'error');
    } finally {
      setUpdating(undefined);
    }
  };

  const syncLead = async () => {
    if (!selected) return;
    try {
      await leadCrmApi.syncLead(selected.id, 'manual-ui');
      pushToast('CRM synchronization queued');
      deliveries.reload();
      activity.reload();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Could not queue CRM synchronization', 'error');
    }
  };

  const retryDelivery = async (deliveryId: string) => {
    setRetrying(deliveryId);
    try {
      const result = await leadCrmApi.retryDelivery(deliveryId);
      pushToast(result?.acknowledged_at ? 'CRM verification queued; the acknowledged write will not be resent' : 'CRM delivery queued for retry');
      deliveries.reload();
      activity.reload();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Could not retry delivery', 'error');
    } finally {
      setRetrying(undefined);
    }
  };

  if ((leads.loading && !leads.data) || agents.loading) return <PageLoader />;
  if (leads.error) return <div className="page leads-page"><Card><EmptyState icon={UsersRound} title="Leads are unavailable" description={leads.error} action={<Button onClick={leads.reload}>Try again</Button>} /></Card></div>;

  const qualified = records.filter((lead) => lead.status === 'qualified').length;
  const converted = records.filter((lead) => lead.status === 'converted').length;
  const consented = records.filter((lead) => lead.consent).length;
  const totalPages = Math.max(1, Math.ceil((leads.data?.total ?? 0) / (leads.data?.pageSize ?? 50)));

  return <div className="page leads-page">
    <div className="page-heading page-heading--split">
      <div><h2>Leads</h2><p>Resolve the conversation and mark its lead Qualified to sync it automatically to your connected CRM.</p></div>
      <div className="lead-export-actions"><Button variant="secondary" disabled={layoutResult.loading || Boolean(layoutResult.error)} onClick={() => setCustomizing(true)}>Customize columns</Button>{(['csv', 'xlsx'] as const).map((format) => <Button key={format} variant="secondary" icon={Download} disabled={exporting || !records.length || Boolean(layoutResult.error)} onClick={async () => { setExporting(true); try { await leadLayoutApi.export(format, search, status); pushToast('All matching leads exported'); } catch (e) { pushToast(e instanceof Error ? e.message : 'Export failed', 'error'); } finally { setExporting(false); } }}>Export {format === 'csv' ? 'CSV' : 'Excel'}</Button>)}</div>
    </div>

    {layoutResult.error && <p role="alert">Could not load your saved layout. <Button variant="secondary" onClick={layoutResult.reload}>Retry layout</Button></p>}
    <div className="leads-stats">
      <Card><span><UsersRound /></span><div><strong>{leads.data?.total ?? 0}</strong><small>Total leads</small></div></Card>
      <Card><span><UserRound /></span><div><strong>{qualified}</strong><small>Qualified on page</small></div></Card>
      <Card><span><ShieldCheck /></span><div><strong>{consented}</strong><small>Consented on page</small></div></Card>
      <Card><span><Checkmark /></span><div><strong>{converted}</strong><small>Converted on page</small></div></Card>
    </div>

    <Card className="leads-card">
      <div className="leads-toolbar">
        <div><h3>Captured contacts</h3><p>{records.length} shown · {leads.data?.total ?? 0} total</p></div>
        <div className="leads-toolbar__filters">
          <div className="search-box"><Search /><input value={search} onChange={(event) => { setPage(1); setSearch(event.target.value); }} placeholder="Search name, email, or phone" aria-label="Search leads" /></div>
          <div className="filter-select leads-status-filter"><Filter /><select value={status} onChange={(event) => { setPage(1); setStatus(event.target.value); }} aria-label="Filter leads by status"><option value="all">All statuses</option>{commonStatuses.map((item) => <option key={item} value={item}>{item}</option>)}</select><ChevronDown /></div>
        </div>
      </div>

      {records.length ? <div className="leads-table-wrap"><table className="leads-table">
        <thead><tr>{layout.columns.filter((c) => c.visible).map((c) => <th key={c.id}>{c.label}</th>)}<th>Actions</th></tr></thead>
        <tbody>{records.map((lead) => {
          const statuses = commonStatuses.includes(lead.status) ? commonStatuses : [lead.status, ...commonStatuses];
          return <tr key={lead.id}>{layout.columns.filter((c) => c.visible).map((column) => <td key={column.id}>{column.source === 'status' ? <label className={`lead-status lead-status--${statusTone(lead.status)}`}><span className="sr-only">Status for {lead.name || 'lead'}</span><select value={lead.status} disabled={updating === lead.id} onChange={(event) => void updateStatus(lead, event.target.value)}>{statuses.map((item) => <option key={item} value={item}>{item}</option>)}</select><ChevronDown /></label> : column.source === 'name' ? <strong>{leadColumnValue(lead, column) || 'Anonymous visitor'}</strong> : leadColumnValue(lead, column, agentNames.get(lead.agentId)) || 'Not provided'}</td>)}
          <td><div className="lead-export-actions"><Button variant="secondary" disabled={Boolean(layoutResult.error)} onClick={() => setEditing(lead)}>Edit details</Button><Button variant="secondary" onClick={() => setSelected(lead)}>View sync</Button></div></td></tr>;
        })}</tbody>
      </table></div> : <EmptyState icon={UsersRound} title="No leads found" description={search || status !== 'all' ? 'Try another search or status filter.' : 'New contacts captured by your channels will appear here.'} />}
      <div className="page-heading page-heading--split"><small>Page {page} of {totalPages}</small><div><Button variant="secondary" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>Previous</Button> <Button variant="secondary" disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)}>Next</Button></div></div>
    </Card>

    {customizing && <LeadLayoutEditor initial={layout} records={records} agentNames={agentNames} onClose={() => setCustomizing(false)} onSaved={setSavedLayout} />}
    {editing && <LeadDetailsEditor lead={editing} layout={layout} onClose={() => setEditing(null)} onSaved={() => { leads.reload(); pushToast("Lead details saved"); }} />}
    {selected ? <Card>
      <div className="page-heading page-heading--split">
        <div><h3>{selected.name || selected.email || 'Lead'} · CRM delivery</h3><p>Provider ACK and read-back proof are separate. Identity verification proves the record ID; mapped-field verification additionally compares the configured fields. Verification retries never resend an acknowledged write.</p></div>
        <div><Button icon={RefreshCw} onClick={() => void syncLead()}>Sync now</Button> <Button variant="secondary" onClick={() => { deliveries.reload(); activity.reload(); }}>Refresh status</Button> <Button variant="secondary" onClick={() => setSelected(null)}>Close</Button></div>
      </div>
      {deliveries.loading ? <p>Loading CRM deliveries…</p> : deliveries.error ? <p role="alert">Could not load CRM deliveries: {deliveries.error}</p> : deliveries.data?.length ? <div className="leads-table-wrap"><table className="leads-table">
        <thead><tr><th>Provider</th><th>Status</th><th>External ID</th><th>Write attempts</th><th>Provider ACK</th><th>Read-back verification</th><th>Action</th></tr></thead>
        <tbody>{deliveries.data.map((delivery) => {
          const verification = getVerificationView(delivery);
          return <tr key={delivery.id}>
            <td>{delivery.provider}</td>
            <td><Badge tone={deliveryTone(delivery.status)}>{delivery.status}</Badge>{delivery.last_error_message ? <small>{delivery.last_error_message}</small> : null}</td>
            <td>{delivery.external_record_id ?? '—'}</td>
            <td>{delivery.attempt_count}</td>
            <td>{delivery.acknowledged_at ? relativeTime(delivery.acknowledged_at) : '—'}</td>
            <td><Badge tone={verification.proved ? 'success' : verification.error ? 'warning' : 'neutral'}>{verification.label}</Badge><small>Read-back attempts: {verification.attempts}</small>{verification.proved && delivery.verified_at ? <small>{relativeTime(delivery.verified_at)}</small> : null}{verification.nextAttempt ? <small>Next check: {new Date(verification.nextAttempt).toLocaleString()}</small> : null}{verification.error ? <small>{verification.error}</small> : null}</td>
            <td><div>{verification.retryable ? <Button variant="secondary" disabled={Boolean(retrying)} onClick={() => void retryDelivery(delivery.id)}>{verification.retryLabel}</Button> : null}<CRMDeliveryAttempts deliveryId={delivery.id} attemptCount={delivery.attempt_count} /></div></td>
          </tr>;
        })}</tbody>
      </table></div> : <EmptyState icon={RefreshCw} title="No CRM deliveries yet" description="Use Sync now or qualify the lead to evaluate CRM routing rules." />}
      <h3>Activity</h3>
      {activity.loading ? <p>Loading activity…</p> : activity.error ? <p role="alert">Could not load activity: {activity.error}</p> : activity.data?.length ? <div>{activity.data.slice().reverse().map((item) => <p key={item.id}><strong>{item.event_type}</strong> · <time dateTime={item.occurred_at}>{relativeTime(item.occurred_at)}</time></p>)}</div> : <p>No activity recorded yet.</p>}
    </Card> : null}
  </div>;
}

function Checkmark() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

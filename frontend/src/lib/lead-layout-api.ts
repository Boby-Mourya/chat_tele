import type { Lead, Session } from '@/types';
import { readStorage } from '@/lib/storage';
import { activeWorkspaceId } from '@/lib/workspace-api';

export interface LeadColumn {
  id: string; label: string; source: string; type: 'text' | 'number' | 'date' | 'boolean';
  format: 'plain' | 'upper' | 'lower' | 'yyyy-mm-dd' | 'dd/mm/yyyy' | 'mm/dd/yyyy';
  visible: boolean; required: boolean; crmTargets: Record<string, string>;
}
export interface LeadLayout { name: string; version: number; columns: LeadColumn[] }
export const standardSources: Record<string, string> = { name: 'Name', email: 'Email', phone: 'Phone / WhatsApp', status: 'Status', consent: 'Consent', agentName: 'Agent', createdAt: 'Captured date', updatedAt: 'Updated date' };
export const defaultLayout: LeadLayout = { name: 'My lead layout', version: 0, columns: Object.entries(standardSources).map(([source, label]) => ({ id: source, label, source, type: source === 'consent' ? 'boolean' : source.endsWith('At') ? 'date' : 'text', format: 'plain', visible: source !== 'updatedAt', required: false, crmTargets: {} })) };
const base = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
function headers(json = true) {
  const session = readStorage<Session | null>('northstar.session', null);
  const workspace = activeWorkspaceId();
  return { ...(json ? { 'Content-Type': 'application/json' } : {}), ...(session ? { Authorization: `Bearer ${session.accessToken}` } : {}), ...(workspace ? { 'X-Workspace-ID': workspace } : {}) };
}
async function checked(response: Response) {
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: unknown; error?: { message?: string } };
    throw new Error(body.error?.message ?? (typeof body.detail === 'string' ? body.detail : `Request failed (${response.status}). Check the field values.`));
  }
  return response;
}
export const leadLayoutApi = {
  get: async (): Promise<LeadLayout> => (await checked(await fetch(`${base}/leads/layout`, { headers: headers(), credentials: 'include' }))).json(),
  save: async (layout: LeadLayout): Promise<LeadLayout> => (await checked(await fetch(`${base}/leads/layout`, { method: 'PUT', headers: headers(), credentials: 'include', body: JSON.stringify(layout) }))).json(),
  importTemplate: async (file: File): Promise<LeadLayout> => {
    const body = new FormData(); body.append('file', file);
    return (await checked(await fetch(`${base}/leads/layout/template`, { method: 'POST', headers: headers(false), credentials: 'include', body }))).json();
  },
  edit: async (id: string, value: { name: string | null; email: string | null; phone: string | null; consent: boolean; fields: Record<string, unknown> }): Promise<Lead> => (await checked(await fetch(`${base}/leads/${id}/details`, { method: 'PATCH', headers: headers(), credentials: 'include', body: JSON.stringify(value) }))).json(),
  export: async (format: 'csv' | 'xlsx', search: string, status: string) => {
    const params = new URLSearchParams({ format, search, status });
    const response = await checked(await fetch(`${base}/leads/layout/export?${params}`, { headers: headers(false), credentials: 'include' }));
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `northstar-leads.${format}`; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
};
export function leadColumnValue(lead: Lead, column: LeadColumn, agentName = ''): string {
  const raw = column.source.startsWith('fields.') ? lead.fields[column.source.slice(7)] : column.source === 'agentName' ? agentName : lead[column.source as keyof Lead];
  if (raw == null || raw === '') return '';
  let value = typeof raw === 'boolean' ? ['upper', 'lower'].includes(column.format) ? String(raw) : raw ? 'Yes' : 'No' : String(raw);
  if (column.format === 'upper') value = value.toUpperCase();
  if (column.format === 'lower') value = value.toLowerCase();
  if (['yyyy-mm-dd', 'dd/mm/yyyy', 'mm/dd/yyyy'].includes(column.format)) {
    const parts = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
    if (parts) value = column.format === 'yyyy-mm-dd' ? `${parts[1]}-${parts[2]}-${parts[3]}` : column.format === 'dd/mm/yyyy' ? `${parts[3]}/${parts[2]}/${parts[1]}` : `${parts[2]}/${parts[3]}/${parts[1]}`;
  }
  return value;
}
export function crmSource(source: string) { return source.startsWith('fields.') ? `customFields.${source.slice(7)}` : source; }

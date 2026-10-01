import { useEffect, useState } from 'react';
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react';
import { Button, Modal } from '@/components/ui';
import { crmSource, leadColumnValue, leadLayoutApi, standardSources, type LeadColumn, type LeadLayout } from '@/lib/lead-layout-api';
import { leadCrmApi, type CRMConnectionView, type CRMFieldSchemaView } from '@/lib/lead-crm-api';
import type { Lead } from '@/types';

export function LeadLayoutEditor({ initial, records, agentNames, onClose, onSaved }: { initial: LeadLayout; records: Lead[]; agentNames?: Map<string, string>; onClose: () => void; onSaved: (layout: LeadLayout) => void }) {
  const [draft, setDraft] = useState<LeadLayout>(structuredClone(initial));
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [connections, setConnections] = useState<CRMConnectionView[]>([]); const [connectionId, setConnectionId] = useState('');
  const [schema, setSchema] = useState<CRMFieldSchemaView | null>(null); const [schemaError, setSchemaError] = useState('');
  const [mappingLoaded, setMappingLoaded] = useState(false);
  const [existingMapping, setExistingMapping] = useState<Record<string, unknown>>({});
  useEffect(() => { let active = true; void (async () => { try { const rows = await leadCrmApi.connections(); if (active) setConnections(rows.filter((c) => c.status !== 'disabled')); } catch { /* Layout editing remains available without CRM access. */ } })(); return () => { active = false; }; }, []);
  useEffect(() => {
    let active = true; setSchema(null); setSchemaError(''); setMappingLoaded(false); setExistingMapping({});
    if (connectionId) void (async () => {
      try {
        const [fields, mappings] = await Promise.all([leadCrmApi.schema(connectionId), leadCrmApi.mappings(connectionId)]);
        if (active) {
          setSchema(fields); const existing = mappings.find((m) => m.object_name === 'Leads')?.mapping ?? {};
          setExistingMapping(existing); setMappingLoaded(true);
          const rules = Array.isArray(existing.fields) ? existing.fields as Array<{ source?: string; target?: string }> : Object.entries((existing.fields ?? {}) as Record<string, string>).map(([source, target]) => ({ source, target }));
          setDraft((current) => ({ ...current, columns: current.columns.map((column) => {
            const target = rules.find((r) => r.source === crmSource(column.source))?.target;
            return target && !(connectionId in column.crmTargets) ? { ...column, crmTargets: { ...column.crmTargets, [connectionId]: target } } : column;
          }) }));
        }
      } catch (e) { if (active) setSchemaError(e instanceof Error ? e.message : 'CRM schema is unavailable.'); }
    })();
    return () => { active = false; };
  }, [connectionId]);
  function patch(id: string, value: Partial<LeadColumn>) { setDraft((current) => ({ ...current, columns: current.columns.map((c) => c.id === id ? { ...c, ...value } : c) })); }
  function move(index: number, direction: number) { setDraft((current) => { const columns = [...current.columns]; [columns[index], columns[index + direction]] = [columns[index + direction]!, columns[index]!]; return { ...current, columns }; }); }
  async function importFile(file?: File) {
    if (!file) return; setBusy(true); setError('');
    try { const imported = await leadLayoutApi.importTemplate(file); setDraft({ ...imported, version: draft.version }); setNotice('Template loaded. Match the columns to your lead fields, then save. Sample rows were not imported.'); }
    catch (e) { setError(e instanceof Error ? e.message : 'Cannot read template'); } finally { setBusy(false); }
  }
  async function save() {
    setBusy(true); setError('');
    try { const saved = await leadLayoutApi.save(draft); onSaved(saved); onClose(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Cannot save layout'); } finally { setBusy(false); }
  }
  async function applyMapping() {
    setBusy(true); setError(''); setNotice('');
    try {
      const rules = draft.columns.filter((c) => c.crmTargets[connectionId]?.trim()).map((c) => ({ source: crmSource(c.source), target: c.crmTargets[connectionId]!.trim(), ...(c.format !== 'plain' ? { transform: c.format } : {}) }));
      if (!rules.length) throw new Error('Choose at least one CRM destination field.');
      if (new Set(rules.map((r) => r.target)).size !== rules.length) throw new Error('Each CRM destination field can be mapped only once.');
      if (rules.some((r) => r.source === 'agentName')) throw new Error('Agent name is a display column. Leave its CRM destination blank.');
      const saved = await leadLayoutApi.save(draft); setDraft(saved); onSaved(saved);
      await leadCrmApi.putMapping(connectionId, { object_name: 'Leads', mapping: { ...existingMapping, fields: rules } });
      const result = await leadCrmApi.validateMappings(connectionId);
      if (!result.valid) throw new Error(`Mapping needs attention. Missing required fields: ${String(result.missingRequiredTargets ?? '')}. Unknown/read-only fields: ${String(result.unknownOrReadOnlyTargets ?? '')}.`);
      setNotice('Layout saved and CRM mapping activated. New sync requests will use these fields.');
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not apply CRM mapping'); } finally { setBusy(false); }
  }
  const known = [...new Set([...records.flatMap((r) => Object.keys(r.fields ?? {})), 'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'location', 'ip_address', 'page_url', 'page_slug', 'referrer'])];
  return <Modal open title="Customize leads" description="Choose the fields, column names and formats your team uses. Changes are shared in this workspace." size="lg" onClose={onClose} closeDisabled={busy} footer={<><Button variant="secondary" disabled={busy} onClick={onClose}>Cancel</Button><Button disabled={busy} onClick={() => void save()}>{busy ? 'Working...' : 'Save layout'}</Button></>}>
    <div className="lead-layout-editor">
      <div className="lead-layout-toolbar"><label>Layout name<input value={draft.name} maxLength={100} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label><label>Upload sample format<input type="file" accept=".csv,.xlsx" disabled={busy} onChange={(e) => { void importFile(e.target.files?.[0]); e.target.value = ''; }} /></label></div>
      <p>Use CSV or Excel (.xlsx), up to 2 MB. Headers from the first worksheet become columns. Review their data sources below.</p>
      {notice && <p role="status" className="lead-layout-notice">{notice}</p>}{error && <p role="alert" className="lead-layout-error">{error}</p>}
      <div className="lead-column-list">{draft.columns.map((column, index) => <div className="lead-column" key={column.id}>
        <div className="lead-column-heading"><strong>Column {index + 1}</strong><div><Button variant="secondary" size="icon" aria-label={`Move ${column.label} up`} disabled={index === 0 || busy} onClick={() => move(index, -1)}><ArrowUp /></Button><Button variant="secondary" size="icon" aria-label={`Move ${column.label} down`} disabled={index === draft.columns.length - 1 || busy} onClick={() => move(index, 1)}><ArrowDown /></Button><Button variant="secondary" size="icon" aria-label={`Remove ${column.label}`} disabled={draft.columns.length === 1 || busy} onClick={() => setDraft({ ...draft, columns: draft.columns.filter((c) => c.id !== column.id) })}><Trash2 /></Button></div></div>
        <div className="lead-column-fields"><label>Column name<input value={column.label} maxLength={100} onChange={(e) => patch(column.id, { label: e.target.value })} /></label>
        <label>Data source<select value={column.source.startsWith('fields.') && !known.includes(column.source.slice(7)) ? 'custom' : column.source} onChange={(e) => patch(column.id, { source: e.target.value === 'custom' ? `fields.${column.id}` : e.target.value })}>{Object.entries(standardSources).map(([key, label]) => <option key={key} value={key}>{label}</option>)}{known.map((key) => <option key={key} value={`fields.${key}`}>{key}</option>)}<option value="custom">Custom field</option></select></label>
        {column.source.startsWith('fields.') && <label>Custom field key<input value={column.source.slice(7)} maxLength={64} onChange={(e) => patch(column.id, { source: `fields.${e.target.value}` })} /><small>Stable key used to store this value.</small></label>}
        <label>Data type<select value={column.type} onChange={(e) => patch(column.id, { type: e.target.value as LeadColumn['type'] })}>{['text', 'number', 'date', 'boolean'].map((t) => <option key={t}>{t}</option>)}</select></label>
        <label>Display / export format<select value={column.format} onChange={(e) => patch(column.id, { format: e.target.value as LeadColumn['format'] })}><option value="plain">Original value</option><option value="upper">UPPERCASE</option><option value="lower">lowercase</option><option value="yyyy-mm-dd">YYYY-MM-DD</option><option value="dd/mm/yyyy">DD/MM/YYYY</option><option value="mm/dd/yyyy">MM/DD/YYYY</option></select></label></div>
        <div className="lead-column-options"><label><input type="checkbox" checked={column.visible} onChange={(e) => patch(column.id, { visible: e.target.checked })} /> Show in table and export</label>{column.source.startsWith('fields.') && <label><input type="checkbox" checked={column.required} onChange={(e) => patch(column.id, { required: e.target.checked })} /> Required when editing a lead</label>}</div>
        {connectionId && <label>CRM destination for {connections.find((c) => c.id === connectionId)?.name}<input list="crm-layout-fields" value={column.crmTargets[connectionId] ?? ''} maxLength={160} placeholder="Leave blank to omit from this mapping" onChange={(e) => patch(column.id, { crmTargets: { ...column.crmTargets, [connectionId]: e.target.value } })} /></label>}
      </div>)}</div>
      <Button variant="secondary" icon={Plus} disabled={busy || draft.columns.length >= 64} onClick={() => { const id = `custom_${crypto.randomUUID().replaceAll('-', '').slice(0, 12)}`; setDraft({ ...draft, columns: [...draft.columns, { id, label: `Custom field ${draft.columns.length + 1}`, source: `fields.${id}`, type: 'text', format: 'plain', visible: true, required: false, crmTargets: {} }] }); }}>Add field</Button>
      <h3>Preview your lead data</h3><div className="leads-table-wrap"><table className="leads-table"><thead><tr>{draft.columns.filter((c) => c.visible).map((c) => <th key={c.id}>{c.label}</th>)}</tr></thead><tbody>{records.slice(0, 3).map((lead) => <tr key={lead.id}>{draft.columns.filter((c) => c.visible).map((c) => <td key={c.id}>{leadColumnValue(lead, c, agentNames?.get(lead.agentId)) || '—'}</td>)}</tr>)}</tbody></table></div>{!records.length && <p>Values will appear here as leads are captured or entered.</p>}
      <h3>Send these fields to CRM</h3><label>CRM connection<select value={connectionId} onChange={(e) => setConnectionId(e.target.value)}><option value="">Choose a connection</option>{connections.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.status})</option>)}</select></label>
      <p>Choose destinations above, then apply. This replaces the connection's field rules and retains existing constants. Provider-required fields still apply. Exporting a file does not send leads to CRM.</p>
      <datalist id="crm-layout-fields">{schema?.fields.filter((f) => !f.readOnly).map((f) => <option key={f.apiName} value={f.apiName}>{f.label}{f.required ? ' (required)' : ''}</option>)}</datalist>
      {schemaError && <p role="alert">{schemaError}</p>}
      <Button disabled={!connectionId || !mappingLoaded || busy} onClick={() => void applyMapping()}>Save & apply CRM mapping</Button>
    </div>
  </Modal>;
}

import { CheckCircle2, GitBranch, RefreshCw, Save, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useToast } from '@/components/providers';
import { Badge, Button, Card } from '@/components/ui';
import {
  leadCrmApi,
  type CRMConnectionView,
  type CRMFieldSchemaView,
  type CRMMappingView,
  type CRMRouteView,
  type CRMWorkspaceSettings,
} from '@/lib/lead-crm-api';

interface CRMManagementPanelProps {
  connections: CRMConnectionView[];
  canManage: boolean;
  onConnectionsChanged: () => void;
}

const EMPTY_LEAD_MAPPING = '{\n  "fields": {}\n}';
const DEFAULT_ROUTE_NAME = 'Qualified leads';
const DEFAULT_ROUTE_PRIORITY = '100';
const DEFAULT_ROUTE_CONDITIONS = '{\n  "qualificationStatus": "qualified"\n}';

function parseObject(value: string, label: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error(`${label} must be a JSON object`);
  }
  return parsed as Record<string, unknown>;
}

export function CRMManagementPanel({ connections, canManage, onConnectionsChanged }: CRMManagementPanelProps) {
  const { pushToast } = useToast();
  const loadRequestRef = useRef(0);
  const [selectedId, setSelectedId] = useState('');
  const [pendingConnectionId, setPendingConnectionId] = useState('');
  const [schema, setSchema] = useState<CRMFieldSchemaView | null>(null);
  const [mappings, setMappings] = useState<CRMMappingView[]>([]);
  const [routes, setRoutes] = useState<CRMRouteView[]>([]);
  const [workspaceSettings, setWorkspaceSettings] = useState<CRMWorkspaceSettings | null>(null);
  const [mappingText, setMappingText] = useState(EMPTY_LEAD_MAPPING);
  const [mappingBaseline, setMappingBaseline] = useState(EMPTY_LEAD_MAPPING);
  const [routeName, setRouteName] = useState(DEFAULT_ROUTE_NAME);
  const [routePriority, setRoutePriority] = useState(DEFAULT_ROUTE_PRIORITY);
  const [conditionsText, setConditionsText] = useState(DEFAULT_ROUTE_CONDITIONS);
  const [busy, setBusy] = useState(false);

  const resetRouteDraft = useCallback(() => {
    setRouteName(DEFAULT_ROUTE_NAME);
    setRoutePriority(DEFAULT_ROUTE_PRIORITY);
    setConditionsText(DEFAULT_ROUTE_CONDITIONS);
  }, []);

  const clearConnectionState = useCallback(() => {
    setSchema(null);
    setMappings([]);
    setWorkspaceSettings(null);
    setMappingText(EMPTY_LEAD_MAPPING);
    setMappingBaseline(EMPTY_LEAD_MAPPING);
  }, []);

  useEffect(() => {
    if (!connections.length) {
      setSelectedId('');
      setPendingConnectionId('');
      clearConnectionState();
      resetRouteDraft();
      return;
    }
    if (!connections.some((connection) => connection.id === selectedId)) {
      setPendingConnectionId('');
      clearConnectionState();
      resetRouteDraft();
      setSelectedId(connections[0]?.id ?? '');
    }
  }, [clearConnectionState, connections, resetRouteDraft, selectedId]);

  const selected = useMemo(
    () => connections.find((connection) => connection.id === selectedId) ?? null,
    [connections, selectedId],
  );

  const pendingConnection = useMemo(
    () => connections.find((connection) => connection.id === pendingConnectionId) ?? null,
    [connections, pendingConnectionId],
  );

  const mappingDirty = mappingText !== mappingBaseline;
  const routeDraftDirty = routeName !== DEFAULT_ROUTE_NAME
    || routePriority !== DEFAULT_ROUTE_PRIORITY
    || conditionsText !== DEFAULT_ROUTE_CONDITIONS;
  const hasUnsavedDraft = mappingDirty || routeDraftDirty;

  const load = useCallback(async () => {
    const connectionId = selectedId;
    const requestId = ++loadRequestRef.current;
    clearConnectionState();
    if (!connectionId) {
      setRoutes([]);
      return;
    }
    try {
      const [nextSchema, nextMappings, nextRoutes, nextWorkspaceSettings] = await Promise.all([
        leadCrmApi.schema(connectionId),
        leadCrmApi.mappings(connectionId),
        leadCrmApi.routes(),
        leadCrmApi.workspaceSettings(connectionId),
      ]);
      if (requestId !== loadRequestRef.current) return;
      setSchema(nextSchema);
      setMappings(nextMappings);
      setRoutes(nextRoutes);
      setWorkspaceSettings(nextWorkspaceSettings);
      const leadMapping = nextMappings.find((item) => item.object_name === 'Leads');
      const nextMappingText = leadMapping
        ? JSON.stringify(leadMapping.mapping, null, 2)
        : EMPTY_LEAD_MAPPING;
      setMappingBaseline(nextMappingText);
      setMappingText(nextMappingText);
    } catch (error) {
      if (requestId !== loadRequestRef.current) return;
      pushToast(error instanceof Error ? error.message : 'Could not load CRM management data', 'error');
    }
  }, [clearConnectionState, pushToast, selectedId]);

  useEffect(() => {
    void load();
  }, [load]);

  const requestConnectionSwitch = (nextConnectionId: string) => {
    if (!nextConnectionId || nextConnectionId === selectedId) return;
    if (hasUnsavedDraft) {
      setPendingConnectionId(nextConnectionId);
      return;
    }
    setPendingConnectionId('');
    resetRouteDraft();
    setSelectedId(nextConnectionId);
  };

  const stayOnCurrentConnection = () => {
    setPendingConnectionId('');
  };

  const discardDraftAndSwitch = () => {
    const nextConnectionId = pendingConnectionId;
    if (!nextConnectionId) return;
    setPendingConnectionId('');
    clearConnectionState();
    resetRouteDraft();
    setSelectedId(nextConnectionId);
  };

  const saveMapping = async () => {
    if (!selectedId) return;
    setBusy(true);
    try {
      const mapping = parseObject(mappingText, 'Mapping');
      await leadCrmApi.putMapping(selectedId, { object_name: 'Leads', mapping });
      const validation = await leadCrmApi.validateMappings(selectedId);
      pushToast(validation.valid === false ? 'Mapping saved but requires attention' : 'Mapping saved and validated');
      await load();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Could not save mapping', 'error');
    } finally {
      setBusy(false);
    }
  };

  const refreshSchema = async () => {
    if (!selectedId) return;
    setBusy(true);
    try {
      await leadCrmApi.refreshSchema(selectedId);
      pushToast('CRM schema refreshed');
      await load();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Schema refresh failed', 'error');
    } finally {
      setBusy(false);
    }
  };

  const updateAutoSync = async (field: 'auto_sync_new_leads' | 'auto_sync_updates', value: boolean) => {
    if (!selectedId || !workspaceSettings) return;
    setBusy(true);
    try {
      const updated = await leadCrmApi.updateWorkspaceSettings(selectedId, { [field]: value });
      setWorkspaceSettings(updated);
      pushToast('CRM auto-sync settings updated');
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Could not update CRM auto-sync settings', 'error');
    } finally {
      setBusy(false);
    }
  };

  const createRoute = async () => {
    if (!selectedId) return;
    setBusy(true);
    try {
      const conditions = parseObject(conditionsText, 'Route conditions');
      const priority = Number.parseInt(routePriority, 10);
      if (!routeName.trim() || !Number.isFinite(priority) || priority < 0) throw new Error('Route name and valid priority are required');
      await leadCrmApi.createRoute({
        name: routeName.trim(),
        enabled: true,
        priority,
        conditions,
        connection_ids: [selectedId],
      });
      resetRouteDraft();
      pushToast('CRM route created');
      await load();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Could not create route', 'error');
    } finally {
      setBusy(false);
    }
  };

  const toggleRoute = async (route: CRMRouteView) => {
    setBusy(true);
    try {
      await leadCrmApi.updateRoute(route.id, { enabled: !route.enabled });
      pushToast(`Route ${route.enabled ? 'disabled' : 'enabled'}`);
      await load();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Could not update route', 'error');
    } finally {
      setBusy(false);
    }
  };

  const deleteRoute = async (route: CRMRouteView) => {
    setBusy(true);
    try {
      await leadCrmApi.deleteRoute(route.id);
      pushToast('CRM route deleted');
      await load();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Could not delete route', 'error');
    } finally {
      setBusy(false);
    }
  };

  const disableConnection = async () => {
    if (!selectedId) return;
    setBusy(true);
    try {
      await leadCrmApi.disableConnection(selectedId);
      pushToast('CRM connection disabled and credentials removed');
      setPendingConnectionId('');
      setSelectedId('');
      clearConnectionState();
      resetRouteDraft();
      onConnectionsChanged();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Could not disable CRM connection', 'error');
    } finally {
      setBusy(false);
    }
  };

  if (!connections.length) return null;
  const selectedRoutes = routes.filter((route) => route.connection_ids.includes(selectedId));
  const currentMapping = mappings.find((item) => item.object_name === 'Leads');

  return <Card className="crm-management-panel">
    <div className="page-heading page-heading--split">
      <div><h3>CRM mapping & routing</h3><p>Discover provider fields, validate mappings, and control exactly which qualified leads are delivered to each CRM.</p></div>
      <Badge tone="purple">Management wizard</Badge>
    </div>

    <div className="integration-toolbar">
      <label>
        CRM connection
        <select aria-label="CRM management connection" value={selectedId} disabled={busy} onChange={(event) => requestConnectionSwitch(event.target.value)}>
          {connections.map((connection) => <option key={connection.id} value={connection.id}>{connection.name} · {connection.provider}</option>)}
        </select>
      </label>
      {selected ? <Badge>{selected.status}</Badge> : null}
      <Button variant="secondary" size="sm" icon={RefreshCw} disabled={!canManage || busy} onClick={() => void refreshSchema()}>Refresh schema</Button>
      <Button variant="secondary" size="sm" disabled={!canManage || busy} onClick={() => void disableConnection()}>Disable connection</Button>
    </div>

    {pendingConnection ? <div role="alert" className="integration-helper">
      <strong>Unsaved CRM setup changes</strong>
      <p>
        {mappingDirty && routeDraftDirty
          ? 'Your Lead mapping and routing-rule drafts have unsaved changes.'
          : mappingDirty
            ? 'Your Lead mapping draft has unsaved changes.'
            : 'Your routing-rule draft has unsaved changes.'}{' '}
        Switching to {pendingConnection.name} would discard those drafts.
      </p>
      <div>
        <Button variant="secondary" size="sm" disabled={busy} onClick={stayOnCurrentConnection}>Stay on current CRM</Button>{' '}
        <Button variant="secondary" size="sm" disabled={busy} onClick={discardDraftAndSwitch}>Discard & switch</Button>
      </div>
    </div> : null}

    <Card className="integration-card">
      <div className="integration-card__copy">
        <span><h3>Automatic CRM sync</h3><Badge tone={workspaceSettings?.auto_sync_new_leads || workspaceSettings?.auto_sync_updates ? 'success' : 'neutral'}>Workspace scoped</Badge></span>
        <p>Choose which automatic Lead events create CRM deliveries for this connection. Manual Sync remains available even when automation is disabled.</p>
        <label>
          <input
            type="checkbox"
            aria-label="Automatically sync new leads"
            checked={workspaceSettings?.auto_sync_new_leads ?? false}
            disabled={!canManage || busy || !workspaceSettings}
            onChange={(event) => void updateAutoSync('auto_sync_new_leads', event.target.checked)}
          />
          Automatically sync new leads
        </label>
        <label>
          <input
            type="checkbox"
            aria-label="Automatically sync lead updates"
            checked={workspaceSettings?.auto_sync_updates ?? false}
            disabled={!canManage || busy || !workspaceSettings}
            onChange={(event) => void updateAutoSync('auto_sync_updates', event.target.checked)}
          />
          Automatically sync lead updates
        </label>
      </div>
    </Card>

    <div className="integration-grid">
      <Card className="integration-card">
        <div className="integration-card__copy">
          <span><h3>Provider schema</h3><Badge>{schema?.fields.length ?? 0} fields</Badge></span>
          <p>Hash: {schema?.schemaHash ?? 'not discovered'}</p>
          <div>{schema?.fields.slice(0, 12).map((field) => <p key={field.apiName}><strong>{field.label}</strong> · {field.apiName} · {field.dataType}{field.required ? ' · required' : ''}{field.readOnly ? ' · read only' : ''}</p>)}</div>
          {(schema?.fields.length ?? 0) > 12 ? <small>Showing first 12 fields. Mapping validation uses the complete discovered schema.</small> : null}
        </div>
      </Card>

      <Card className="integration-card">
        <div className="integration-card__copy">
          <span><h3>Lead field mapping</h3>{currentMapping ? <Badge tone={currentMapping.status === 'active' ? 'success' : 'warning'}>{currentMapping.status}</Badge> : <Badge>draft</Badge>}</span>
          <p>Map canonical Lead fields to provider API fields. Constants, defaults and transforms remain supported by the backend mapping engine.</p>
          <textarea aria-label="CRM lead mapping JSON" rows={12} value={mappingText} onChange={(event) => setMappingText(event.target.value)} spellCheck={false} />
          {currentMapping?.validation ? <small>Validation: {JSON.stringify(currentMapping.validation)}</small> : null}
          <Button icon={Save} disabled={!canManage || busy} onClick={() => void saveMapping()}>Save & validate</Button>
        </div>
      </Card>
    </div>

    <div className="integration-grid">
      <Card className="integration-card">
        <div className="integration-card__copy">
          <span><h3>Create routing rule</h3><GitBranch /></span>
          <input aria-label="CRM route name" value={routeName} onChange={(event) => setRouteName(event.target.value)} placeholder="Route name" />
          <input aria-label="CRM route priority" type="number" min="0" value={routePriority} onChange={(event) => setRoutePriority(event.target.value)} placeholder="Priority" />
          <textarea aria-label="CRM route conditions JSON" rows={7} value={conditionsText} onChange={(event) => setConditionsText(event.target.value)} spellCheck={false} />
          <Button icon={GitBranch} disabled={!canManage || busy} onClick={() => void createRoute()}>Create route</Button>
        </div>
      </Card>

      <Card className="integration-card">
        <div className="integration-card__copy">
          <span><h3>Active routes</h3><Badge>{selectedRoutes.length}</Badge></span>
          {selectedRoutes.length ? selectedRoutes.map((route) => <div key={route.id}>
            <p><strong>{route.name}</strong> · priority {route.priority} · v{route.version}</p>
            <small>{JSON.stringify(route.conditions)}</small>
            <div>
              <Button variant="secondary" size="sm" icon={CheckCircle2} disabled={!canManage || busy} onClick={() => void toggleRoute(route)}>{route.enabled ? 'Disable' : 'Enable'}</Button>{' '}
              <Button variant="secondary" size="sm" icon={Trash2} disabled={!canManage || busy} onClick={() => void deleteRoute(route)}>Delete</Button>
            </div>
          </div>) : <p>No routes target this connection yet.</p>}
        </div>
      </Card>
    </div>
  </Card>;
}
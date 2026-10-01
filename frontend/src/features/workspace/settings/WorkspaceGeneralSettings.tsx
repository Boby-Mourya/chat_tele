import { useEffect, useState } from 'react';
import { Badge, Button, Card, Field, PageLoader, Switch } from '@/components/ui';
import type { WorkspaceSettings } from '@/lib/workspace-api';
import {
  workspaceSettingsApi,
  type BusinessHours,
  type WorkspaceGeneralMetadata,
  type WorkspaceSettingsBundle,
} from './workspaceSettings.api';

const DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'] as const;

function firstRange(hours: BusinessHours, day: string): string {
  return hours.schedule[day]?.[0] ?? '';
}

function setRange(hours: BusinessHours, day: string, value: string): BusinessHours {
  const schedule = { ...hours.schedule };
  const normalized = value.trim();
  if (normalized) schedule[day] = [normalized];
  else delete schedule[day];
  return { ...hours, schedule };
}

export function WorkspaceGeneralSettings({
  workspace,
  bundle,
  disabled,
  onWorkspace,
  onBundle,
  onSave,
}: {
  workspace: WorkspaceSettings;
  bundle: WorkspaceSettingsBundle;
  disabled: boolean;
  onWorkspace: (value: WorkspaceSettings) => void;
  onBundle: (value: WorkspaceSettingsBundle) => void;
  onSave: () => void;
}) {
  const [metadata, setMetadata] = useState<WorkspaceGeneralMetadata | null>(null);
  const [metadataError, setMetadataError] = useState('');
  const general = bundle.general;

  useEffect(() => {
    let current = true;
    workspaceSettingsApi.generalMetadata().then((value) => {
      if (current) {
        setMetadata(value);
        setMetadataError('');
      }
    }).catch((reason: unknown) => {
      if (current) setMetadataError(reason instanceof Error ? reason.message : 'Workspace metadata could not be loaded');
    });
    return () => { current = false; };
  }, []);

  if (!metadata && !metadataError) return <PageLoader />;

  return <Card className="workspace-panel">
    <div className="workspace-panel__body">
      <div className="page-heading page-heading--split">
        <div><h3>General</h3><p>Workspace identity, ownership, locale, and operating schedule.</p></div>
        {metadata ? <Badge tone={metadata.status === 'active' ? 'success' : 'neutral'}>{metadata.status}</Badge> : null}
      </div>
      {metadataError ? <p role="alert">{metadataError}</p> : null}
      <div className="two-fields">
        <Field label="Workspace name"><input disabled={disabled} value={workspace.name} onChange={(event) => onWorkspace({ ...workspace, name: event.target.value })} /></Field>
        <Field label="Workspace slug"><input disabled={disabled} value={workspace.slug} onChange={(event) => onWorkspace({ ...workspace, slug: event.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '') })} /></Field>
      </div>
      <div className="two-fields">
        <Field label="Workspace ID"><input readOnly value={metadata?.workspaceId ?? workspace.id} /></Field>
        <Field label="Organization"><input readOnly value={metadata?.organization ?? workspace.tenantName} /></Field>
      </div>
      <div className="two-fields">
        <Field label="Workspace owner"><input readOnly value={metadata?.owner ? `${metadata.owner.name} (${metadata.owner.email})` : 'No owner recorded'} /></Field>
        <Field label="Workspace status"><input readOnly value={metadata?.status ?? workspace.status} /></Field>
      </div>
      <div className="two-fields">
        <Field label="Industry"><input disabled={disabled} value={general.industry} onChange={(event) => onBundle({ ...bundle, general: { ...general, industry: event.target.value } })} /></Field>
        <Field label="Country"><input disabled={disabled} value={general.country} onChange={(event) => onBundle({ ...bundle, general: { ...general, country: event.target.value } })} /></Field>
      </div>
      <div className="two-fields">
        <Field label="Timezone"><input disabled={disabled} value={workspace.preferences.timezone} onChange={(event) => onWorkspace({ ...workspace, preferences: { ...workspace.preferences, timezone: event.target.value } })} /></Field>
        <Field label="Default language"><input disabled={disabled} value={workspace.preferences.defaultLanguage} onChange={(event) => onWorkspace({ ...workspace, preferences: { ...workspace.preferences, defaultLanguage: event.target.value } })} /></Field>
      </div>
      <div className="two-fields">
        <Field label="Date format"><input disabled={disabled} value={workspace.preferences.dateFormat} onChange={(event) => onWorkspace({ ...workspace, preferences: { ...workspace.preferences, dateFormat: event.target.value as WorkspaceSettings['preferences']['dateFormat'] } })} /></Field>
        <Field label="Time format"><select disabled={disabled} value={general.timeFormat} onChange={(event) => onBundle({ ...bundle, general: { ...general, timeFormat: event.target.value as '12h' | '24h' } })}><option value="12h">12 hour</option><option value="24h">24 hour</option></select></Field>
      </div>
      <div className="two-fields">
        <Field label="Currency"><input disabled={disabled} maxLength={3} value={general.currency} onChange={(event) => onBundle({ ...bundle, general: { ...general, currency: event.target.value.toUpperCase() } })} /></Field>
        <Field label="Week start"><select disabled={disabled} value={general.weekStart} onChange={(event) => onBundle({ ...bundle, general: { ...general, weekStart: event.target.value as 'monday' | 'sunday' } })}><option value="monday">Monday</option><option value="sunday">Sunday</option></select></Field>
      </div>
      <Field label="Workspace icon"><input disabled={disabled} value={general.workspaceIcon} placeholder="Asset URL or data URL" onChange={(event) => onBundle({ ...bundle, general: { ...general, workspaceIcon: event.target.value } })} /></Field>
      <Field label="Description"><textarea disabled={disabled} value={general.description} onChange={(event) => onBundle({ ...bundle, general: { ...general, description: event.target.value } })} /></Field>
      <Switch checked={general.businessHours.enabled} disabled={disabled} onChange={(enabled) => onBundle({ ...bundle, general: { ...general, businessHours: { ...general.businessHours, enabled } } })} label="Business hours" description="Use workspace business hours for routing, widgets, and escalation policies." />
      {general.businessHours.enabled ? <div className="setup-resource">
        <Field label="Business-hours timezone"><input disabled={disabled} value={general.businessHours.timezone} onChange={(event) => onBundle({ ...bundle, general: { ...general, businessHours: { ...general.businessHours, timezone: event.target.value } } })} /></Field>
        <p>Use 24-hour ranges such as <code>09:00-17:30</code>. Leave a day empty when closed.</p>
        {DAYS.map((day) => <Field key={day} label={day.charAt(0).toUpperCase() + day.slice(1)}><input disabled={disabled} value={firstRange(general.businessHours, day)} placeholder="09:00-17:00" onChange={(event) => onBundle({ ...bundle, general: { ...general, businessHours: setRange(general.businessHours, day, event.target.value) } })} /></Field>)}
      </div> : null}
      <div className="workspace-panel__actions"><Button disabled={disabled} onClick={onSave}>Save general settings</Button></div>
    </div>
  </Card>;
}

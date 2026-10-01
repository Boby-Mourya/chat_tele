import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CRMManagementPanel } from '@/components/crm-management-panel';

const mocks = vi.hoisted(() => ({
  pushToast: vi.fn(),
  schema: vi.fn(),
  mappings: vi.fn(),
  routes: vi.fn(),
  workspaceSettings: vi.fn(),
  updateWorkspaceSettings: vi.fn(),
  refreshSchema: vi.fn(),
  putMapping: vi.fn(),
  validateMappings: vi.fn(),
  createRoute: vi.fn(),
  updateRoute: vi.fn(),
  deleteRoute: vi.fn(),
  disableConnection: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useToast: () => ({ pushToast: mocks.pushToast }),
}));

vi.mock('@/lib/lead-crm-api', () => ({
  leadCrmApi: {
    schema: mocks.schema,
    mappings: mocks.mappings,
    routes: mocks.routes,
    workspaceSettings: mocks.workspaceSettings,
    updateWorkspaceSettings: mocks.updateWorkspaceSettings,
    refreshSchema: mocks.refreshSchema,
    putMapping: mocks.putMapping,
    validateMappings: mocks.validateMappings,
    createRoute: mocks.createRoute,
    updateRoute: mocks.updateRoute,
    deleteRoute: mocks.deleteRoute,
    disableConnection: mocks.disableConnection,
  },
}));

const connection = {
  id: 'connection-1',
  public_id: 'crm_public_1',
  provider: 'zoho' as const,
  name: 'Zoho Production',
  environment: 'production',
  status: 'healthy' as const,
  configuration: {},
  capabilities: {},
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

const secondConnection = {
  ...connection,
  id: 'connection-2',
  public_id: 'crm_public_2',
  provider: 'salesforce' as const,
  name: 'Salesforce Production',
};

const settings = {
  connection_id: 'connection-1',
  auto_sync_new_leads: true,
  auto_sync_updates: true,
  updated_at: new Date().toISOString(),
};

const secondSettings = {
  ...settings,
  connection_id: 'connection-2',
  auto_sync_new_leads: false,
  auto_sync_updates: false,
};

const zohoSchema = {
  connectionId: 'connection-1',
  objectName: 'Leads',
  schemaHash: 'zoho-hash',
  fields: [{
    apiName: 'Last_Name',
    label: 'Zoho Last Name',
    dataType: 'string',
    required: true,
    nullable: false,
    readOnly: false,
    unique: false,
    custom: false,
    maxLength: 120,
    picklistValues: [],
  }],
};

const salesforceSchema = {
  connectionId: 'connection-2',
  objectName: 'Leads',
  schemaHash: 'salesforce-hash',
  fields: [{
    apiName: 'Email',
    label: 'Salesforce Email',
    dataType: 'string',
    required: false,
    nullable: true,
    readOnly: false,
    unique: false,
    custom: false,
    maxLength: 320,
    picklistValues: [],
  }],
};

const zohoMapping = {
  connection_id: 'connection-1',
  object_name: 'Leads',
  version: 1,
  status: 'active',
  mapping: { fields: { Last_Name: 'name' } },
  validation: {},
};

const salesforceMapping = {
  connection_id: 'connection-2',
  object_name: 'Leads',
  version: 1,
  status: 'active',
  mapping: { fields: { Email: 'email' } },
  validation: {},
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe('CRMManagementPanel auto-sync settings', () => {
  beforeEach(() => {
    mocks.schema.mockResolvedValue({ connectionId: 'connection-1', objectName: 'Leads', fields: [] });
    mocks.mappings.mockResolvedValue([]);
    mocks.routes.mockResolvedValue([]);
    mocks.workspaceSettings.mockResolvedValue(settings);
    mocks.updateWorkspaceSettings.mockImplementation(async (_id: string, patch: Record<string, boolean>) => ({
      ...settings,
      ...patch,
    }));
    mocks.refreshSchema.mockResolvedValue(undefined);
    mocks.putMapping.mockResolvedValue(undefined);
    mocks.validateMappings.mockResolvedValue({ valid: true });
    mocks.createRoute.mockResolvedValue(undefined);
    mocks.updateRoute.mockResolvedValue(undefined);
    mocks.deleteRoute.mockResolvedValue(undefined);
    mocks.disableConnection.mockResolvedValue(undefined);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('loads workspace auto-sync settings and persists both controls', async () => {
    const user = userEvent.setup();
    render(<CRMManagementPanel connections={[connection]} canManage onConnectionsChanged={vi.fn()} />);

    const newLeads = await screen.findByRole('checkbox', { name: 'Automatically sync new leads' });
    const updates = screen.getByRole('checkbox', { name: 'Automatically sync lead updates' });
    expect(newLeads).toBeChecked();
    expect(updates).toBeChecked();
    expect(mocks.workspaceSettings).toHaveBeenCalledWith('connection-1');

    await user.click(newLeads);
    await waitFor(() => expect(mocks.updateWorkspaceSettings).toHaveBeenCalledWith(
      'connection-1',
      { auto_sync_new_leads: false },
    ));
    await waitFor(() => expect(newLeads).not.toBeChecked());

    await user.click(updates);
    await waitFor(() => expect(mocks.updateWorkspaceSettings).toHaveBeenCalledWith(
      'connection-1',
      { auto_sync_updates: false },
    ));
    expect(mocks.pushToast).toHaveBeenCalledWith('CRM auto-sync settings updated');
  });

  it('keeps auto-sync settings read-only without CRM management permission', async () => {
    render(<CRMManagementPanel connections={[connection]} canManage={false} onConnectionsChanged={vi.fn()} />);

    expect(await screen.findByRole('checkbox', { name: 'Automatically sync new leads' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: 'Automatically sync lead updates' })).toBeDisabled();
    expect(mocks.updateWorkspaceSettings).not.toHaveBeenCalled();
  });

  it('clears the previous mapping and settings when switching to a connection with no mapping', async () => {
    const user = userEvent.setup();
    mocks.schema.mockImplementation(async (id: string) => id === 'connection-1' ? zohoSchema : salesforceSchema);
    mocks.mappings.mockImplementation(async (id: string) => id === 'connection-1' ? [zohoMapping] : []);
    mocks.workspaceSettings.mockImplementation(async (id: string) => id === 'connection-1' ? settings : secondSettings);

    render(<CRMManagementPanel connections={[connection, secondConnection]} canManage onConnectionsChanged={vi.fn()} />);

    const mappingEditor = await screen.findByRole('textbox', { name: 'CRM lead mapping JSON' });
    await waitFor(() => expect(mappingEditor).toHaveValue(JSON.stringify(zohoMapping.mapping, null, 2)));
    expect(screen.getByRole('checkbox', { name: 'Automatically sync new leads' })).toBeChecked();

    await user.selectOptions(screen.getByRole('combobox', { name: 'CRM management connection' }), 'connection-2');

    await waitFor(() => expect(mocks.mappings).toHaveBeenCalledWith('connection-2'));
    await waitFor(() => expect(mappingEditor).toHaveValue('{\n  "fields": {}\n}'));
    expect(screen.getByRole('checkbox', { name: 'Automatically sync new leads' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Automatically sync lead updates' })).not.toBeChecked();
    expect(await screen.findByText('Salesforce Email')).toBeInTheDocument();
  });

  it('ignores an older connection load that resolves after a newer selection', async () => {
    const user = userEvent.setup();
    const firstSchema = deferred<typeof zohoSchema>();
    const firstMappings = deferred<typeof zohoMapping[]>();
    const firstSettings = deferred<typeof settings>();

    mocks.schema.mockImplementation((id: string) => id === 'connection-1'
      ? firstSchema.promise
      : Promise.resolve(salesforceSchema));
    mocks.mappings.mockImplementation((id: string) => id === 'connection-1'
      ? firstMappings.promise
      : Promise.resolve([salesforceMapping]));
    mocks.workspaceSettings.mockImplementation((id: string) => id === 'connection-1'
      ? firstSettings.promise
      : Promise.resolve(secondSettings));

    render(<CRMManagementPanel connections={[connection, secondConnection]} canManage onConnectionsChanged={vi.fn()} />);

    await waitFor(() => expect(mocks.schema).toHaveBeenCalledWith('connection-1'));
    await user.selectOptions(screen.getByRole('combobox', { name: 'CRM management connection' }), 'connection-2');

    const mappingEditor = screen.getByRole('textbox', { name: 'CRM lead mapping JSON' });
    await waitFor(() => expect(mappingEditor).toHaveValue(JSON.stringify(salesforceMapping.mapping, null, 2)));
    expect(await screen.findByText('Salesforce Email')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Automatically sync new leads' })).not.toBeChecked();

    await act(async () => {
      firstSchema.resolve(zohoSchema);
      firstMappings.resolve([zohoMapping]);
      firstSettings.resolve(settings);
      await Promise.resolve();
    });

    expect(mappingEditor).toHaveValue(JSON.stringify(salesforceMapping.mapping, null, 2));
    expect(screen.getByText('Salesforce Email')).toBeInTheDocument();
    expect(screen.queryByText('Zoho Last Name')).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Automatically sync new leads' })).not.toBeChecked();
    expect(mocks.pushToast).not.toHaveBeenCalledWith('Could not load CRM management data', 'error');
  });

  it('blocks connection switching when the Lead mapping has unsaved changes', async () => {
    const user = userEvent.setup();
    mocks.schema.mockImplementation(async (id: string) => id === 'connection-1' ? zohoSchema : salesforceSchema);
    mocks.mappings.mockImplementation(async (id: string) => id === 'connection-1' ? [zohoMapping] : [salesforceMapping]);
    mocks.workspaceSettings.mockImplementation(async (id: string) => id === 'connection-1' ? settings : secondSettings);

    render(<CRMManagementPanel connections={[connection, secondConnection]} canManage onConnectionsChanged={vi.fn()} />);

    const selector = screen.getByRole('combobox', { name: 'CRM management connection' });
    const mappingEditor = await screen.findByRole('textbox', { name: 'CRM lead mapping JSON' });
    await waitFor(() => expect(mappingEditor).toHaveValue(JSON.stringify(zohoMapping.mapping, null, 2)));

    const unsavedMapping = '{\n  "fields": {\n    "Email": "email"\n  }\n}';
    fireEvent.change(mappingEditor, { target: { value: unsavedMapping } });
    await user.selectOptions(selector, 'connection-2');

    expect(selector).toHaveValue('connection-1');
    expect(await screen.findByRole('alert')).toHaveTextContent('Lead mapping draft has unsaved changes');
    expect(screen.getByRole('alert')).toHaveTextContent('Salesforce Production');
    expect(mocks.mappings).not.toHaveBeenCalledWith('connection-2');

    await user.click(screen.getByRole('button', { name: 'Stay on current CRM' }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(mappingEditor).toHaveValue(unsavedMapping);
    expect(selector).toHaveValue('connection-1');

    await user.selectOptions(selector, 'connection-2');
    await user.click(await screen.findByRole('button', { name: 'Discard & switch' }));

    await waitFor(() => expect(selector).toHaveValue('connection-2'));
    await waitFor(() => expect(mocks.mappings).toHaveBeenCalledWith('connection-2'));
    await waitFor(() => expect(mappingEditor).toHaveValue(JSON.stringify(salesforceMapping.mapping, null, 2)));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('does not carry an unsaved routing-rule draft to another CRM connection', async () => {
    const user = userEvent.setup();
    mocks.schema.mockImplementation(async (id: string) => id === 'connection-1' ? zohoSchema : salesforceSchema);
    mocks.mappings.mockImplementation(async (id: string) => id === 'connection-1' ? [zohoMapping] : [salesforceMapping]);
    mocks.workspaceSettings.mockImplementation(async (id: string) => id === 'connection-1' ? settings : secondSettings);

    render(<CRMManagementPanel connections={[connection, secondConnection]} canManage onConnectionsChanged={vi.fn()} />);

    const selector = screen.getByRole('combobox', { name: 'CRM management connection' });
    await screen.findByText('Zoho Last Name');
    fireEvent.change(screen.getByRole('textbox', { name: 'CRM route name' }), {
      target: { value: 'Zoho-only high-value leads' },
    });

    await user.selectOptions(selector, 'connection-2');
    expect(await screen.findByRole('alert')).toHaveTextContent('routing-rule draft has unsaved changes');
    expect(selector).toHaveValue('connection-1');

    await user.click(screen.getByRole('button', { name: 'Discard & switch' }));
    await waitFor(() => expect(selector).toHaveValue('connection-2'));
    await screen.findByText('Salesforce Email');

    expect(screen.getByRole('textbox', { name: 'CRM route name' })).toHaveValue('Qualified leads');
    expect(screen.getByRole('spinbutton', { name: 'CRM route priority' })).toHaveValue(100);
    expect(screen.getByRole('textbox', { name: 'CRM route conditions JSON' })).toHaveValue(
      '{\n  "qualificationStatus": "qualified"\n}',
    );

    await user.click(screen.getByRole('button', { name: 'Create route' }));
    await waitFor(() => expect(mocks.createRoute).toHaveBeenCalledWith(expect.objectContaining({
      name: 'Qualified leads',
      connection_ids: ['connection-2'],
    })));
  });

  it('allows switching without a warning after the mapping draft is saved and reloaded', async () => {
    const user = userEvent.setup();
    let persistedZohoMapping = zohoMapping;
    mocks.schema.mockImplementation(async (id: string) => id === 'connection-1' ? zohoSchema : salesforceSchema);
    mocks.mappings.mockImplementation(async (id: string) => id === 'connection-1' ? [persistedZohoMapping] : [salesforceMapping]);
    mocks.workspaceSettings.mockImplementation(async (id: string) => id === 'connection-1' ? settings : secondSettings);
    mocks.putMapping.mockImplementation(async (_id: string, payload: { mapping: Record<string, unknown> }) => {
      persistedZohoMapping = { ...zohoMapping, mapping: payload.mapping as typeof zohoMapping.mapping };
    });

    render(<CRMManagementPanel connections={[connection, secondConnection]} canManage onConnectionsChanged={vi.fn()} />);

    const selector = screen.getByRole('combobox', { name: 'CRM management connection' });
    const mappingEditor = await screen.findByRole('textbox', { name: 'CRM lead mapping JSON' });
    await waitFor(() => expect(mappingEditor).toHaveValue(JSON.stringify(zohoMapping.mapping, null, 2)));

    const savedMapping = '{\n  "fields": {\n    "Last_Name": "name",\n    "Email": "email"\n  }\n}';
    fireEvent.change(mappingEditor, { target: { value: savedMapping } });
    await user.click(screen.getByRole('button', { name: 'Save & validate' }));
    await waitFor(() => expect(mocks.putMapping).toHaveBeenCalledWith(
      'connection-1',
      { object_name: 'Leads', mapping: JSON.parse(savedMapping) },
    ));
    await waitFor(() => expect(mappingEditor).toHaveValue(savedMapping));

    await user.selectOptions(selector, 'connection-2');

    await waitFor(() => expect(selector).toHaveValue('connection-2'));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    await waitFor(() => expect(mocks.mappings).toHaveBeenCalledWith('connection-2'));
  });
});
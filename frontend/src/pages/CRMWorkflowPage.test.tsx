import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { CRMWorkflowPage } from '@/pages/CRMWorkflowPage';

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
}));

vi.mock('@/lib/crm-workflow-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/crm-workflow-api')>(
    '@/lib/crm-workflow-api',
  );
  return {
    ...actual,
    crmWorkflowApi: { get: mocks.get },
  };
});

const readyWorkflow = {
  generatedAt: '2026-09-13T05:30:00Z',
  workspaceId: 'workspace-1',
  readiness: {
    ready: true,
    stages: [
      {
        id: 'lead_generation',
        label: 'Lead generation Agent',
        description: 'A Lead Generation Agent resolves conversations.',
        status: 'ready',
        detail: '1 active Lead Generation Agent is available.',
      },
      {
        id: 'crm_connection',
        label: 'Workspace CRM connection',
        description: 'Workspace-scoped CRM configuration.',
        status: 'ready',
        detail: 'Zoho Sandbox is healthy.',
      },
    ],
  },
  counts: {
    resolvedConversations: 12,
    localLeads: 9,
    leadsWithoutDelivery: 1,
    totalDeliveries: 8,
    inFlightDeliveries: 2,
    verifiedDeliveries: 5,
    attentionDeliveries: 1,
    openDeadLetters: 1,
    byStatus: {
      queued: 1,
      verifying: 1,
      verified: 5,
      dead_letter: 1,
    },
  },
  connections: [
    {
      id: 'connection-1',
      name: 'Zoho Sandbox',
      provider: 'zoho',
      environment: 'sandbox',
      status: 'healthy',
      credentialsConfigured: true,
      mappingConfigured: true,
      mappingStatus: 'active',
      mappingVersion: 4,
      enabledRouteCount: 1,
      autoSyncNewLeads: true,
      autoSyncUpdates: true,
      ready: true,
      lastHealthAt: '2026-09-13T05:25:00Z',
      lastSuccessAt: '2026-09-13T05:29:00Z',
      lastFailureAt: null,
      lastError: null,
    },
  ],
  recentJourneys: [
    {
      leadId: 'lead-1',
      conversationId: 'conversation-1',
      conversationPublicId: 'cnv_1001',
      agentId: 'agent-1',
      agentName: 'Admissions Lead Agent',
      customerName: 'Anita Sharma',
      email: 'anita@example.com',
      phone: '+919999999999',
      sourceChannel: 'whatsapp',
      lifecycleStatus: 'qualified',
      qualificationStatus: 'qualified',
      qualificationScore: 91,
      stage: 'verified',
      stageLabel: 'Verified in CRM',
      stageDetail: 'The provider record passed read-back verification.',
      nextActionLabel: 'Open Lead',
      nextActionPath: '/leads',
      delivery: {
        id: 'delivery-1',
        connectionId: 'connection-1',
        connectionName: 'Zoho Sandbox',
        provider: 'zoho',
        operation: 'upsert',
        status: 'verified',
        verificationStatus: 'verified',
        externalRecordId: 'zoho-1001',
        attemptCount: 1,
        verificationAttemptCount: 1,
        acknowledgedAt: '2026-09-13T05:28:00Z',
        verifiedAt: '2026-09-13T05:29:00Z',
        nextRetryAt: null,
        nextVerificationAt: null,
        lastErrorCode: null,
        lastErrorMessage: null,
        verificationErrorCode: null,
        verificationErrorMessage: null,
        deadLetterOpen: false,
        createdAt: '2026-09-13T05:27:00Z',
        updatedAt: '2026-09-13T05:29:00Z',
      },
      createdAt: '2026-09-13T05:20:00Z',
      updatedAt: '2026-09-13T05:29:00Z',
    },
  ],
};

describe('CRMWorkflowPage', () => {
  beforeEach(() => {
    mocks.get.mockResolvedValue(readyWorkflow);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('shows the complete frontend and backend Lead-to-CRM workflow', async () => {
    render(
      <MemoryRouter>
        <CRMWorkflowPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText('CRM full workflow')).toBeInTheDocument();
    expect(screen.getByText('Automatic flow ready')).toBeInTheDocument();
    expect(screen.getByText('1. Conversation captured')).toBeInTheDocument();
    expect(screen.getByText('2. Resolve and qualify')).toBeInTheDocument();
    expect(screen.getByText('4. Durable CRM routing')).toBeInTheDocument();
    expect(screen.getByText('7. Provider acknowledgement')).toBeInTheDocument();
    expect(screen.getByText('8. Read-back or recovery')).toBeInTheDocument();
    expect(screen.getByText('conversation_resolution_service.resolve()')).toBeInTheDocument();
    expect(screen.getByText('lead.crm.sync.requested.v1 → WorkspaceCRMRouteService')).toBeInTheDocument();
  });

  it('renders live readiness, connection, delivery proof, and journey state', async () => {
    render(
      <MemoryRouter>
        <CRMWorkflowPage />
      </MemoryRouter>,
    );

    expect((await screen.findAllByText('Zoho Sandbox')).length).toBeGreaterThan(0);
    expect(screen.getByText('Anita Sharma')).toBeInTheDocument();
    expect(screen.getByText('Verified in CRM')).toBeInTheDocument();
    expect(screen.getByText('External ID: zoho-1001')).toBeInTheDocument();
    expect(screen.getByText('Score 91/100')).toBeInTheDocument();
  });

  it('refreshes the workspace workflow without losing the current result', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <CRMWorkflowPage />
      </MemoryRouter>,
    );

    expect((await screen.findAllByText('Zoho Sandbox')).length).toBeGreaterThan(0);
    await user.click(screen.getByRole('button', { name: 'Refresh' }));

    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(2));
    expect(screen.getAllByText('Zoho Sandbox').length).toBeGreaterThan(0);
  });

  it('shows deterministic setup actions when automatic CRM delivery is blocked', async () => {
    mocks.get.mockResolvedValueOnce({
      ...readyWorkflow,
      readiness: {
        ready: false,
        stages: [
          {
            id: 'crm_connection',
            label: 'Workspace CRM connection',
            description: 'Workspace-scoped CRM configuration.',
            status: 'blocked',
            detail: 'No CRM connection is assigned to this workspace.',
            actionLabel: 'Open CRM setup',
            actionPath: '/integrations',
          },
        ],
      },
      connections: [],
      recentJourneys: [],
    });

    render(
      <MemoryRouter>
        <CRMWorkflowPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText('Setup requires attention')).toBeInTheDocument();
    expect(screen.getByText('No CRM connection is assigned to this workspace.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open CRM setup/i })).toHaveAttribute(
      'href',
      '/integrations',
    );
  });
});

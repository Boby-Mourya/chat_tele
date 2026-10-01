import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider } from '@/components/providers';
import { demoAgents, demoLeads } from '@/lib/demo-data';
import type { CRMDeliveryAttemptView, CRMDeliveryView } from '@/lib/lead-crm-api';
import { LeadsPage } from '@/pages/LeadsPage';
import type { Agent, Lead, PageResult } from '@/types';

interface LeadFilters {
  page?: number;
  pageSize?: number;
  search?: string;
  status?: string;
  agentId?: string;
}

const apiMocks = vi.hoisted(() => ({
  listLeads: vi.fn<(filters?: LeadFilters) => Promise<PageResult<Lead>>>(),
  listFallbackLeads: vi.fn<() => Promise<PageResult<Lead>>>(),
  listAgents: vi.fn<() => Promise<Agent[]>>(),
  updateStatus: vi.fn<(leadId: string, status: string) => Promise<Lead>>(),
  deliveriesForLead: vi.fn<(leadId: string) => Promise<CRMDeliveryView[]>>(),
  deliveryAttempts: vi.fn<(deliveryId: string) => Promise<CRMDeliveryAttemptView[]>>(),
  activityForLead: vi.fn<() => Promise<never[]>>(),
  syncLead: vi.fn<() => Promise<Record<string, never>>>(),
  retryDelivery: vi.fn<() => Promise<Record<string, never>>>(),
}));

vi.mock('@/lib/api', () => ({
  api: {
    agents: { list: apiMocks.listAgents },
    leads: { list: apiMocks.listFallbackLeads, updateStatus: apiMocks.updateStatus },
  },
}));

vi.mock('@/lib/lead-crm-api', () => ({
  leadCrmApi: {
    leads: apiMocks.listLeads,
    deliveriesForLead: apiMocks.deliveriesForLead,
    deliveryAttempts: apiMocks.deliveryAttempts,
    activityForLead: apiMocks.activityForLead,
    syncLead: apiMocks.syncLead,
    retryDelivery: apiMocks.retryDelivery,
  },
}));

vi.mock('@/lib/lead-layout-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/lead-layout-api')>();
  return { ...actual, leadLayoutApi: { ...actual.leadLayoutApi, get: vi.fn(async () => actual.defaultLayout) } };
});

describe('LeadsPage', () => {
  beforeEach(() => {
    const leads = structuredClone(demoLeads);
    apiMocks.listAgents.mockResolvedValue(structuredClone(demoAgents));
    apiMocks.listFallbackLeads.mockResolvedValue({
      items: structuredClone(demoLeads), total: demoLeads.length, page: 1, pageSize: 50,
    });
    apiMocks.listLeads.mockImplementation(async (filters = {}) => {
      const search = filters.search?.trim().toLowerCase();
      const status = filters.status;
      const items = leads.filter((lead) => {
        const matchesSearch = !search || `${lead.name ?? ''} ${lead.email ?? ''} ${lead.phone ?? ''}`.toLowerCase().includes(search);
        const matchesStatus = !status || status === 'all' || lead.status === status;
        return matchesSearch && matchesStatus;
      });
      return { items, total: items.length, page: filters.page ?? 1, pageSize: filters.pageSize ?? 50 };
    });
    apiMocks.updateStatus.mockImplementation(async (leadId, status) => ({ ...leads.find((lead) => lead.id === leadId)!, status }));
    apiMocks.deliveriesForLead.mockResolvedValue([]);
    apiMocks.deliveryAttempts.mockResolvedValue([]);
    apiMocks.activityForLead.mockResolvedValue([]);
    apiMocks.syncLead.mockResolvedValue({});
    apiMocks.retryDelivery.mockResolvedValue({});
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('filters captured contacts through the server API and persists a status change', async () => {
    const user = userEvent.setup();
    render(<ToastProvider><LeadsPage /></ToastProvider>);

    expect(await screen.findByText('Nora Reed')).toBeInTheDocument();
    await user.type(screen.getByLabelText('Search leads'), 'Arjun');
    expect(await screen.findByText('Arjun Mehta')).toBeInTheDocument();
    expect(screen.queryByText('Nora Reed')).not.toBeInTheDocument();
    await waitFor(() => expect(apiMocks.listLeads).toHaveBeenCalledWith(expect.objectContaining({ search: 'Arjun' })));

    await user.clear(screen.getByLabelText('Search leads'));
    expect(await screen.findByText('Nora Reed')).toBeInTheDocument();
    await user.selectOptions(screen.getByRole('combobox', { name: 'Status for Nora Reed' }), 'converted');
    await waitFor(() => expect(apiMocks.updateStatus).toHaveBeenCalledWith('lead-1', 'converted'));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Status for Nora Reed' }), 'qualified');
    await waitFor(() => expect(apiMocks.updateStatus).toHaveBeenCalledWith('lead-1', 'qualified'));
    expect(await screen.findByText('Nora Reed marked Qualified. Resolved leads sync automatically using your CRM settings.')).toBeInTheDocument();
    expect(apiMocks.syncLead).not.toHaveBeenCalled();
  });

  it('uses the configured app fallback when the CRM API is unavailable', async () => {
    apiMocks.listLeads.mockRejectedValueOnce(new Error('Request failed (502)'));

    render(<ToastProvider><LeadsPage /></ToastProvider>);

    expect(await screen.findByText('Nora Reed')).toBeInTheDocument();
    expect(screen.queryByText('Leads are unavailable')).not.toBeInTheDocument();
    expect(apiMocks.listFallbackLeads).toHaveBeenCalledOnce();
  });

  it('loads persisted CRM delivery attempt evidence on demand for the selected Lead', async () => {
    const user = userEvent.setup();
    const delivery: CRMDeliveryView = {
      id: 'delivery-1',
      lead_id: 'lead-1',
      connection_id: 'connection-1',
      provider: 'zoho',
      operation: 'upsert',
      status: 'failed',
      verification_status: 'failed',
      verification_attempt_count: 0,
      attempt_count: 2,
      last_error_message: 'Provider unavailable',
      created_at: '2026-09-12T08:00:00.000Z',
    };
    const attempts: CRMDeliveryAttemptView[] = [
      {
        id: 'attempt-1',
        delivery_id: delivery.id,
        attempt_number: 1,
        started_at: '2026-09-12T08:00:00.000Z',
        finished_at: '2026-09-12T08:00:01.000Z',
        http_status: 500,
        latency_ms: 120,
        result_status: 'retryable_error',
        normalized_error_code: 'provider_unavailable',
        provider_error_code: 'SERVER_ERROR',
        provider_request_id: 'provider-request-1',
      },
      {
        id: 'attempt-2',
        delivery_id: delivery.id,
        attempt_number: 2,
        started_at: '2026-09-12T08:01:00.000Z',
        finished_at: '2026-09-12T08:01:01.000Z',
        http_status: 429,
        latency_ms: 180,
        result_status: 'retryable_error',
        normalized_error_code: 'rate_limited',
        provider_error_code: 'TOO_MANY_REQUESTS',
        provider_request_id: 'provider-request-2',
      },
    ];
    apiMocks.deliveriesForLead.mockImplementation(async (leadId) => leadId === 'lead-1' ? [delivery] : []);
    apiMocks.deliveryAttempts.mockResolvedValue(attempts);

    render(<ToastProvider><LeadsPage /></ToastProvider>);

    expect(await screen.findByText('Nora Reed')).toBeInTheDocument();
    const viewSyncButtons = screen.getAllByRole('button', { name: 'View sync' });
    await user.click(viewSyncButtons[0]!);
    expect(await screen.findByText('Provider unavailable')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Attempts (2)' }));

    await waitFor(() => expect(apiMocks.deliveryAttempts).toHaveBeenCalledWith('delivery-1'));
    expect(await screen.findByText('Attempt 1')).toBeInTheDocument();
    expect(screen.getByText('Attempt 2')).toBeInTheDocument();
    expect(screen.getByText('HTTP 500 · 120 ms')).toBeInTheDocument();
    expect(screen.getByText('HTTP 429 · 180 ms')).toBeInTheDocument();
    expect(screen.getByText('Provider request: provider-request-1')).toBeInTheDocument();
    expect(screen.getByText('Error: provider_unavailable · SERVER_ERROR')).toBeInTheDocument();
    expect(screen.getByText('Error: rate_limited · TOO_MANY_REQUESTS')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Hide attempts' }));
    expect(screen.queryByText('Attempt 1')).not.toBeInTheDocument();
  });
});

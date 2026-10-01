import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AnalyticsPage } from '@/pages/AnalyticsPage';

const mocks = vi.hoisted(() => ({ summary: vi.fn() }));

vi.mock('@/lib/analytics-api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/analytics-api')>('@/lib/analytics-api');
  return { ...actual, analyticsApi: { summary: mocks.summary } };
});

const data = {
  period: 'Last 30 days',
  conversations: 100,
  conversationsDelta: 12.5,
  resolutionRate: 80,
  resolutionDelta: 4,
  avgResponseSeconds: 1.4,
  satisfaction: 4.6,
  chart: [{ label: 'Sep 01', conversations: 10, resolved: 8 }],
  topQuestions: [{ question: 'How do I enroll?', count: 8, resolutionRate: 87.5 }],
  channels: [{ channel: 'Widget', value: 70 }, { channel: 'WhatsApp', value: 30 }],
  agents: { total: 5, active: 4, support: 2, leadGeneration: 1, education: 2 },
  leads: { created: 20, qualified: 12, converted: 4, qualificationRate: 60, conversionRate: 20 },
  crm: { deliveries: 10, verified: 8, failed: 1, successRate: 80 },
  education: { students: 50, activeEnrollments: 45, conversations: 30, activityEvents: 18 },
};

describe('AnalyticsPage', () => {
  beforeEach(() => {
    mocks.summary.mockResolvedValue(data);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('preserves conversation analytics and renders lead, CRM, agent, and education outcomes', async () => {
    render(<AnalyticsPage />);

    expect(await screen.findByText('Total conversations')).toBeInTheDocument();
    expect(screen.getByText('Conversations & resolutions')).toBeInTheDocument();
    expect(screen.getByText('Top questions')).toBeInTheDocument();
    expect(screen.getByText('Channels')).toBeInTheDocument();
    expect(screen.getByText('Leads created')).toBeInTheDocument();
    expect(screen.getByText('CRM verified')).toBeInTheDocument();
    expect(screen.getByText('Active students')).toBeInTheDocument();
    expect(screen.getByText('Active agents')).toBeInTheDocument();
    expect(screen.getByText('Lead & CRM outcomes')).toBeInTheDocument();
    expect(screen.getByText('Education & agent mix')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Export' })).toBeInTheDocument();
    expect(mocks.summary).toHaveBeenCalledWith(30);
  });

  it('reloads analytics when the user changes the reporting period', async () => {
    const user = userEvent.setup();
    render(<AnalyticsPage />);
    await screen.findByText('Total conversations');

    await user.selectOptions(screen.getByLabelText('Analytics period'), '7');

    await waitFor(() => expect(mocks.summary).toHaveBeenCalledWith(7));
  });

  it('shows an actionable error if analytics cannot be loaded', async () => {
    mocks.summary.mockRejectedValueOnce(new Error('Analytics unavailable'));
    render(<AnalyticsPage />);

    expect(await screen.findByText('Analytics could not be loaded')).toBeInTheDocument();
    expect(screen.getByText('Analytics unavailable')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });
});

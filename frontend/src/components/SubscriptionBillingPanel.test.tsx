import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SubscriptionBillingPanel } from '@/components/SubscriptionBillingPanel';
import type { WorkspaceSettings } from '@/lib/workspace-api';

const mocks = vi.hoisted(() => ({
  pushToast: vi.fn(),
  getSubscription: vi.fn(),
  getEntitlements: vi.fn(),
  createCheckout: vi.fn(),
  createPortal: vi.fn(),
  cancelSubscription: vi.fn(),
  reactivateSubscription: vi.fn(),
  role: 'owner',
}));

vi.mock('@/components/providers', () => ({
  useAuth: () => ({
    session: {
      user: { id: 'user-1', name: 'Owner', email: 'owner@example.com', role: mocks.role },
    },
  }),
  useToast: () => ({ pushToast: mocks.pushToast }),
}));

vi.mock('@/lib/billing-api', () => ({
  billingApi: {
    getSubscription: mocks.getSubscription,
    getEntitlements: mocks.getEntitlements,
    createCheckout: mocks.createCheckout,
    createPortal: mocks.createPortal,
    cancelSubscription: mocks.cancelSubscription,
    reactivateSubscription: mocks.reactivateSubscription,
  },
}));

const workspace: WorkspaceSettings = {
  id: 'workspace-1',
  tenantId: 'tenant-1',
  tenantName: 'Northstar Academy',
  name: 'Admissions',
  slug: 'admissions',
  status: 'active',
  role: 'workspace_admin',
  permissions: ['*'],
  plan: 'starter',
  memberCount: 4,
  preferences: {
    timezone: 'Asia/Calcutta',
    defaultLanguage: 'English',
    dateFormat: 'DD/MM/YYYY',
  },
  security: { sensitiveDataMasking: true, securityContact: null },
  whiteLabel: {
    companyName: 'Northstar Academy',
    logoDataUrl: '',
    faviconDataUrl: '',
    appIconDataUrl: '',
    primaryColor: '#146cf6',
    secondaryColor: '#705cf6',
    supportEmail: 'support@example.com',
    supportUrl: 'https://example.com/support',
    browserTitle: 'Northstar',
    customDomain: '',
    dnsStatus: 'not-configured',
    brandedLogin: true,
    brandedDashboard: true,
    brandedWidget: true,
    brandedEmails: true,
    removePlatformBranding: false,
  },
};

const subscription = {
  id: 'subscription-1',
  tenantId: 'tenant-1',
  plan: 'professional',
  status: 'trial',
  provider: null,
  trialEndsAt: '2026-09-25T00:00:00Z',
  currentPeriodStart: null,
  currentPeriodEnd: null,
  cancelAtPeriodEnd: false,
  pastDueAt: null,
  suspendedAt: null,
  cancelledAt: null,
  createdAt: '2026-09-11T00:00:00Z',
  updatedAt: '2026-09-11T00:00:00Z',
};

const entitlements = {
  plan: 'professional',
  subscriptionStatus: 'trial',
  limits: {
    workspaces: 3,
    agents: 5,
    members: 10,
    conversationsMonthly: 3000,
    tokensMonthly: 2_000_000,
    storageBytes: 5 * 1024 ** 3,
  },
  usage: {
    workspaces: 2,
    agents: 4,
    members: 7,
    pendingMemberSeats: 1,
    conversationsMonthly: 1200,
    tokensMonthly: 450_000,
    storageBytes: 1024 ** 3,
  },
  features: {
    allowedChannels: ['widget', 'api', 'whatsapp'],
    crm: true,
    api: true,
    whiteLabel: false,
  },
};

describe('SubscriptionBillingPanel', () => {
  beforeEach(() => {
    mocks.role = 'owner';
    mocks.getSubscription.mockResolvedValue(subscription);
    mocks.getEntitlements.mockResolvedValue(entitlements);
    mocks.createCheckout.mockResolvedValue({ url: 'https://checkout.stripe.com/c/pay/test' });
    mocks.createPortal.mockResolvedValue({ url: 'https://billing.stripe.com/p/session/test' });
    mocks.cancelSubscription.mockResolvedValue({
      ...subscription,
      status: 'cancelled',
      trialEndsAt: null,
      cancelledAt: '2026-09-11T12:00:00Z',
    });
    mocks.reactivateSubscription.mockResolvedValue({
      ...subscription,
      status: 'active',
      trialEndsAt: null,
      cancelAtPeriodEnd: false,
      cancelledAt: null,
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('renders backend subscription state and measured entitlement usage', async () => {
    const user = userEvent.setup();
    render(<SubscriptionBillingPanel workspace={workspace} />);

    expect(await screen.findByText('Professional · Trial')).toBeInTheDocument();
    expect(screen.getByText('Professional subscription')).toBeInTheDocument();
    expect(screen.getByText(/Trial ends/)).toBeInTheDocument();
    expect(screen.getByText('Provider: Not connected')).toBeInTheDocument();
    expect(screen.getByText('Conversations this month')).toBeInTheDocument();
    expect(screen.getByText('1,200 / 3,000')).toBeInTheDocument();
    expect(screen.getByText('4 / 5')).toBeInTheDocument();
    expect(screen.getByText('8 / 10 (1 pending)')).toBeInTheDocument();
    expect(screen.getByText('450,000 / 2,000,000')).toBeInTheDocument();
    expect(screen.getByText('1.0 GB / 5.0 GB')).toBeInTheDocument();
    expect(screen.getByText(/CRM: Included/)).toBeInTheDocument();
    expect(screen.getByText(/White-label: Upgrade required/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Manage billing' }));
    expect(screen.getByRole('dialog', { name: 'Manage subscription' })).toBeInTheDocument();
    expect(screen.getByText('Cancel subscription now')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Confirm cancellation' })).toBeDisabled();
    expect(mocks.getSubscription).toHaveBeenCalledWith('starter');
    expect(mocks.getEntitlements).toHaveBeenCalledWith('starter');
  });

  it('replaces the plan placeholder with a real upgrade choice without changing current state first', async () => {
    const user = userEvent.setup();
    render(<SubscriptionBillingPanel workspace={workspace} />);
    await screen.findByText('Professional · Trial');

    await user.click(screen.getByRole('button', { name: 'Compare plans' }));
    expect(screen.getByRole('dialog', { name: 'Compare plans' })).toBeInTheDocument();
    expect(screen.getByText('Business')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Choose Business' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Choose Professional' })).not.toBeInTheDocument();
    expect(mocks.createCheckout).not.toHaveBeenCalled();
  });

  it('requires explicit CANCEL confirmation and applies safe soft offboarding', async () => {
    const user = userEvent.setup();
    render(<SubscriptionBillingPanel workspace={workspace} />);
    await screen.findByText('Professional · Trial');

    await user.click(screen.getByRole('button', { name: 'Manage billing' }));
    await user.type(screen.getByLabelText('Type CANCEL to confirm'), 'CANCEL');
    await user.click(screen.getByRole('button', { name: 'Confirm cancellation' }));

    await waitFor(() => expect(mocks.cancelSubscription).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('Professional · Cancelled')).toBeInTheDocument();
    expect(screen.getByText(/New resource creation and other plan-gated writes are blocked/)).toBeInTheDocument();
    expect(mocks.pushToast).toHaveBeenCalledWith(
      'Subscription cancelled. Existing tenant data has been preserved',
      'success',
    );
  });

  it('lets a billing manager remove a scheduled cancellation', async () => {
    const user = userEvent.setup();
    mocks.getSubscription.mockResolvedValueOnce({
      ...subscription,
      status: 'active',
      trialEndsAt: null,
      currentPeriodEnd: '2026-10-01T00:00:00Z',
      cancelAtPeriodEnd: true,
    });
    render(<SubscriptionBillingPanel workspace={workspace} />);

    expect(await screen.findByText('Professional · Active')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Manage billing' }));
    expect(screen.getByText('Cancellation is scheduled')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Keep subscription' }));

    await waitFor(() => expect(mocks.reactivateSubscription).toHaveBeenCalledTimes(1));
    expect(mocks.cancelSubscription).not.toHaveBeenCalled();
  });

  it('does not expose billing mutations to a user without billing management permission', async () => {
    mocks.role = 'member';
    render(<SubscriptionBillingPanel workspace={{ ...workspace, permissions: ['workspace.view'] }} />);

    expect(await screen.findByText('Professional · Trial')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Manage billing' })).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Compare plans' }));
    expect(screen.getByText('Ask a tenant billing administrator to upgrade this plan.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Choose Business' })).not.toBeInTheDocument();
  });

  it('routes Stripe-managed subscriptions to the secure provider portal instead of local cancellation', async () => {
    const user = userEvent.setup();
    mocks.getSubscription.mockResolvedValueOnce({ ...subscription, provider: 'stripe' });
    render(<SubscriptionBillingPanel workspace={workspace} />);

    await screen.findByText('Provider: Stripe');
    await user.click(screen.getByRole('button', { name: 'Manage billing' }));
    expect(screen.getByText('Stripe-managed subscription')).toBeInTheDocument();
    expect(screen.getByText(/Signed Stripe webhooks keep Northstar subscription status/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open billing portal' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Confirm cancellation' })).not.toBeInTheDocument();
    expect(mocks.cancelSubscription).not.toHaveBeenCalled();
  });

  it('shows authorization failures instead of inventing billing access', async () => {
    mocks.getEntitlements.mockRejectedValueOnce(new Error('Insufficient permission'));
    render(<SubscriptionBillingPanel workspace={workspace} />);

    expect(await screen.findByText('Billing access is unavailable')).toBeInTheDocument();
    expect(screen.getByText('Insufficient permission')).toBeInTheDocument();
    await waitFor(() => expect(mocks.pushToast).toHaveBeenCalledWith('Insufficient permission', 'error'));
  });
});

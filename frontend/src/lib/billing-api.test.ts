import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { billingApi } from '@/lib/billing-api';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}
const subscription = {
  id: 'subscription-1', tenantId: 'tenant-1', plan: 'business', status: 'active', provider: null,
  trialEndsAt: null, currentPeriodStart: null, currentPeriodEnd: null, cancelAtPeriodEnd: false,
  pastDueAt: null, suspendedAt: null, cancelledAt: null,
  createdAt: '2026-09-11T00:00:00Z', updatedAt: '2026-09-11T00:00:00Z',
};
const entitlements = {
  plan: 'business', subscriptionStatus: 'active',
  limits: { workspaces: 10, agents: 10, members: 20, conversationsMonthly: 5000, tokensMonthly: 5_000_000, storageBytes: 20 * 1024 ** 3 },
  usage: { workspaces: 2, agents: 4, members: 6, pendingMemberSeats: 1, conversationsMonthly: 100, tokensMonthly: 20_000, storageBytes: 1024 },
  features: { allowedChannels: ['widget', 'api', 'whatsapp'], crm: true, api: true, whiteLabel: true },
};

describe('billingApi uses authoritative organization state', () => {
  const fetchMock = vi.fn<typeof fetch>();
  beforeEach(() => {
    localStorage.setItem('northstar.session', JSON.stringify({ accessToken: 'session-token' }));
    localStorage.setItem('northstar.active-workspace-id', JSON.stringify('workspace-1'));
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals(); vi.resetAllMocks(); localStorage.clear();
  });

  it('loads the real subscription and entitlements without operational workspace authority', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(subscription));
    await expect(billingApi.getSubscription('free')).resolves.toEqual(subscription);
    expect(fetchMock).toHaveBeenLastCalledWith('/api/v1/billing/subscription', expect.objectContaining({
      credentials: 'include', cache: 'no-store', headers: { Accept: 'application/json', Authorization: 'Bearer session-token' },
    }));
    fetchMock.mockResolvedValueOnce(jsonResponse(entitlements));
    await expect(billingApi.getEntitlements('free')).resolves.toEqual(entitlements);
    expect(fetchMock.mock.calls.at(-1)?.[1]?.headers).not.toHaveProperty('X-Workspace-ID');
  });

  it('creates hosted checkout and portal redirects through authenticated backend mutations', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ url: 'https://checkout.stripe.com/c/pay/test' }));
    await expect(billingApi.createCheckout('professional')).resolves.toEqual({ url: 'https://checkout.stripe.com/c/pay/test' });
    expect(fetchMock).toHaveBeenLastCalledWith('/api/v1/billing/checkout', expect.objectContaining({
      method: 'POST', credentials: 'include', body: JSON.stringify({ plan: 'professional' }),
      headers: { Accept: 'application/json', 'Content-Type': 'application/json', Authorization: 'Bearer session-token' },
    }));
    fetchMock.mockResolvedValueOnce(jsonResponse({ url: 'https://billing.stripe.com/p/session/test' }));
    await expect(billingApi.createPortal()).resolves.toEqual({ url: 'https://billing.stripe.com/p/session/test' });
    expect(fetchMock).toHaveBeenLastCalledWith('/api/v1/billing/portal', expect.objectContaining({ method: 'POST' }));
  });

  it('cancels and reactivates only after backend acknowledgement', async () => {
    const cancelled = { ...subscription, status: 'cancelled', cancelledAt: '2026-09-11T12:00:00Z' };
    fetchMock.mockResolvedValueOnce(jsonResponse(cancelled));
    await expect(billingApi.cancelSubscription()).resolves.toEqual(cancelled);
    expect(fetchMock).toHaveBeenLastCalledWith('/api/v1/billing/cancel', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ confirmation: 'CANCEL' }),
    }));
    fetchMock.mockResolvedValueOnce(jsonResponse(subscription));
    await expect(billingApi.reactivateSubscription()).resolves.toEqual(subscription);
    expect(fetchMock).toHaveBeenLastCalledWith('/api/v1/billing/reactivate', expect.objectContaining({ method: 'POST' }));
  });

  it('never invents a successful mutation or automatically resends one', async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: { message: 'Provider workflow required' } }, 409));
    await expect(billingApi.cancelSubscription()).rejects.toThrow('Provider workflow required');
    fetchMock.mockRejectedValueOnce(new TypeError('Network unavailable'));
    await expect(billingApi.reactivateSubscription()).rejects.toThrow('Network unavailable');
    fetchMock.mockRejectedValueOnce(new TypeError('Network unavailable'));
    await expect(billingApi.createCheckout('professional')).rejects.toThrow('Network unavailable');
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it.each([401, 403, 409, 429, 500, 502, 503])('surfaces HTTP %i for reads instead of fabricating billing data', async (status) => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: { message: 'Billing unavailable' } }, status));
    await expect(billingApi.getSubscription('business')).rejects.toMatchObject({ status, message: 'Billing unavailable' });
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: 'Entitlements unavailable' }, status));
    await expect(billingApi.getEntitlements('legacy_custom_contract')).rejects.toMatchObject({ status, message: 'Entitlements unavailable' });
  });

  it.each(['free', 'business', 'legacy_custom_contract'])('does not turn an outage into a plan named %s', async (plan) => {
    fetchMock.mockRejectedValueOnce(new TypeError('Network unavailable'));
    await expect(billingApi.getSubscription(plan)).rejects.toThrow('Network unavailable');
    fetchMock.mockRejectedValueOnce(new TypeError('Network unavailable'));
    await expect(billingApi.getEntitlements(plan)).rejects.toThrow('Network unavailable');
  });

  it('requires an interactive credential rather than sending an unauthenticated request', async () => {
    localStorage.removeItem('northstar.session');
    await expect(billingApi.getSubscription()).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('discards a response after account change without repeating the mutation', async () => {
    fetchMock.mockImplementationOnce(async () => {
      localStorage.setItem('northstar.session', JSON.stringify({ accessToken: 'other-account' }));
      return jsonResponse(subscription);
    });
    await expect(billingApi.cancelSubscription()).rejects.toMatchObject({ status: 409 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('checks account context again after reading a delayed response body', async () => {
    const response = jsonResponse(subscription);
    vi.spyOn(response, 'json').mockImplementationOnce(async () => {
      localStorage.removeItem('northstar.session');
      return subscription;
    });
    fetchMock.mockResolvedValueOnce(response);
    await expect(billingApi.getSubscription()).rejects.toMatchObject({ status: 409 });
  });

  it('rejects malformed success bodies instead of presenting them as a subscription', async () => {
    fetchMock.mockResolvedValueOnce(new Response('<html>Proxy failure</html>', { status: 200 }));
    await expect(billingApi.getSubscription()).rejects.toMatchObject({ status: 502 });
  });

  it.each(['javascript:alert(1)', 'http://billing.example.test', '//billing.example.test', 'https://user:pass@billing.example.test', 'not-a-url'])('rejects unsafe redirect %s', async (url) => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ url }));
    await expect(billingApi.createPortal()).rejects.toMatchObject({ status: 502 });
  });
});

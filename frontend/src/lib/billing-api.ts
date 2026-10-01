import { readStorage } from '@/lib/storage';

export type SubscriptionStatus = 'trial' | 'active' | 'past_due' | 'suspended' | 'cancelled';
export interface TenantSubscription {
  id: string; tenantId: string; plan: string; status: SubscriptionStatus; provider: string | null;
  trialEndsAt: string | null; currentPeriodStart: string | null; currentPeriodEnd: string | null;
  cancelAtPeriodEnd: boolean; pastDueAt: string | null; suspendedAt: string | null;
  cancelledAt: string | null; createdAt: string; updatedAt: string;
}
export interface EntitlementLimits { workspaces: number | null; agents: number | null; members: number | null; conversationsMonthly: number | null; tokensMonthly: number | null; storageBytes: number | null }
export interface EntitlementUsage { workspaces: number; agents: number; members: number; pendingMemberSeats: number; conversationsMonthly: number; tokensMonthly: number; storageBytes: number }
export interface TenantEntitlements { plan: string; subscriptionStatus: SubscriptionStatus; limits: EntitlementLimits; usage: EntitlementUsage; features: { allowedChannels: string[]; crm: boolean; api: boolean; whiteLabel: boolean } }
export interface BillingRedirect { url: string }

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

class BillingRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'BillingRequestError';
  }
}

function bearer(): string | undefined {
  return readStorage<{ accessToken?: string } | null>(SESSION_KEY, null)?.accessToken;
}

function checkContext(token: string): void {
  if (bearer() !== token) {
    throw new BillingRequestError(
      'The active account changed. Reload billing; this request may already have completed.', 409,
    );
  }
}

async function remote<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = bearer();
  if (!token) throw new BillingRequestError('Sign in to access organization billing.', 401);
  // Billing belongs to the authenticated organization. A remembered operational
  // workspace must not prevent its billing administrator from recovering access.
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: 'include',
    cache: 'no-store',
    headers: {
      Accept: 'application/json',
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      Authorization: `Bearer ${token}`,
    },
  });
  checkContext(token);
  const payload: unknown = await response.json().catch(() => null);
  checkContext(token);
  if (!response.ok) {
    const error = payload as { error?: { message?: unknown }; detail?: unknown } | null;
    const detail = error?.error?.message ?? error?.detail;
    throw new BillingRequestError(
      typeof detail === 'string' ? detail : `Billing request failed (${response.status})`, response.status,
    );
  }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new BillingRequestError('The billing service returned an invalid response.', 502);
  }
  return payload as T;
}

async function redirect(path: string, body?: unknown): Promise<BillingRedirect> {
  const value = await remote<BillingRedirect>(path, {
    method: 'POST', body: body === undefined ? undefined : JSON.stringify(body),
  });
  let url: URL;
  try { url = new URL(value.url); }
  catch { throw new BillingRequestError('The billing provider returned an invalid redirect.', 502); }
  if (url.protocol !== 'https:' || url.username || url.password) {
    throw new BillingRequestError('The billing provider returned an unsafe redirect.', 502);
  }
  return value;
}

// The compatibility plan argument is not a source of subscription authority.
// Failed reads and writes propagate to the existing billing panel's error UI.
export const billingApi = {
  getSubscription: (_fallbackPlan = 'starter') => remote<TenantSubscription>('/billing/subscription'),
  getEntitlements: (_fallbackPlan = 'starter') => remote<TenantEntitlements>('/billing/entitlements'),
  createCheckout: (plan: string) => redirect('/billing/checkout', { plan }),
  createPortal: () => redirect('/billing/portal'),
  cancelSubscription: () => remote<TenantSubscription>('/billing/cancel', {
    method: 'POST', body: JSON.stringify({ confirmation: 'CANCEL' }),
  }),
  reactivateSubscription: () => remote<TenantSubscription>('/billing/reactivate', { method: 'POST' }),
};

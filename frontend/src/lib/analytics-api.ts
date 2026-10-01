import { demoAgents, demoAnalytics, demoLeads } from '@/lib/demo-data';
import { activeWorkspaceId } from '@/lib/workspace-api';
import { clone, readStorage } from '@/lib/storage';
import type { AnalyticsSummary, Session } from '@/types';

export type AnalyticsPeriodDays = 7 | 30 | 90;

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const SESSION_KEY = 'northstar.session';

class AnalyticsRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'AnalyticsRequestError';
  }
}

function session(): Session | null {
  return readStorage<Session | null>(SESSION_KEY, null);
}

function inPeriod(value: string, days: AnalyticsPeriodDays): boolean {
  return new Date(value).getTime() >= Date.now() - days * 86_400_000;
}

function demoSummary(days: AnalyticsPeriodDays): AnalyticsSummary {
  const value = clone(demoAnalytics);
  const periodLeads = demoLeads.filter((lead) => inPeriod(lead.createdAt, days));
  const qualified = periodLeads.filter((lead) => lead.status === 'qualified').length;
  const converted = periodLeads.filter((lead) => lead.status === 'converted').length;
  const leadGeneration = demoAgents.filter((agent) => agent.purpose === 'lead_generation').length;
  const education = demoAgents.filter((agent) => agent.purpose === 'education').length;
  value.period = `Last ${days} days`;
  value.agents = {
    total: demoAgents.length,
    active: demoAgents.filter((agent) => agent.status === 'active').length,
    support: Math.max(0, demoAgents.length - leadGeneration - education),
    leadGeneration,
    education,
  };
  value.leads = {
    created: periodLeads.length,
    qualified,
    converted,
    qualificationRate: periodLeads.length ? Math.round(qualified * 1000 / periodLeads.length) / 10 : 0,
    conversionRate: periodLeads.length ? Math.round(converted * 1000 / periodLeads.length) / 10 : 0,
  };
  value.crm = { deliveries: 0, verified: 0, failed: 0, successRate: 0 };
  value.education = { students: 0, activeEnrollments: 0, conversations: 0, activityEvents: 0 };
  return value;
}

async function remote(days: AnalyticsPeriodDays): Promise<AnalyticsSummary> {
  const active = session();
  const workspaceId = activeWorkspaceId();
  const response = await fetch(`${API_URL}/analytics/summary?days=${days}`, {
    credentials: 'include',
    headers: {
      Accept: 'application/json',
      ...(active ? { Authorization: `Bearer ${active.accessToken}` } : {}),
      ...(workspaceId ? { 'X-Workspace-ID': workspaceId } : {}),
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { error?: { message?: string } } | null;
    throw new AnalyticsRequestError(
      payload?.error?.message ?? `Analytics request failed (${response.status})`,
      response.status,
    );
  }
  return response.json() as Promise<AnalyticsSummary>;
}

export const analyticsApi = {
  async summary(days: AnalyticsPeriodDays = 30): Promise<AnalyticsSummary> {
    try {
      return await remote(days);
    } catch (error) {
      if (error instanceof AnalyticsRequestError && error.status >= 400 && error.status < 500) throw error;
      return demoSummary(days);
    }
  },
};

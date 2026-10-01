import { describe, expect, it } from 'vitest';
import type { DashboardWidget } from '@/features/workspace/settings/workspaceSettings.api';
import { widgetVisibleToViewer, type DashboardViewerContext } from './dashboard.types';

const baseViewer: DashboardViewerContext = {
  role: 'manager',
  permissions: ['analytics.view', 'leads.view', 'conversations.view'],
  industry: 'Education',
  country: 'IN',
  enabledFeatures: ['crm', 'api'],
};

function widget(overrides: Partial<DashboardWidget> = {}): DashboardWidget {
  return {
    id: 'widget-1',
    type: 'conversation-summary',
    x: 0,
    y: 0,
    width: 4,
    height: 2,
    visible: true,
    audience: [],
    config: {},
    ...overrides,
  };
}

describe('widgetVisibleToViewer', () => {
  it('uses role, permissions, industry and enabled feature filters together', () => {
    expect(widgetVisibleToViewer(widget({
      audience: ['manager'],
      config: {
        requiredPermissions: ['analytics.view'],
        industries: ['education'],
        requiredFeature: 'crm',
      },
    }), baseViewer)).toBe(true);
  });

  it('hides widgets when any configured audience boundary is not satisfied', () => {
    expect(widgetVisibleToViewer(widget({ audience: ['viewer'] }), baseViewer)).toBe(false);
    expect(widgetVisibleToViewer(widget({ config: { requiredPermissions: ['billing.manage'] } }), baseViewer)).toBe(false);
    expect(widgetVisibleToViewer(widget({ config: { industries: ['retail'] } }), baseViewer)).toBe(false);
    expect(widgetVisibleToViewer(widget({ config: { requiredFeature: 'sso' } }), baseViewer)).toBe(false);
    expect(widgetVisibleToViewer(widget({ visible: false }), baseViewer)).toBe(false);
  });

  it('does not allow published configuration to bypass a widget intrinsic data permission', () => {
    const limitedViewer = { ...baseViewer, permissions: ['workspace.view', 'conversations.view'] };
    expect(widgetVisibleToViewer(widget({ type: 'lead-summary', audience: [], config: {} }), limitedViewer)).toBe(false);
    expect(widgetVisibleToViewer(widget({ type: 'leads-chart', config: { requiredPermissions: [] } }), limitedViewer)).toBe(false);
    expect(widgetVisibleToViewer(widget({ type: 'inbox-attention', config: {} }), limitedViewer)).toBe(true);
  });

  it('hides mixed KPI cards when any underlying data capability is unavailable', () => {
    expect(widgetVisibleToViewer(widget({ type: 'kpi-cards', config: {} }), baseViewer)).toBe(false);
    const authorizedViewer = {
      ...baseViewer,
      permissions: [...baseViewer.permissions, 'agents.view'],
    };
    expect(widgetVisibleToViewer(widget({ type: 'kpi-cards', config: {} }), authorizedViewer)).toBe(true);
  });

  it('requires every metric source for multi-source conversation and usage widgets', () => {
    expect(widgetVisibleToViewer(widget({ type: 'conversation-summary' }), { ...baseViewer, permissions: ['conversations.view'] })).toBe(false);
    expect(widgetVisibleToViewer(widget({ type: 'conversation-summary' }), { ...baseViewer, permissions: ['analytics.view'] })).toBe(false);
    expect(widgetVisibleToViewer(widget({ type: 'conversation-summary' }), { ...baseViewer, permissions: ['conversations.view', 'analytics.view'] })).toBe(true);
    expect(widgetVisibleToViewer(widget({ type: 'usage' }), { ...baseViewer, permissions: ['workspace.view'] })).toBe(false);
    expect(widgetVisibleToViewer(widget({ type: 'usage' }), { ...baseViewer, permissions: ['agents.view'] })).toBe(false);
    expect(widgetVisibleToViewer(widget({ type: 'usage' }), { ...baseViewer, permissions: ['agents.view', 'analytics.view'] })).toBe(true);
  });

  it('requires the relevant backend capability for each data-bearing widget', () => {
    const cases: Array<[string, string]> = [
      ['conversation-chart', 'analytics.view'],
      ['agent-activity', 'agents.view'],
      ['channel-health', 'channels.view'],
      ['crm-status', 'crm.view'],
      ['education-summary', 'education.view'],
    ];
    for (const [type, permission] of cases) {
      expect(widgetVisibleToViewer(widget({ type, config: {} }), { ...baseViewer, permissions: [] })).toBe(false);
      expect(widgetVisibleToViewer(widget({ type, config: {} }), { ...baseViewer, permissions: [permission] })).toBe(true);
    }
  });
});

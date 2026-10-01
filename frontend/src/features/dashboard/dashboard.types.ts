import type { DashboardAppearance, DashboardSettings, DashboardWidget } from '@/features/workspace/settings/workspaceSettings.api';
import type { Agent, AnalyticsSummary, Conversation, Lead } from '@/types';

export type WorkspaceDashboardRuntime = {
  dashboard: DashboardSettings;
  appearance: DashboardAppearance;
  industry: string;
  country: string;
  enabledFeatures: string[];
};

export type DashboardData = {
  agents: Agent[];
  conversations: Conversation[];
  openConversations: Conversation[];
  leads: Lead[];
  analytics: AnalyticsSummary | null | undefined;
  loading: boolean;
};

export type DashboardViewerContext = {
  role: string;
  permissions: string[];
  industry: string;
  country: string;
  enabledFeatures: string[];
};

export type DashboardWidgetRendererProps = {
  widget: DashboardWidget;
  data: DashboardData;
};

// A workspace administrator may customize audience/configuration, but cannot
// grant a widget access to data the current viewer is not authorized to see.
// Keep these capabilities in sync with the backend's WORKSPACE_PERMISSIONS.
const WIDGET_PERMISSIONS: Readonly<Record<string, readonly string[]>> = {
  'conversation-summary': ['conversations.view', 'analytics.view'],
  'conversation-chart': ['analytics.view'],
  'inbox-attention': ['conversations.view'],
  'lead-summary': ['leads.view'],
  'leads-chart': ['leads.view'],
  'agent-activity': ['agents.view'],
  'channel-health': ['channels.view'],
  'crm-status': ['crm.view'],
  'education-summary': ['education.view'],
  'usage': ['agents.view', 'analytics.view'],
  'kpi-cards': ['agents.view', 'analytics.view', 'conversations.view', 'leads.view'],
};

export function widgetVisibleToViewer(widget: DashboardWidget, viewer: DashboardViewerContext): boolean {
  if (!widget.visible) return false;
  if (widget.audience.length > 0 && !widget.audience.includes(viewer.role)) return false;
  if ((WIDGET_PERMISSIONS[widget.type] ?? []).some((permission) => !viewer.permissions.includes(permission))) return false;
  const requiredPermissions = Array.isArray(widget.config.requiredPermissions)
    ? widget.config.requiredPermissions.filter((value): value is string => typeof value === 'string')
    : [];
  if (requiredPermissions.some((permission) => !viewer.permissions.includes(permission))) return false;
  const industries = Array.isArray(widget.config.industries)
    ? widget.config.industries.filter((value): value is string => typeof value === 'string').map((value) => value.toLowerCase())
    : [];
  if (industries.length > 0 && !industries.includes(viewer.industry.toLowerCase())) return false;
  const feature = typeof widget.config.requiredFeature === 'string' ? widget.config.requiredFeature : '';
  if (feature && !viewer.enabledFeatures.includes(feature)) return false;
  return true;
}

import { Inbox } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useAuth, useWorkspace } from '@/components/providers';
import { Badge, EmptyState } from '@/components/ui';
import type { ExtendedBranding } from '@/features/workspace/settings/workspaceSettings.api';
import { api } from '@/lib/api';
import { useApi } from '@/lib/use-api';
import { DashboardGrid } from './DashboardGrid';
import { loadWorkspaceDashboardRuntime } from './dashboard.api';
import type { DashboardData, WorkspaceDashboardRuntime } from './dashboard.types';
import { widgetVisibleToViewer } from './dashboard.types';
import { DashboardWidgetRenderer } from './widgets/DashboardWidgetRenderer';
import './dashboard.css';

export function DashboardPage({ brand }: { brand: ExtendedBranding }) {
  const { activeWorkspace } = useWorkspace();
  // Remount every dashboard query together on workspace changes. The generic
  // useApi hook retains its previous response while refetching, so a dependency
  // change alone could briefly show another workspace's conversation/lead data.
  return <WorkspaceDashboardContent key={activeWorkspace?.id ?? 'no-workspace'} brand={brand} />;
}

function WorkspaceDashboardContent({ brand }: { brand: ExtendedBranding }) {
  const { session } = useAuth();
  const { activeWorkspace } = useWorkspace();
  const agents = useApi(() => api.agents.list());
  const conversations = useApi(() => api.conversations.list());
  const leads = useApi(() => api.leads.list());
  const analytics = useApi(() => api.analytics.summary(7));
  const [runtime, setRuntime] = useState<WorkspaceDashboardRuntime | null>(null);
  const [runtimeError, setRuntimeError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    void loadWorkspaceDashboardRuntime(controller.signal).then((value) => {
      if (controller.signal.aborted) return;
      setRuntime(value);
      setRuntimeError('');
    }).catch((reason: unknown) => {
      if (controller.signal.aborted || (reason instanceof DOMException && reason.name === 'AbortError')) return;
      setRuntimeError(reason instanceof Error ? reason.message : 'Dashboard profile context is unavailable');
    });
    return () => controller.abort();
  }, [activeWorkspace?.id]);

  const dashboard = runtime?.dashboard ?? brand.dashboard;
  const viewer = useMemo(() => ({
    role: activeWorkspace?.role ?? '',
    permissions: activeWorkspace?.permissions ?? [],
    industry: runtime?.industry ?? '',
    country: runtime?.country ?? '',
    enabledFeatures: runtime?.enabledFeatures ?? [],
  }), [activeWorkspace?.permissions, activeWorkspace?.role, runtime]);
  const widgets = useMemo(() => [...dashboard.widgets]
    .filter((widget) => widgetVisibleToViewer(widget, viewer))
    .sort((left, right) => {
      const leftPinned = left.config.pinned === true ? 0 : 1;
      const rightPinned = right.config.pinned === true ? 0 : 1;
      return leftPinned - rightPinned || left.y - right.y || left.x - right.x;
    }), [dashboard.widgets, viewer]);
  const conversationItems = conversations.data?.items ?? [];
  const data: DashboardData = {
    agents: agents.data ?? [],
    conversations: conversationItems,
    openConversations: conversationItems.filter((item) => item.state !== 'resolved'),
    leads: leads.data?.items ?? [],
    analytics: analytics.data,
    loading: agents.loading || conversations.loading || leads.loading || analytics.loading,
  };

  return <div className="page workspace-configured-dashboard">
    <div className="workspace-configured-dashboard__heading">
      <div><span className="page-kicker">{brand.identity.companyName || activeWorkspace?.name || 'Workspace'}</span><h2>Welcome back, {session?.user.name?.split(/\s+/)[0] || 'there'}</h2><p>{dashboard.landingScreen === 'overview' ? 'Your published workspace dashboard.' : `Landing view: ${dashboard.landingScreen}`}</p></div>
      <Badge tone="brand">Layout v{dashboard.layoutVersion}</Badge>
    </div>
    {runtimeError ? <p role="alert">{runtimeError}. Showing the published layout with the access context already available in this session.</p> : null}
    <DashboardGrid widgets={widgets} renderWidget={(widget) => <DashboardWidgetRenderer widget={widget} data={data} />} />
    {widgets.length === 0 ? <EmptyState icon={Inbox} title="No dashboard widgets are available" description="A workspace administrator can publish widgets in Workspace settings → White label → Dashboard." /> : null}
  </div>;
}

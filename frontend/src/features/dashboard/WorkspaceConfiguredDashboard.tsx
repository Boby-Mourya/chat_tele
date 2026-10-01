import type { ExtendedBranding } from '@/features/workspace/settings/workspaceSettings.api';
import { DashboardPage } from './DashboardPage';

/** Compatibility entry point retained for existing Overview imports. */
export function WorkspaceConfiguredDashboard({ brand }: { brand: ExtendedBranding }) {
  return <DashboardPage brand={brand} />;
}

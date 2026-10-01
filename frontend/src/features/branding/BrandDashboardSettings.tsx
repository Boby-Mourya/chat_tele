import { DashboardEditor } from '@/features/dashboard/editor/DashboardEditor';
import type { DashboardSettings } from '@/features/workspace/settings/workspaceSettings.api';

/** Branding compatibility wrapper; dashboard editing is owned by the dashboard feature. */
export function BrandDashboardSettings({ value, onChange }: { value: DashboardSettings; onChange: (value: DashboardSettings) => void }) {
  return <DashboardEditor value={value} onChange={onChange} />;
}

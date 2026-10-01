/** Platform control-plane feature boundary. */
export { PlatformAdminPage } from '@/pages/PlatformAdminPage';
export { platformAdminApi } from '@/lib/platform-admin-api';
export type {
  PlatformOverview,
  PlatformTenantDetail,
  PlatformTenantSummary,
  PlatformTenantUser,
  PlatformEntitlement,
  PlatformConfiguration,
  PlatformAdminPermissions,
  PlatformOperator,
} from '@/lib/platform-admin-api';

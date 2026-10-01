import { CRMOneClickPanel } from '@/components/CRMOneClickPanel';
import { useAuth } from '@/components/providers';
import { leadCrmApi } from '@/lib/lead-crm-api';
import { useApi } from '@/lib/use-api';
import { IntegrationsPage } from '@/pages/IntegrationsPage';

/**
 * Adds the one-click CRM activation and live-certification workflow above the
 * existing provider-neutral integration administration page. The underlying
 * IntegrationsPage remains unchanged so its advanced channel, mapping, retry,
 * dead-letter and health controls continue to be available.
 */
export function CRMIntegrationsPage() {
  const crmConnections = useApi(() => leadCrmApi.connections());
  const { session } = useAuth();
  const canManage = session?.user.role === 'owner' || session?.user.role === 'admin';

  return <>
    <div className="page integrations-page">
      <CRMOneClickPanel
        connections={crmConnections.data ?? []}
        canManage={canManage}
        onConnectionsChanged={crmConnections.reload}
      />
    </div>
    <IntegrationsPage />
  </>;
}

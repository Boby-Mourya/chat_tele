import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock3,
  Code2,
  Database,
  GitBranch,
  MessageSquare,
  PlugZap,
  RefreshCw,
  Search,
  Send,
  UserRound,
  type LucideIcon,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Badge, Button, Card, EmptyState, PageLoader } from '@/components/ui';
import {
  crmWorkflowApi,
  type CRMWorkflow,
  type CRMWorkflowJourney,
  type CRMWorkflowJourneyStage,
  type CRMWorkflowStageStatus,
} from '@/lib/crm-workflow-api';
import { relativeTime } from '@/lib/format';
import '@/pages/CRMWorkflowPage.css';

interface PipelineStep {
  id: string;
  label: string;
  description: string;
  backend: string;
  frontend: string;
  icon: LucideIcon;
}

const pipelineSteps: PipelineStep[] = [
  {
    id: 'conversation',
    label: '1. Conversation captured',
    description: 'Verified channel events create or continue the workspace-scoped conversation.',
    backend: 'Channel webhook → normalized event → Conversation and Message',
    frontend: 'Conversations inbox',
    icon: MessageSquare,
  },
  {
    id: 'resolution',
    label: '2. Resolve and qualify',
    description: 'A Lead Generation Agent preserves the conversation and resolves it idempotently.',
    backend: 'conversation_resolution_service.resolve()',
    frontend: 'Conversation Resolve action',
    icon: CheckCircle2,
  },
  {
    id: 'lead',
    label: '3. Local Lead created',
    description: 'One Lead and LeadProfile store identity, source, campaign, score, and consent.',
    backend: 'Lead + LeadProfile + LeadActivityEvent',
    frontend: 'Leads list and Lead CRM detail',
    icon: UserRound,
  },
  {
    id: 'routing',
    label: '4. Durable CRM routing',
    description: 'The outbox event is consumed and workspace routes select eligible connections.',
    backend: 'lead.crm.sync.requested.v1 → WorkspaceCRMRouteService',
    frontend: 'CRM routing and auto-sync settings',
    icon: GitBranch,
  },
  {
    id: 'mapping',
    label: '5. Field mapping',
    description: 'Canonical Lead values are transformed into the provider Leads object.',
    backend: 'CRMFieldMapping + frozen delivery payload',
    frontend: 'CRM mapping editor',
    icon: Code2,
  },
  {
    id: 'delivery',
    label: '6. Provider upsert',
    description: 'A durable, idempotent delivery performs create, update, or upsert.',
    backend: 'crm_delivery_worker + provider connector',
    frontend: 'Delivery status and write attempts',
    icon: Send,
  },
  {
    id: 'acknowledgement',
    label: '7. Provider acknowledgement',
    description: 'The external record ID proves that the provider accepted the write.',
    backend: 'ACK state + CRMExternalReference',
    frontend: 'External CRM ID and acknowledgement time',
    icon: PlugZap,
  },
  {
    id: 'verification',
    label: '8. Read-back or recovery',
    description: 'Verification reads the provider record without resending an acknowledged write.',
    backend: 'reconciliation, retry policy, dead letter, replay, audit',
    frontend: 'Verification proof, retry, DLQ replay, health and audit',
    icon: Search,
  },
];

function readinessTone(status: CRMWorkflowStageStatus): 'success' | 'warning' | 'danger' {
  if (status === 'ready') return 'success';
  if (status === 'warning') return 'warning';
  return 'danger';
}

function journeyTone(
  stage: CRMWorkflowJourneyStage,
): 'success' | 'warning' | 'danger' | 'brand' | 'neutral' | 'purple' {
  if (stage === 'verified') return 'success';
  if (stage === 'dead_letter') return 'danger';
  if (stage === 'attention_required') return 'warning';
  if (stage === 'provider_acknowledged' || stage === 'verifying') return 'purple';
  if (stage === 'in_progress' || stage === 'awaiting_routing') return 'brand';
  return 'neutral';
}

function statusLabel(value: string): string {
  return value.replaceAll('_', ' ');
}

function journeyError(journey: CRMWorkflowJourney): string | null {
  const delivery = journey.delivery;
  if (!delivery) return null;
  return delivery.verificationErrorMessage
    ?? delivery.lastErrorMessage
    ?? delivery.verificationErrorCode
    ?? delivery.lastErrorCode
    ?? null;
}

export function CRMWorkflowPage() {
  const [workflow, setWorkflow] = useState<CRMWorkflow | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async (refresh = false) => {
    if (refresh) setRefreshing(true);
    else setLoading(true);
    setError('');
    try {
      setWorkflow(await crmWorkflowApi.get(50));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The CRM workflow could not be loaded.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    void crmWorkflowApi.get(50)
      .then((value) => { if (active) setWorkflow(value); })
      .catch((reason) => {
        if (active) setError(reason instanceof Error ? reason.message : 'The CRM workflow could not be loaded.');
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const visibleStatuses = useMemo(
    () => Object.entries(workflow?.counts.byStatus ?? {}).filter(([, count]) => count > 0),
    [workflow?.counts.byStatus],
  );

  if (loading && !workflow) return <PageLoader />;
  if (!workflow) {
    return <div className="page crm-workflow-page">
      <Card>
        <EmptyState
          icon={AlertTriangle}
          title="CRM workflow is unavailable"
          description={error || 'The workspace workflow could not be loaded.'}
          action={<Button icon={RefreshCw} onClick={() => void load()}>Try again</Button>}
        />
      </Card>
    </div>;
  }

  const counts = workflow.counts;
  return <div className="page crm-workflow-page">
    <div className="page-heading page-heading--split">
      <div>
        <span className="page-kicker">Lead → CRM operations</span>
        <h2>CRM full workflow</h2>
        <p>
          Follow each workspace Lead from conversation resolution through routing, provider
          acknowledgement, read-back verification, and recovery.
        </p>
      </div>
      <div className="crm-workflow-page__heading-actions">
        <Badge tone={workflow.readiness.ready ? 'success' : 'warning'}>
          {workflow.readiness.ready ? <CheckCircle2 /> : <AlertTriangle />}
          {workflow.readiness.ready ? 'Automatic flow ready' : 'Setup requires attention'}
        </Badge>
        <Button
          variant="secondary"
          icon={RefreshCw}
          disabled={refreshing}
          onClick={() => void load(true)}
        >
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </Button>
        <Link className="button button--primary button--md" to="/integrations">
          CRM setup <ArrowRight />
        </Link>
      </div>
    </div>

    {error ? <div className="form-error" role="alert">{error}</div> : null}

    <section className="crm-workflow-metrics" aria-label="CRM workflow metrics">
      <Card><span><MessageSquare /></span><div><strong>{counts.resolvedConversations}</strong><small>Resolved conversations</small></div></Card>
      <Card><span><Database /></span><div><strong>{counts.localLeads}</strong><small>Local Leads</small></div></Card>
      <Card><span><Clock3 /></span><div><strong>{counts.inFlightDeliveries}</strong><small>Deliveries in flight</small></div></Card>
      <Card><span><CheckCircle2 /></span><div><strong>{counts.verifiedDeliveries}</strong><small>CRM records verified</small></div></Card>
      <Card><span><AlertTriangle /></span><div><strong>{counts.attentionDeliveries}</strong><small>Need attention</small></div></Card>
    </section>

    <Card className="crm-workflow-readiness">
      <div className="crm-workflow-section-heading">
        <div><h3>Automatic workflow readiness</h3><p>Every required backend contract is checked in the active workspace.</p></div>
        <small>Generated {relativeTime(workflow.generatedAt)}</small>
      </div>
      <div className="crm-readiness-grid">
        {workflow.readiness.stages.map((stage) => <article key={stage.id} className={`crm-readiness-card crm-readiness-card--${stage.status}`}>
          <div>
            <Badge tone={readinessTone(stage.status)}>{statusLabel(stage.status)}</Badge>
            <h4>{stage.label}</h4>
          </div>
          <p>{stage.description}</p>
          <small>{stage.detail}</small>
          {stage.actionPath && stage.actionLabel ? <Link to={stage.actionPath}>{stage.actionLabel} <ArrowRight /></Link> : null}
        </article>)}
      </div>
    </Card>

    <Card className="crm-workflow-flow">
      <div className="crm-workflow-section-heading">
        <div><h3>End-to-end execution path</h3><p>The frontend actions and backend components used at every stage.</p></div>
      </div>
      <div className="crm-pipeline">
        {pipelineSteps.map((step, index) => {
          const Icon = step.icon;
          return <div key={step.id} className="crm-pipeline-step">
            <span className="crm-pipeline-step__icon"><Icon /></span>
            <div>
              <h4>{step.label}</h4>
              <p>{step.description}</p>
              <dl>
                <div><dt>Backend</dt><dd>{step.backend}</dd></div>
                <div><dt>Frontend</dt><dd>{step.frontend}</dd></div>
              </dl>
            </div>
            {index < pipelineSteps.length - 1 ? <ArrowRight className="crm-pipeline-step__arrow" /> : null}
          </div>;
        })}
      </div>
    </Card>

    <Card className="crm-workflow-connections">
      <div className="crm-workflow-section-heading">
        <div><h3>Workspace CRM connections</h3><p>Credentials are never returned; this view exposes configuration and health only.</p></div>
        <Link to="/integrations">Manage integrations <ArrowRight /></Link>
      </div>
      {workflow.connections.length ? <div className="crm-workflow-table-wrap">
        <table className="crm-workflow-table">
          <thead><tr><th>Connection</th><th>Health</th><th>Mapping</th><th>Routes</th><th>Auto-sync</th><th>Last activity</th></tr></thead>
          <tbody>{workflow.connections.map((connection) => <tr key={connection.id}>
            <td><strong>{connection.name}</strong><small>{connection.provider} · {connection.environment}</small></td>
            <td><Badge tone={connection.status === 'healthy' ? 'success' : connection.status === 'degraded' ? 'warning' : 'danger'}>{statusLabel(connection.status)}</Badge>{connection.lastError ? <small>{connection.lastError}</small> : null}</td>
            <td>{connection.mappingConfigured ? <><Badge tone="success">Configured</Badge><small>v{connection.mappingVersion ?? 1} · {connection.mappingStatus ?? 'configured'}</small></> : <Badge tone="danger">Missing</Badge>}</td>
            <td><strong>{connection.enabledRouteCount}</strong><small>enabled route{connection.enabledRouteCount === 1 ? '' : 's'}</small></td>
            <td><Badge tone={connection.autoSyncNewLeads ? 'success' : 'warning'}>{connection.autoSyncNewLeads ? 'New Leads on' : 'New Leads off'}</Badge><small>Updates {connection.autoSyncUpdates ? 'on' : 'off'}</small></td>
            <td>{connection.lastSuccessAt ? relativeTime(connection.lastSuccessAt) : connection.lastHealthAt ? relativeTime(connection.lastHealthAt) : 'No successful activity yet'}</td>
          </tr>)}</tbody>
        </table>
      </div> : <EmptyState icon={PlugZap} title="No CRM connected" description="Connect Zoho, HubSpot, Salesforce, Dynamics 365, Pipedrive, Freshsales, REST, or a webhook to move local Leads into an external CRM." action={<Link className="button button--primary button--md" to="/integrations">Connect CRM</Link>} />}
    </Card>

    <Card className="crm-workflow-statuses">
      <div className="crm-workflow-section-heading">
        <div><h3>Delivery state distribution</h3><p>Provider acknowledgement and read-back verification are measured separately.</p></div>
      </div>
      {visibleStatuses.length ? <div className="crm-status-grid">
        {visibleStatuses.map(([status, count]) => <div key={status}><strong>{count}</strong><span>{statusLabel(status)}</span></div>)}
      </div> : <EmptyState icon={Clock3} title="No CRM deliveries yet" description="Resolve a Lead Generation conversation or manually sync a local Lead to start the durable delivery workflow." />}
    </Card>

    <Card className="crm-workflow-journeys">
      <div className="crm-workflow-section-heading">
        <div><h3>Recent Lead journeys</h3><p>Latest delivery state for each local Lead in this workspace.</p></div>
        <Link to="/leads">Open Leads <ArrowRight /></Link>
      </div>
      {workflow.recentJourneys.length ? <div className="crm-workflow-table-wrap">
        <table className="crm-workflow-table crm-workflow-journey-table">
          <thead><tr><th>Lead source</th><th>Qualification</th><th>Current stage</th><th>Provider proof</th><th>Attempts</th><th>Next action</th></tr></thead>
          <tbody>{workflow.recentJourneys.map((journey) => {
            const delivery = journey.delivery;
            const currentError = journeyError(journey);
            return <tr key={journey.leadId}>
              <td>
                <strong>{journey.customerName || journey.email || journey.phone || 'Anonymous Lead'}</strong>
                <small>{journey.agentName} · {journey.sourceChannel ?? 'direct'}</small>
                <small>{journey.conversationPublicId ? `Conversation ${journey.conversationPublicId}` : 'Direct Lead capture'}</small>
              </td>
              <td>
                <Badge tone={journey.qualificationStatus === 'qualified' ? 'purple' : 'neutral'}>{statusLabel(journey.qualificationStatus ?? journey.lifecycleStatus)}</Badge>
                {journey.qualificationScore != null ? <small>Score {journey.qualificationScore}/100</small> : null}
              </td>
              <td>
                <Badge tone={journeyTone(journey.stage)}>{journey.stageLabel}</Badge>
                <small>{journey.stageDetail}</small>
                {currentError ? <small className="crm-workflow-error">{currentError}</small> : null}
              </td>
              <td>
                {delivery ? <>
                  <strong>{delivery.connectionName}</strong>
                  <small>{delivery.provider} · {statusLabel(delivery.status)}</small>
                  <small>External ID: {delivery.externalRecordId ?? 'not acknowledged'}</small>
                  <small>Verification: {statusLabel(delivery.verificationStatus)}</small>
                </> : <small>No delivery record</small>}
              </td>
              <td>
                {delivery ? <><strong>{delivery.attemptCount}</strong><small>write attempt{delivery.attemptCount === 1 ? '' : 's'}</small><small>{delivery.verificationAttemptCount} read-back check{delivery.verificationAttemptCount === 1 ? '' : 's'}</small></> : '—'}
              </td>
              <td>
                {journey.nextActionPath && journey.nextActionLabel ? <Link className="button button--secondary button--sm" to={journey.nextActionPath}>{journey.nextActionLabel}</Link> : <Badge tone="success">Complete</Badge>}
                <small>Updated {relativeTime(journey.updatedAt)}</small>
              </td>
            </tr>;
          })}</tbody>
        </table>
      </div> : <EmptyState icon={UserRound} title="No local Leads yet" description="A Lead Generation conversation creates its local Lead when an authorized user resolves it." action={<Link className="button button--secondary button--md" to="/conversations">Open conversations</Link>} />}
    </Card>
  </div>;
}

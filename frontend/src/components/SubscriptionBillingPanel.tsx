import { CreditCard, Sparkles } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { useAuth, useToast } from '@/components/providers';
import { Badge, Button, Card, Field, Modal } from '@/components/ui';
import {
  billingApi,
  type SubscriptionStatus,
  type TenantEntitlements,
  type TenantSubscription,
} from '@/lib/billing-api';
import type { WorkspaceSettings } from '@/lib/workspace-api';

const statusLabels: Record<SubscriptionStatus, string> = {
  trial: 'Trial',
  active: 'Active',
  past_due: 'Past due',
  suspended: 'Suspended',
  cancelled: 'Cancelled',
};

const checkoutPlans = [
  {
    id: 'professional',
    name: 'Professional',
    description: 'More agents, seats, conversations, tokens, channels and CRM access.',
  },
  {
    id: 'business',
    name: 'Business',
    description: 'Higher capacity, every channel, CRM, API and white-label capabilities.',
  },
] as const;

const planRank: Record<string, number> = {
  starter: 0,
  professional: 1,
  business: 2,
  enterprise: 3,
};

export function SubscriptionBillingPanel({ workspace }: { workspace: WorkspaceSettings }) {
  const { session } = useAuth();
  const { pushToast } = useToast();
  const [subscription, setSubscription] = useState<TenantSubscription | null>(null);
  const [entitlements, setEntitlements] = useState<TenantEntitlements | null>(null);
  const [error, setError] = useState('');
  const [manageOpen, setManageOpen] = useState(false);
  const [plansOpen, setPlansOpen] = useState(false);
  const [confirmation, setConfirmation] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    setError('');
    void Promise.all([
      billingApi.getSubscription(workspace.plan),
      billingApi.getEntitlements(workspace.plan),
    ])
      .then(([nextSubscription, nextEntitlements]) => {
        if (!active) return;
        setSubscription(nextSubscription);
        setEntitlements(nextEntitlements);
      })
      .catch((reason) => {
        if (!active) return;
        const message = reason instanceof Error ? reason.message : 'Billing information could not be loaded';
        setError(message);
        pushToast(message, 'error');
      });
    return () => { active = false; };
  }, [pushToast, workspace.id, workspace.plan]);

  const canManageBilling = Boolean(
    session?.user.role === 'owner'
    || session?.user.role === 'admin'
    || session?.user.role === 'billing_admin'
    || workspace.permissions?.includes('*')
    || workspace.permissions?.includes('billing.manage'),
  );
  const plan = subscription?.plan ?? entitlements?.plan ?? workspace.plan;
  const statusValue = subscription?.status ?? entitlements?.subscriptionStatus;
  const status = statusValue ? statusLabels[statusValue] : 'Loading';
  const period = subscription?.status === 'cancelled'
    ? subscription.cancelledAt
      ? `Cancelled ${formatDate(subscription.cancelledAt)}. Existing tenant data is preserved.`
      : 'Cancelled. Existing tenant data is preserved.'
    : subscription?.cancelAtPeriodEnd && subscription.currentPeriodEnd
      ? `Cancellation is scheduled for ${formatDate(subscription.currentPeriodEnd)}.`
      : subscription?.currentPeriodEnd
        ? `Current period ends ${formatDate(subscription.currentPeriodEnd)}`
        : subscription?.trialEndsAt
          ? `Trial ends ${formatDate(subscription.trialEndsAt)}`
          : 'Billing period will appear when a payment provider is connected.';

  const limits = entitlements?.limits;
  const usage = entitlements?.usage;
  const memberUsage = usage ? usage.members + usage.pendingMemberSeats : 0;
  const currentRank = planRank[plan.toLowerCase()] ?? Number.MAX_SAFE_INTEGER;
  const availableCheckoutPlans = checkoutPlans.filter((candidate) => (planRank[candidate.id] ?? 0) > currentRank);

  const applySubscription = (next: TenantSubscription) => {
    setSubscription(next);
    setEntitlements((current) => current ? {
      ...current,
      plan: next.plan,
      subscriptionStatus: next.status,
    } : current);
  };

  const cancelSubscription = async () => {
    if (confirmation !== 'CANCEL') return;
    setSaving(true);
    try {
      const next = await billingApi.cancelSubscription();
      applySubscription(next);
      setConfirmation('');
      setManageOpen(false);
      pushToast(
        next.cancelAtPeriodEnd
          ? 'Subscription cancellation scheduled for the end of the current period'
          : 'Subscription cancelled. Existing tenant data has been preserved',
        next.cancelAtPeriodEnd ? 'info' : 'success',
      );
    } catch (reason) {
      pushToast(reason instanceof Error ? reason.message : 'Subscription could not be cancelled', 'error');
    } finally {
      setSaving(false);
    }
  };

  const reactivateSubscription = async () => {
    setSaving(true);
    try {
      const next = await billingApi.reactivateSubscription();
      applySubscription(next);
      setManageOpen(false);
      pushToast(next.status === 'active' ? 'Subscription reactivated' : 'Scheduled cancellation removed');
    } catch (reason) {
      pushToast(reason instanceof Error ? reason.message : 'Subscription could not be reactivated', 'error');
    } finally {
      setSaving(false);
    }
  };

  const startCheckout = async (nextPlan: string) => {
    if (!canManageBilling) return;
    setSaving(true);
    try {
      const redirect = await billingApi.createCheckout(nextPlan);
      window.location.assign(redirect.url);
    } catch (reason) {
      pushToast(reason instanceof Error ? reason.message : 'Secure checkout could not be opened', 'error');
      setSaving(false);
    }
  };

  const openBillingPortal = async () => {
    if (!canManageBilling) return;
    setSaving(true);
    try {
      const redirect = await billingApi.createPortal();
      window.location.assign(redirect.url);
    } catch (reason) {
      pushToast(reason instanceof Error ? reason.message : 'Billing portal could not be opened', 'error');
      setSaving(false);
    }
  };

  return <>
    <Card className="workspace-panel">
      <PanelHeading
        title="Plan & billing"
        description="Review your tenant subscription status, plan features, and measured usage."
        action={<Badge tone="brand">{formatPlan(plan)} · {status}</Badge>}
      />
      <div className="workspace-panel__body">
        {error ? <div className="workspace-empty-row"><CreditCard /><span><strong>Billing access is unavailable</strong><small>{error}</small></span></div> : <div className="workspace-empty-row"><CreditCard /><span><strong>{formatPlan(plan)} subscription</strong><small>{period}</small><small>Provider: {subscription?.provider ? formatPlan(subscription.provider) : 'Not connected'}</small>{subscription?.cancelAtPeriodEnd ? <small>Existing workspace, agent, knowledge, Lead and CRM data stays available while cancellation is pending.</small> : null}{subscription?.status === 'cancelled' ? <small>New resource creation and other plan-gated writes are blocked until the subscription is reactivated.</small> : null}{entitlements ? <small>CRM: {entitlements.features.crm ? 'Included' : 'Upgrade required'} · API: {entitlements.features.api ? 'Included' : 'Upgrade required'} · White-label: {entitlements.features.whiteLabel ? 'Included' : 'Upgrade required'}</small> : null}</span></div>}
      </div>
      <div className="workspace-plan-grid">
        <Usage label="Conversations this month" used={usage?.conversationsMonthly ?? 0} limit={limits?.conversationsMonthly} />
        <Usage label="AI agents" used={usage?.agents ?? 0} limit={limits?.agents} />
        <Usage label="Team seats" used={memberUsage} limit={limits?.members} suffix={usage?.pendingMemberSeats ? ` (${usage.pendingMemberSeats} pending)` : undefined} />
        <Usage label="AI tokens this month" used={usage?.tokensMonthly ?? 0} limit={limits?.tokensMonthly} />
        <Usage label="Knowledge storage" used={usage?.storageBytes ?? 0} limit={limits?.storageBytes} bytes />
      </div>
      <div className="workspace-panel__actions workspace-panel__actions--border">
        {canManageBilling ? <Button variant="secondary" onClick={() => { setConfirmation(''); setManageOpen(true); }} disabled={!subscription || saving}>Manage billing</Button> : null}
        <Button onClick={() => setPlansOpen(true)}>Compare plans</Button>
      </div>
    </Card>
    <Card className="workspace-upgrade-card"><Sparkles /><div><strong>Need more capacity?</strong><p>Upgrade limits without changing your agents, knowledge, integrations, or existing workspace data.</p></div><Button variant="secondary" onClick={() => setPlansOpen(true)}>View plans</Button></Card>

    <Modal
      open={manageOpen}
      onClose={() => { if (!saving) { setManageOpen(false); setConfirmation(''); } }}
      title="Manage subscription"
      description="Subscription offboarding changes billing state only. Existing tenant data is never deleted by this action."
      size="sm"
      closeDisabled={saving}
      footer={subscription?.provider === 'stripe' ? <>
        <Button variant="secondary" onClick={() => setManageOpen(false)} disabled={saving}>Close</Button>
        <Button onClick={() => void openBillingPortal()} disabled={saving}>{saving ? 'Opening…' : 'Open billing portal'}</Button>
      </> : subscription?.provider ? <Button variant="secondary" onClick={() => setManageOpen(false)} disabled={saving}>Close</Button> : subscription?.cancelAtPeriodEnd || subscription?.status === 'cancelled' ? <>
        <Button variant="secondary" onClick={() => setManageOpen(false)} disabled={saving}>Close</Button>
        <Button onClick={() => void reactivateSubscription()} disabled={saving}>{subscription.cancelAtPeriodEnd ? 'Keep subscription' : 'Reactivate subscription'}</Button>
      </> : <>
        <Button variant="secondary" onClick={() => { setManageOpen(false); setConfirmation(''); }} disabled={saving}>Back</Button>
        <Button variant="danger" onClick={() => void cancelSubscription()} disabled={saving || confirmation !== 'CANCEL'}>{saving ? 'Cancelling…' : 'Confirm cancellation'}</Button>
      </>}
    >
      {subscription?.provider === 'stripe' ? <div className="workspace-empty-row"><CreditCard /><span><strong>Stripe-managed subscription</strong><small>Plan changes, payment methods, invoices and cancellation are managed in Stripe's secure customer portal. Signed Stripe webhooks keep Northstar subscription status and entitlements synchronized.</small></span></div> : subscription?.provider ? <div className="workspace-empty-row"><CreditCard /><span><strong>Provider-managed subscription</strong><small>{formatPlan(subscription.provider)} billing must be cancelled through its provider workflow. Northstar will not mark it cancelled locally without provider confirmation.</small></span></div> : subscription?.cancelAtPeriodEnd ? <div className="workspace-empty-row"><CreditCard /><span><strong>Cancellation is scheduled</strong><small>{subscription.currentPeriodEnd ? `Access remains on the current subscription until ${formatDate(subscription.currentPeriodEnd)}.` : 'Cancellation is pending.'}</small><small>Choose Keep subscription to remove the scheduled offboarding.</small></span></div> : subscription?.status === 'cancelled' ? <div className="workspace-empty-row"><CreditCard /><span><strong>Subscription is cancelled</strong><small>Your existing tenant, workspaces, agents, knowledge, Leads and CRM records are preserved.</small><small>Reactivate to restore plan-gated creation and write capabilities.</small></span></div> : <div style={{ display: 'grid', gap: 18 }}>
        <div className="workspace-empty-row"><CreditCard /><span><strong>{subscription?.currentPeriodEnd ? 'Schedule cancellation' : 'Cancel subscription now'}</strong><small>{subscription?.currentPeriodEnd ? `The subscription will stay active until ${formatDate(subscription.currentPeriodEnd)}. Existing data will be preserved.` : 'No external billing period is connected, so cancellation takes effect immediately. Existing data will be preserved.'}</small><small>After cancellation, new resource creation and other plan-gated writes are blocked until reactivation.</small></span></div>
        <Field label="Type CANCEL to confirm" hint="This does not delete tenant or workspace data.">
          <input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoComplete="off" disabled={saving} />
        </Field>
      </div>}
    </Modal>

    <Modal
      open={plansOpen}
      onClose={() => { if (!saving) setPlansOpen(false); }}
      title="Compare plans"
      description={subscription?.provider === 'stripe'
        ? 'Your subscription is already provider-managed. Use the secure billing portal for plan changes.'
        : 'Choose a higher plan to continue in Stripe hosted checkout. Northstar changes entitlements only after a signed provider webhook confirms the subscription.'}
      size="md"
      closeDisabled={saving}
      footer={<Button variant="secondary" onClick={() => setPlansOpen(false)} disabled={saving}>Close</Button>}
    >
      {subscription?.provider === 'stripe' ? <div className="workspace-empty-row"><CreditCard /><span><strong>{formatPlan(plan)} is managed by Stripe</strong><small>Use the customer portal to change plans, payment methods or cancellation settings.</small>{canManageBilling ? <Button onClick={() => void openBillingPortal()} disabled={saving}>{saving ? 'Opening…' : 'Open billing portal'}</Button> : null}</span></div> : availableCheckoutPlans.length ? <div style={{ display: 'grid', gap: 14 }}>{availableCheckoutPlans.map((candidate) => <Card key={candidate.id}><div className="workspace-empty-row"><Sparkles /><span><strong>{candidate.name}</strong><small>{candidate.description}</small>{canManageBilling ? <Button onClick={() => void startCheckout(candidate.id)} disabled={saving}>{saving ? 'Opening secure checkout…' : `Choose ${candidate.name}`}</Button> : <small>Ask a tenant billing administrator to upgrade this plan.</small>}</span></div></Card>)}</div> : <div className="workspace-empty-row"><Sparkles /><span><strong>No self-service upgrade is available above {formatPlan(plan)}</strong><small>Enterprise and custom contracts can continue to use the existing tenant plan without changing any workspace data.</small></span></div>}
    </Modal>
  </>;
}

function formatPlan(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString();
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${(value / 1024 ** 3).toFixed(1)} GB`;
}

function PanelHeading({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <div className="workspace-panel__heading"><span><CreditCard /></span><div><h3>{title}</h3><p>{description}</p></div>{action}</div>;
}

function Usage({ label, used, limit, suffix, bytes = false }: { label: string; used: number; limit: number | null | undefined; suffix?: string; bytes?: boolean }) {
  const value = bytes ? formatBytes(used) : used.toLocaleString();
  const maximum = limit == null ? 'Unlimited' : bytes ? formatBytes(limit) : limit.toLocaleString();
  const width = limit == null || limit <= 0 ? '0%' : `${Math.min(100, Math.round((used / limit) * 100))}%`;
  return <div><small>{label}</small><strong>{value} / {maximum}{suffix ?? ''}</strong><span><i style={{ width }} /></span></div>;
}

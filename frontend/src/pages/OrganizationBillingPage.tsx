import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '@/components/providers';
import { Button, Field, Modal } from '@/components/ui';
import { billingApi, type TenantEntitlements, type TenantSubscription } from '@/lib/billing-api';
import '@/components/workspace-setup.css';

/** Independent recovery route: no fabricated workspace or bootstrap is needed. */
export function OrganizationBillingPage() {
  const { session, logout } = useAuth();
  const [state, setState] = useState<{ token: string; subscription: TenantSubscription; entitlements: TenantEntitlements } | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [confirmation, setConfirmation] = useState('');
  const currentToken = useRef(session?.accessToken);
  currentToken.current = session?.accessToken;
  useEffect(() => {
    let current = true;
    const token = session?.accessToken ?? '';
    setError(''); setState(null); setCancelOpen(false); setConfirmation('');
    void Promise.all([billingApi.getSubscription(), billingApi.getEntitlements()]).then(([subscription, entitlements]) => {
      if (current && currentToken.current === token) setState({ token, subscription, entitlements });
    }).catch((reason: unknown) => {
      if (current && currentToken.current === token) setError(reason instanceof Error ? reason.message : 'Billing could not be loaded');
    });
    return () => { current = false; };
  }, [session?.accessToken, attempt]);
  const data = state?.token === session?.accessToken ? state : null;
  const canManage = !!session && ['owner', 'admin', 'billing_admin'].includes(session.user.role);
  async function act(action: () => Promise<unknown>) {
    if (busy || !canManage) return;
    const token = currentToken.current;
    setBusy(true); setError('');
    try { await action(); if (currentToken.current === token) { setCancelOpen(false); setAttempt((value) => value + 1); } }
    catch (reason) { if (currentToken.current === token) setError(reason instanceof Error ? reason.message : 'Billing action did not complete'); }
    finally { if (currentToken.current === token) setBusy(false); }
  }
  const limits = data?.entitlements.limits;
  const usage = data?.entitlements.usage;
  const subscription = data?.subscription;
  const rank: Record<string, number> = { free: 0, starter: 1, professional: 2, business: 3, enterprise: 4 };
  const upgradePlans = ['professional', 'business'].filter((plan) => subscription && (rank[plan] ?? -1) > (rank[subscription.plan] ?? Infinity));
  const count = (used: number, limit: number | null) => `${used.toLocaleString()} / ${limit === null ? 'Contract allowance' : limit.toLocaleString()}`;
  return <main className="setup-page"><h1>Organization billing</h1>
    <p>This account-level page remains available without access to an operational workspace. Billing authorization is checked by the server.</p>
    <div className="setup-actions"><Link to="/organizations">Switch organization</Link><Link to="/">Dashboard</Link><Button variant="secondary" onClick={() => void logout().catch(() => undefined)}>Sign out</Button></div>
    {error ? <p className="setup-error" role="alert">{error}</p> : null}
    {!data && !error ? <p role="status">Loading subscription and measured usage…</p> : null}
    {data && subscription && usage && limits ? <section>
      <h2>{subscription.plan} · {subscription.status.replaceAll('_', ' ')}</h2>
      <p>Organization ID: {subscription.tenantId}. Provider: {subscription.provider ?? 'No external provider'}.</p>
      <dl><dt>Workspaces</dt><dd>{count(usage.workspaces, limits.workspaces)}</dd>
        <dt>Staff seats, including pending reservations</dt><dd>{count(usage.members + usage.pendingMemberSeats, limits.members)}</dd>
        <dt>Agents</dt><dd>{count(usage.agents, limits.agents)}</dd>
        <dt>Monthly conversations</dt><dd>{count(usage.conversationsMonthly, limits.conversationsMonthly)}</dd>
        <dt>Monthly AI tokens</dt><dd>{count(usage.tokensMonthly, limits.tokensMonthly)}</dd>
        <dt>Knowledge storage, bytes</dt><dd>{count(usage.storageBytes, limits.storageBytes)}</dd></dl>
      {subscription.cancelAtPeriodEnd ? <p>Cancellation is scheduled for {subscription.currentPeriodEnd ? new Date(subscription.currentPeriodEnd).toLocaleString() : 'the end of the current period'}.</p> : null}
      {canManage ? <div className="setup-actions">
        {subscription.provider === 'stripe' ? <Button disabled={busy} onClick={() => void act(async () => { const value = await billingApi.createPortal(); window.location.assign(value.url); })}>Manage in billing portal</Button> : subscription.provider ? <p>Manage this subscription through its configured provider.</p> : <>
          {subscription.status === 'cancelled' || subscription.cancelAtPeriodEnd ? <Button disabled={busy} onClick={() => void act(() => billingApi.reactivateSubscription())}>Reactivate / keep subscription</Button>
            : <Button variant="danger" disabled={busy} onClick={() => setCancelOpen(true)}>Cancel subscription</Button>}
          {upgradePlans.map((plan) => <Button key={plan} disabled={busy} onClick={() => void act(async () => { const value = await billingApi.createCheckout(plan); window.location.assign(value.url); })}>Choose {plan}</Button>)}
        </>}
      </div> : <p>Your organization billing administrator manages changes.</p>}
    </section> : null}
    <div className="setup-actions"><Button disabled={busy} variant="secondary" onClick={() => setAttempt((value) => value + 1)}>Reload billing</Button></div>
    <Modal open={cancelOpen && !!data} title="Cancel organization subscription" closeDisabled={busy} onClose={() => { if (!busy) { setCancelOpen(false); setConfirmation(''); } }}
      footer={<Button variant="danger" disabled={busy || confirmation !== 'CANCEL'} onClick={() => void act(() => billingApi.cancelSubscription())}>Confirm cancellation</Button>}>
      <p>This changes the organization subscription, not just one workspace. Existing data is preserved. New plan-gated operations may be blocked. The server determines whether cancellation is immediate or at period end.</p>
      <Field label="Type CANCEL to confirm"><input autoComplete="off" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} disabled={busy} /></Field>
    </Modal>
  </main>;
}

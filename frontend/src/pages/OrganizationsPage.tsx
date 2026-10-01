import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '@/components/providers';
import { Button, Card } from '@/components/ui';
import { organizationApi, type OrganizationSummary } from '@/lib/organization-api';
import '@/components/workspace-setup.css';

/** Organization recovery does not depend on an operational workspace or its bootstrap. */
export function OrganizationsPage() {
  const { session, logout } = useAuth();
  const navigate = useNavigate();
  const [rows, setRows] = useState<OrganizationSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    const controller = new AbortController();
    setLoaded(false); setError(''); setRows([]); setCursor(null);
    void organizationApi.list(null, controller.signal).then((value) => {
      if (!controller.signal.aborted) { setRows(value.organizations); setCursor(value.nextCursor); setLoaded(true); }
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) { setError(reason instanceof Error ? reason.message : 'Organizations could not be loaded'); setLoaded(true); }
    });
    return () => controller.abort();
  }, [session?.accessToken, attempt]);
  async function more() {
    if (!cursor || busy) return;
    setBusy(true); setError('');
    try {
      const value = await organizationApi.list(cursor);
      if (mounted.current) { setRows((current) => [...new Map([...current, ...value.organizations].map((item) => [item.id, item])).values()]); setCursor(value.nextCursor); }
    } catch (reason) { if (mounted.current) setError(reason instanceof Error ? reason.message : 'More organizations could not be loaded'); }
    finally { if (mounted.current) setBusy(false); }
  }
  async function choose(id: string) {
    if (busy) return;
    setBusy(true); setError('');
    try { await organizationApi.select(id); navigate('/', { replace: true }); }
    catch (reason) { if (mounted.current) setError(reason instanceof Error ? reason.message : 'Organization could not be selected'); }
    finally { if (mounted.current) setBusy(false); }
  }
  return <main className="setup-page">
    <h1>Your organizations</h1><p>Choose an institution or business you already belong to. This does not create memberships or change your assigned permissions.</p>
    <p>Organization selection updates this browser’s sign-in context, including other tabs. Your other devices are not signed out.</p>
    {error ? <p className="setup-error" role="alert">{error}</p> : null}
    {!loaded ? <p role="status">Loading authorized organizations…</p> : !error && rows.length === 0 ? <p>You do not currently belong to an organization. Ask its administrator for an invitation.</p> : null}
    <div className="setup-grid">{rows.map((item) => <Card key={item.id} className="setup-resource">
      <h2>{item.name}</h2><p>Your organization role: {item.role.replaceAll('_', ' ')}{item.selected ? ' · current organization' : ''}</p>
      <Button disabled={busy} onClick={() => void choose(item.id)}>{busy ? 'Please wait…' : item.selected ? 'Reopen this organization' : 'Open organization'}</Button>
    </Card>)}</div>
    <div className="setup-actions">
      {cursor ? <Button disabled={busy} onClick={() => void more()}>Load more</Button> : null}
      {error ? <Button disabled={busy} onClick={() => setAttempt((value) => value + 1)}>Retry list</Button> : null}
      <Link to="/">Dashboard</Link><Link to="/organization/billing">Organization billing</Link>
      <Button variant="secondary" disabled={busy} onClick={() => void logout().catch(() => undefined)}>Sign out</Button>
    </div>
  </main>;
}

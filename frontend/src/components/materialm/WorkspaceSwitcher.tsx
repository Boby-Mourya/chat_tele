import { Building2, Check, ChevronDown, Plus, Settings2, X } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { useAuth, useToast, useWorkspace } from '@/components/providers';

/** Uses the existing WorkspaceProvider: no duplicate local workspace database. */
export function MaterialmWorkspaceSwitcher() {
  const { workspaces, activeWorkspace, loading, selectWorkspace, createWorkspace } = useWorkspace();
  const { session } = useAuth();
  const { pushToast } = useToast();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [saving, setSaving] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !root.current?.contains(event.target)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setOpen(false); trigger.current?.focus(); }
    };
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape); };
  }, [open]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const cleaned = slug.trim().toLowerCase().replace(/[^a-z0-9-]/g, '');
    if (saving || name.trim().length < 2 || cleaned.length < 2) return;
    setSaving(true);
    try {
      await createWorkspace({ name: name.trim(), slug: cleaned });
      setCreating(false); setOpen(false); setName(''); setSlug('');
      pushToast('Workspace created');
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Workspace could not be created', 'error');
    } finally { setSaving(false); }
  }

  return <div className="workspace-switcher" ref={root}>
    <button ref={trigger} className="workspace-switcher__button" type="button" onClick={() => setOpen(!open)} aria-label={`Workspace ${loading ? 'Loading' : activeWorkspace?.name ?? 'Select workspace'}`} aria-expanded={open} aria-controls="mm-workspace-popover">
      <span className="workspace-switcher__mark"><Building2 aria-hidden="true" /></span>
      <span><small>Workspace</small><strong>{loading ? 'Loading…' : activeWorkspace?.name ?? 'Select workspace'}</strong></span><ChevronDown aria-hidden="true" />
    </button>
    {open ? <div id="mm-workspace-popover" className="workspace-switcher__popover">
      <div className="workspace-switcher__heading"><span><small>Account</small><strong>{activeWorkspace?.tenantName ?? session?.user.name}</strong></span><button type="button" onClick={() => { setOpen(false); trigger.current?.focus(); }} aria-label="Close workspace menu"><X /></button></div>
      {!creating ? <>
        <div className="workspace-switcher__list" aria-label="Available workspaces">
          {workspaces.map((workspace) => <button key={workspace.id} type="button" aria-pressed={workspace.id === activeWorkspace?.id} onClick={() => { selectWorkspace(workspace.id); setOpen(false); trigger.current?.focus(); }}>
            <span className="workspace-switcher__initial">{workspace.name.charAt(0).toUpperCase()}</span>
            <span><strong>{workspace.name}</strong><small>{workspace.role?.replace('_', ' ') ?? 'workspace'}</small></span>
            {workspace.id === activeWorkspace?.id ? <Check aria-hidden="true" /> : null}
          </button>)}
        </div>
        <div className="workspace-switcher__actions">
          {session?.user.role === 'owner' || session?.user.role === 'admin' ? <button type="button" onClick={() => setCreating(true)}><Plus />Create workspace</button> : null}
          <Link to="/workspace" onClick={() => setOpen(false)}><Settings2 />Manage workspaces</Link>
        </div>
      </> : <form className="workspace-switcher__form" onSubmit={(event) => void submit(event)}>
        <strong>Create workspace</strong>
        <label>Name<input autoFocus value={name} onChange={(event) => { setName(event.target.value); setSlug(event.target.value.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')); }} placeholder="CPA Division" required minLength={2} maxLength={160} /></label>
        <label>Slug<input value={slug} onChange={(event) => setSlug(event.target.value)} placeholder="cpa-division" required minLength={2} maxLength={80} /></label>
        <div><button type="button" disabled={saving} onClick={() => setCreating(false)}>Cancel</button><button type="submit" disabled={saving || name.trim().length < 2 || slug.trim().length < 2}>{saving ? 'Creating…' : 'Create'}</button></div>
      </form>}
    </div> : null}
  </div>;
}

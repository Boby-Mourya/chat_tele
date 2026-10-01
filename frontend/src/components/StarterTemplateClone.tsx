import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Button, Field, Modal } from '@/components/ui';
import type { StarterItem } from '@/lib/setup-api';
import { starterContentApi, StarterCloneError, type PendingStarterClone, type StarterCloneResult } from '@/lib/starter-content-api';

/** Each instance is keyed by the parent's authorized organization/workspace context. */
export function StarterTemplateClone({ item, canCreate, onCreated }: {
  item: StarterItem & { cloneable?: boolean }; canCreate: boolean; onCreated: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [saved, setSaved] = useState<PendingStarterClone | null>(null);
  const [result, setResult] = useState<StarterCloneResult | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const requestController = useRef<AbortController | null>(null);
  useEffect(() => () => requestController.current?.abort(), []);
  if (!item.cloneable) return null;
  if (!canCreate) return <p>An authorized member with agent creation and view permissions can copy this template.</p>;
  function begin() {
    setError(''); setResult(null); setSaved(null); setName('');
    try {
      const pending = starterContentApi.pending(item.id);
      setSaved(pending); setName(pending?.name ?? `${item.title.slice(0, 100)} copy`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Saved request could not be loaded'); }
    setOpen(true);
  }
  async function run(checkOnly: boolean) {
    if (busy || !canCreate) return;
    setBusy(true); setError('');
    const controller = new AbortController(); requestController.current = controller;
    try {
      const pending = checkOnly ? saved : starterContentApi.prepare(item.id, item.version, name);
      if (!pending) throw new Error('No saved request is available to check');
      setSaved(pending);
      const response = checkOnly ? await starterContentApi.result(pending, controller.signal)
        : await starterContentApi.submit(pending, controller.signal);
      if (controller.signal.aborted) return;
      setResult(response); onCreated();
    } catch (reason) {
      if (!controller.signal.aborted) setError((reason instanceof Error ? reason.message : 'Copy could not be completed')
        + (reason instanceof StarterCloneError && reason.ambiguous ? ' The server may have completed it. Use Check result or retry the same saved request.' : ''));
    } finally { if (!controller.signal.aborted) setBusy(false); }
  }
  function another() {
    if (!result) return;
    try { starterContentApi.startAnother(item.id, result.requestId); setResult(null); setSaved(null); setError(''); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Saved request changed'); }
  }
  return <>
    <Button variant="secondary" onClick={begin}>Use this template</Button>
    <Modal open={open} onClose={() => setOpen(false)} closeDisabled={busy} title="Copy starter template"
      description="Create a draft in this workspace. No private knowledge, students, conversations, leads, API keys or connected accounts will be copied."
      footer={result ? <><Button variant="secondary" onClick={() => setOpen(false)}>Close</Button><Button variant="secondary" onClick={another}>Create another copy</Button></>
        : <><Button variant="secondary" disabled={busy} onClick={() => setOpen(false)}>Close</Button>
          {saved ? <Button variant="secondary" disabled={busy} onClick={() => void run(true)}>Check result</Button> : null}
          <Button disabled={busy || name.trim().length < 2} onClick={() => void run(false)}>{busy ? 'Checking…' : saved ? 'Retry saved request' : 'Create draft copy'}</Button></>}>
      {error ? <p role="alert" className="setup-error">{error}</p> : null}
      {result ? <div role="status"><p>{result.replayed ? 'Found the previously completed copy' : 'Draft copy created'}: <strong>{result.name}</strong>.</p>
        <p>Source version {result.catalogVersion}. The copy originally starts in draft; any later edits and deployment remain separate.</p>
        <Link to={`/agents/${result.agentId}`} onClick={() => setOpen(false)}>Open the agent editor</Link></div>
        : <><p><strong>{item.title}</strong> · catalog version {item.version}</p>
          <Field label="Agent name"><input value={name} minLength={2} maxLength={120} disabled={busy} onChange={(event) => setName(event.target.value)} /></Field>
          <p>This uses one agent slot. Review the instructions, add authorized knowledge and test the draft before publishing it.</p>
          {saved ? <p>A recovery request is saved in this browser tab. Reopening this form or retrying uses the same request ID, even after changing its name. Check result to recover a completed copy.</p> : null}</>}
    </Modal>
  </>;
}

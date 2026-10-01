import { useEffect, useState } from 'react';
import { api, type ExtractionReading, type ExtractionRecord, type ExtractionReviewSubmission } from '@/lib/api';
import { apiErrorMessage } from '@/lib/api-error-message';
import { Button, Modal } from '@/components/ui';
import type { KnowledgeSource } from '@/types';

type Decision = ExtractionReviewSubmission['issueResolutions'][number];

export function ExtractionReviewModal({ source, onClose, onApproved }: {
  source: KnowledgeSource; onClose: () => void; onApproved: (message?: string) => void;
}) {
  const [record, setRecord] = useState<ExtractionRecord | null>(null);
  const [current, setCurrent] = useState(0);
  const [loadedImage, setLoadedImage] = useState<{ sourceId: string; page: number; url: string } | null>(null);
  const [structures, setStructures] = useState<Record<string, string>>({});
  const [links, setLinks] = useState<Record<string, string>>({});
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [confirmed, setConfirmed] = useState(false);
  const [blank, setBlank] = useState(false);
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const initialize = (value: ExtractionRecord) => {
    setRecord(value);
    setStructures(Object.fromEntries(value.pages.flatMap((p) => (p.blocks ?? []).map((b) =>
      [b.id, JSON.stringify(b.reviewed_structure ?? b.visual, null, 2)]))));
    setLinks(Object.fromEntries(value.pages.flatMap((p) => (p.blocks ?? []).map((b) => [b.id, (b.related_block_ids ?? []).join(', ')]))));
    setDecisions({}); setConfirmed(false); setBlank(false); setReason('');
  };

  useEffect(() => {
    let active = true;
    void api.knowledge.extraction(source.id).then((value) => { if (active) initialize(value); })
      .catch((cause: unknown) => { if (active) setError(apiErrorMessage(cause, 'Unable to load extraction evidence.')); });
    return () => { active = false; };
  }, [source.id]);

  const page = record?.pages[current];
  const imageUrl = loadedImage && page && loadedImage.sourceId === source.id && loadedImage.page === page.number ? loadedImage.url : null;
  useEffect(() => {
    if (!page?.image) return;
    let active = true;
    let url: string | null = null;
    void api.knowledge.extractionPage(source.id, page.number).then((blob) => {
      url = URL.createObjectURL(blob);
      if (active) setLoadedImage({ sourceId: source.id, page: page.number, url });
      else URL.revokeObjectURL(url);
    }).catch((cause: unknown) => { if (active) setError(apiErrorMessage(cause, 'Unable to load page image.')); });
    return () => { active = false; if (url) URL.revokeObjectURL(url); };
  }, [source.id, page?.number, page?.image]);

  const download = async () => {
    try {
      const blob = await api.knowledge.extractionArchive(source.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url; anchor.download = `${source.name}-extraction-review.zip`; anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (cause) { setError(apiErrorMessage(cause, 'Unable to download evidence.')); }
  };

  const openStoredPdf = async () => {
    try {
      const blob = await api.knowledge.extractionSourcePdf(source.id);
      window.open(URL.createObjectURL(blob), '_blank', 'noopener,noreferrer');
    } catch (cause) { setError(apiErrorMessage(cause, 'This source is not a stored PDF.')); }
  };

  const downloadText = async () => {
    try {
      const blob = await api.knowledge.extractionText(source.id);
      const url = URL.createObjectURL(blob); const anchor = document.createElement('a');
      anchor.href = url; anchor.download = `${source.name}-extracted.txt`; anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (cause) { setError(apiErrorMessage(cause, 'Unable to download extracted text.')); }
  };

  const save = async () => {
    if (!record || !page || !confirmed) return;
    setSaving(true); setError(''); setNotice('');
    try {
      const blocks = (page.blocks ?? []).filter((b) => b.status !== 'split').map((b) => {
        const structure = JSON.parse(structures[b.id] ?? 'null') as ExtractionReading | null;
        if (!structure || typeof structure.text !== 'string') throw new Error(`Region ${b.id} needs a complete structured reading.`);
        return { id: b.id, selectedText: structure.text, structure,
          relatedBlockIds: (links[b.id] ?? '').split(',').map((v) => v.trim()).filter(Boolean) };
      });
      const result = await api.knowledge.approveExtraction(source.id, {
        extractionRevision: record.extraction_revision,
        pages: [{ number: page.number, selectedText: blocks.length ? blocks.map((b) => b.selectedText).join('\n') : page.native_text,
          reason, structureConfirmed: confirmed, blankConfirmed: blank, blocks }],
        issueResolutions: Object.values(decisions).filter((d) => record.issues.some((i) => i.id === d.id && (i.page === page.number || i.page === 0))),
      });
      if (result.status !== 'needs_review') { onApproved('Verified extraction released'); return; }
      initialize(await api.knowledge.extraction(source.id));
      setNotice('Review saved. Release remains blocked until all checks and required independent reviews pass.');
    } catch (cause) { setError(apiErrorMessage(cause, cause instanceof Error ? cause.message : 'Unable to save review.')); }
    finally { setSaving(false); }
  };

  const retry = async () => {
    setSaving(true); setError('');
    try { await api.knowledge.retryExtraction(source.id); onApproved('Extraction retry started'); }
    catch (cause) { setError(apiErrorMessage(cause, 'Unable to retry extraction.')); }
    finally { setSaving(false); }
  };

  const issues = record?.issues.filter((issue) => issue.page === page?.number || issue.page === 0) ?? [];
  const leaves = (page?.blocks ?? []).filter((b) => b.status !== 'split');
  const released = record?.review_status === 'verified_release';
  const blocked = released || record?.schema_version !== 2 || issues.some((i) => i.technical && i.status !== 'resolved')
    || leaves.some((b) => !b.visual) || (Boolean(page?.image) && !imageUrl);
  const updateStructure = (id: string, value: string) => { setStructures((s) => ({ ...s, [id]: value })); setConfirmed(false); };
  const changePage = (index: number) => { setCurrent(index); setConfirmed(false); setBlank(false); setReason(''); };

  return <Modal open onClose={onClose} size="lg" title={`Review extraction: ${source.name}`}
    description="Compare source evidence and save each page. Critical content requires two different reviewers."
    footer={<><Button variant="secondary" onClick={() => void openStoredPdf()} disabled={!record || saving}>Open stored PDF</Button>
      <Button variant="secondary" onClick={() => void downloadText()} disabled={!record || saving}>Download extracted text</Button>
      <Button variant="secondary" onClick={() => void download()} disabled={!record || saving}>Download evidence</Button>
      <Button variant="secondary" onClick={() => void retry()} disabled={saving || released}>Reprocess source</Button>
      <Button variant="secondary" onClick={onClose} disabled={saving}>Close</Button>
      <Button onClick={() => void save()} disabled={saving || !page || blocked || !confirmed || !reason.trim()}>
        {saving ? 'Saving…' : 'Save page review'}
      </Button></>}>
    {error && <p role="alert" className="form-error">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {!record ? <p>Loading extraction…</p> : <>
      <p>Revision {record.extraction_revision} · {record.review_status.replaceAll('_', ' ')} · Measured accuracy: not measured</p>
      <details><summary>Validation checks and release blockers</summary>
        {(record.checks ?? []).map((c) => <p key={c.name}>{c.name.replaceAll('_', ' ')}: {c.status} {c.details.join('; ')}</p>)}
      </details>
      {record.word && <details><summary>Word source parts and annotation channels</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(record.word, null, 2)}</pre></details>}
      {page ? <div className="extraction-review">
        <p><strong>Source unit {page.number} of {record.pages.length}</strong> · Printed label: {page.printed_page_label ?? 'not identified'}</p>
        {page.quality && <p>Extraction quality: {Math.round(page.quality.score * 100)}% · {page.quality.method.replaceAll('_', ' ')}{page.quality.reasons.length ? ` · Review flags: ${page.quality.reasons.join(', ')}` : ' · Native text accepted'}</p>}
        <p>Primary review: {page.primary_review ? 'recorded' : 'pending'}. {page.requires_second_review && `Independent second review: ${page.second_review ? 'recorded' : 'required'}.`}</p>
        {blocked && !released && <p role="alert">This page needs successful source processing and loaded evidence before review can be saved. The draft package remains available.</p>}
        {imageUrl && <a href={imageUrl} target="_blank" rel="noreferrer" aria-label="Open full resolution source page"><img src={imageUrl} alt={`Original source page ${page.number}`} style={{ display: 'block', width: '100%', maxHeight: 550, objectFit: 'contain' }} /></a>}
        <label>Native source text<textarea readOnly rows={6} value={page.native_text} style={{ width: '100%' }} /></label>
        {page.visual_text !== null && <label>Independent visual reading<textarea readOnly rows={6} value={page.visual_text} style={{ width: '100%' }} /></label>}
        {leaves.map((block) => {
          let reading: ExtractionReading | null = null;
          try { reading = JSON.parse(structures[block.id] ?? 'null') as ExtractionReading | null; } catch { /* Keep invalid drafts visible for repair. */ }
          return <fieldset key={block.id} style={{ margin: '16px 0' }}><legend>{block.type} · {block.id}</legend>
            {block.crop && <RegionEvidence sourceId={source.id} blockId={block.id} />}
            <p>Source rectangle: {block.bbox_px?.join(', ')} pixels</p>
            <label>Selected region text<textarea rows={4} value={reading?.text ?? ''} disabled={!reading}
              onChange={(e) => updateStructure(block.id, JSON.stringify({ ...reading, text: e.target.value }, null, 2))} style={{ width: '100%' }} /></label>
            {reading?.cells && reading.cells.length > 0 && <table><caption>Table cells and header relationships</caption><thead><tr><th>Row / column</th><th>Value</th><th>State</th><th>Headers</th></tr></thead><tbody>
              {reading.cells.map((cell, index) => <tr key={index}><td>{cell.row + 1} / {cell.column + 1}</td><td>{cell.text}</td><td>{cell.state ?? 'VALUE'}</td><td>{cell.header_refs?.join(', ')}</td></tr>)}
            </tbody></table>}
            <details><summary>Review structured evidence: cells, equations, options and captions</summary>
              <p>Preserve exact source values. Header references use zero-based R0C0 coordinates. Descriptions remain separate from visible text.</p>
              <label>Structured reading for {block.id}<textarea rows={12} value={structures[block.id] ?? ''} onChange={(e) => updateStructure(block.id, e.target.value)} style={{ width: '100%', fontFamily: 'monospace' }} /></label>
            </details>
            <label>Related source block IDs (comma separated)<input value={links[block.id] ?? ''} onChange={(e) => { setLinks((s) => ({ ...s, [block.id]: e.target.value })); setConfirmed(false); }} style={{ width: '100%' }} /></label>
          </fieldset>;
        })}
        {issues.map((issue) => <fieldset key={issue.id}><legend>{issue.code} · {issue.status ?? 'open'}</legend>
          <p>{issue.message} {issue.block_id}</p>
          {issue.status !== 'resolved' && !issue.technical && <>
            <label>Decision for {issue.id}<select value={decisions[issue.id]?.action ?? 'unresolved'} onChange={(e) => { setConfirmed(false); setDecisions((s) => ({ ...s, [issue.id]: { id: issue.id, action: e.target.value as Decision['action'], reason: s[issue.id]?.reason ?? '' } })); }}>
              <option value="unresolved">Unresolved — block release</option><option value="source_verified">Verified against source</option><option value="source_anomaly">Source mistake preserved</option>
            </select></label>
            <label>Source evidence and reason for {issue.id}<input value={decisions[issue.id]?.reason ?? ''} onChange={(e) => { setConfirmed(false); setDecisions((s) => ({ ...s, [issue.id]: { id: issue.id, action: s[issue.id]?.action ?? 'unresolved', reason: e.target.value } })); }} style={{ width: '100%' }} /></label>
          </>}
        </fieldset>)}
        <label>Reason for page review<input value={reason} onChange={(e) => setReason(e.target.value)} style={{ width: '100%' }} /></label>
        {!leaves.length && !page.native_text && <label><input type="checkbox" checked={blank} onChange={(e) => setBlank(e.target.checked)} />Source is blank</label>}
        <label><input type="checkbox" checked={confirmed} disabled={blocked} onChange={(e) => setConfirmed(e.target.checked)} />
          I checked every source region, text, order, table cell, equation and relationship on this page.</label>
        <div style={{ display: 'flex', gap: 12, marginTop: 16 }}>
          <Button variant="secondary" disabled={saving || current === 0} onClick={() => changePage(current - 1)}>Previous</Button>
          <Button variant="secondary" disabled={saving || current === record.pages.length - 1} onClick={() => changePage(current + 1)}>Next</Button>
        </div>
      </div> : <p>No source units were extracted. Check the validation report and reprocess a readable source.</p>}
    </>}
  </Modal>;
}

function RegionEvidence({ sourceId, blockId }: { sourceId: string; blockId: string }) {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!open) return;
    let active = true;
    let objectUrl: string | null = null;
    void api.knowledge.extractionRegion(sourceId, blockId).then((blob) => {
      objectUrl = URL.createObjectURL(blob);
      if (active) setUrl(objectUrl); else URL.revokeObjectURL(objectUrl);
    }).catch((cause: unknown) => { if (active) setError(apiErrorMessage(cause, 'Unable to load source crop.')); });
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [open, sourceId, blockId]);
  return <details onToggle={(event) => setOpen(event.currentTarget.open)}><summary>Inspect original region crop</summary>
    {error && <p role="alert">{error}</p>}
    {open && url && <a href={url} target="_blank" rel="noreferrer"><img src={url} alt={`Source crop ${blockId}`} style={{ maxWidth: '100%' }} /></a>}
  </details>;
}

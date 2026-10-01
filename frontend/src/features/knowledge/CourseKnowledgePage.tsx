import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useAuth, useWorkspace } from '@/components/providers';
import { api } from '@/lib/api';
import { knowledgeBlob, knowledgePath, knowledgeRequest, saveKnowledgeBlob, stageCourseFile, type AcademicReview, type KnowledgeCatalog, type KnowledgeRecord, type KnowledgeStatus, type StudentPreview, type TutorContext, type TutorProgress, type VersionDetail } from './api';
import './CourseKnowledgePage.css';

const emptyCatalog: KnowledgeCatalog = { courses: [], batches: [], curricula: [], papers: [], batchCurricula: [] };
const emptyStatus: KnowledgeStatus = { sources: [], versions: [], assignments: [], releases: [], heads: [], artifacts: [], access: [], enrollments: [], academicReviews: [], jobs: [], notice: '' };
function name(row?: KnowledgeRecord) { return row?.name || row?.title || row?.code || row?.id || ''; }
function toggle(values: string[], value: string) { return values.includes(value) ? values.filter(v => v !== value) : [...values, value]; }

export function CourseKnowledgePage() {
  const { activeWorkspace } = useWorkspace();
  return <KnowledgeWorkspace key={activeWorkspace?.id ?? 'none'} />;
}

function KnowledgeWorkspace() {
  const { activeWorkspace } = useWorkspace();
  const { session } = useAuth();
  const [params] = useSearchParams();
  const [catalog, setCatalog] = useState(emptyCatalog);
  const [status, setStatus] = useState(emptyStatus);
  const [progress, setProgress] = useState<TutorProgress[]>([]);
  const [contexts, setContexts] = useState<TutorContext[]>([]);
  const [reviews, setReviews] = useState<AcademicReview[]>([]);
  const [reviewNotes, setReviewNotes] = useState<Record<string, string>>({});
  const [agents, setAgents] = useState<KnowledgeRecord[]>([]);
  const [agent, setAgent] = useState(params.get('agentId') ?? '');
  const [course, setCourse] = useState(params.get('courseId') ?? '');
  const [curriculum, setCurriculum] = useState('');
  const [paper, setPaper] = useState('');
  const [batch, setBatch] = useState('');
  const [materialType, setMaterialType] = useState('notes');
  const [language, setLanguage] = useState('English');
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const staged = useRef<{ file: File; key: string } | null>(null);
  const uploadRequest = useRef({ key: crypto.randomUUID(), fingerprint: '' });
  const mappingRequest = useRef({ key: crypto.randomUUID(), fingerprint: '' });
  const [detail, setDetail] = useState<VersionDetail | null>(null);
  const [blocks, setBlocks] = useState<string[]>([]);
  const [editing, setEditing] = useState<KnowledgeRecord | null>(null);
  const [selectedAssignments, setSelectedAssignments] = useState<string[]>([]);
  const [selectedArtifacts, setSelectedArtifacts] = useState<string[]>([]);
  const [reason, setReason] = useState('');
  const [mismatch, setMismatch] = useState(false);
  const [enrollment, setEnrollment] = useState('');
  const [allowedPapers, setAllowedPapers] = useState<string[]>([]);
  const [query, setQuery] = useState('');
  const [preview, setPreview] = useState<StudentPreview | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [originalImage, setOriginalImage] = useState('');
  const [curriculumCode, setCurriculumCode] = useState('');
  const [curriculumName, setCurriculumName] = useState('');
  const [paperCode, setPaperCode] = useState('');
  const [paperName, setPaperName] = useState('');
  const [artifactType, setArtifactType] = useState('summary');
  const [artifactReview, setArtifactReview] = useState<KnowledgeRecord | null>(null);
  const [answerKeyVerified, setAnswerKeyVerified] = useState(false);
  const permissions = activeWorkspace?.permissions ?? [];
  const owner = session?.user.role === 'owner' || session?.user.role === 'admin';
  const canManage = owner || permissions.includes('*') || (permissions.includes('education.manage') && permissions.includes('knowledge.manage'));
  const curricula = catalog.curricula.filter(c => c.courseId === course);
  const papers = catalog.papers.filter(p => p.curriculumId === curriculum);
  const batches = catalog.batches.filter(b => b.courseId === course);
  const scopeAssignments = status.assignments.filter(a => a.courseId === course && a.curriculumId === curriculum);
  const source = status.versions.find(v => v.id === detail?.id);
  const courseName = name(catalog.courses.find(c => c.id === course));
  const audience = `${courseName || 'Selected course'} / ${name(curricula.find(c => c.id === curriculum)) || 'select curriculum'} / ${paper === 'overview' ? 'course overview only' : name(papers.find(p => p.id === paper)) || 'select paper'} / ${batch ? name(batches.find(b => b.id === batch)) : 'all matching batches'}`;

  async function load() {
    const next = await knowledgeRequest<KnowledgeCatalog>('/education/knowledge/catalog');
    setCatalog(next);
    if (agent) {
      const [nextStatus, nextProgress, nextContexts, nextReviews] = await Promise.all([
        knowledgeRequest<KnowledgeStatus>(knowledgePath(agent, '/status')),
        knowledgeRequest<TutorProgress[]>(`/education/progress?agent_id=${encodeURIComponent(agent)}`),
        knowledgeRequest<TutorContext[]>(`/education/tutor-contexts?agent_id=${encodeURIComponent(agent)}`),
        knowledgeRequest<AcademicReview[]>(`/education/academic-reviews?agent_id=${encodeURIComponent(agent)}`),
      ]);
      setStatus(nextStatus); setProgress(nextProgress); setContexts(nextContexts); setReviews(nextReviews);
    }
  }
  async function action(work: () => Promise<unknown>, message: string) {
    if (busy) return;
    setBusy(true); setError(''); setNotice('');
    try { await work(); await load(); setNotice(message); }
    catch (e) { setError(e instanceof Error ? e.message : 'The request failed'); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    let live = true;
    void Promise.all([knowledgeRequest<KnowledgeCatalog>('/education/knowledge/catalog'), api.agents.list()]).then(([next, list]) => {
      if (live) { setCatalog(next); setAgents(list.filter(a => a.purpose === 'education').map(a => ({ id: a.id, name: a.name }))); }
    }).catch(e => { if (live) setError(String(e)); });
    return () => { live = false; };
  }, []);
  useEffect(() => {
    if (!agent) return;
    let live = true;
    const reload = () => void Promise.all([
      knowledgeRequest<KnowledgeStatus>(knowledgePath(agent, '/status')),
      knowledgeRequest<TutorProgress[]>(`/education/progress?agent_id=${encodeURIComponent(agent)}`),
      knowledgeRequest<TutorContext[]>(`/education/tutor-contexts?agent_id=${encodeURIComponent(agent)}`),
      knowledgeRequest<AcademicReview[]>(`/education/academic-reviews?agent_id=${encodeURIComponent(agent)}`),
    ]).then(([nextStatus, nextProgress, nextContexts, nextReviews]) => { if (live) { setStatus(nextStatus); setProgress(nextProgress); setContexts(nextContexts); setReviews(nextReviews); } }).catch(e => { if (live) setError(String(e)); });
    reload(); const timer = setInterval(reload, 10000);
    return () => { live = false; clearInterval(timer); };
  }, [agent]);
  useEffect(() => () => { if (originalImage) URL.revokeObjectURL(originalImage); }, [originalImage]);

  function destination() { return { courseId: course, curriculumId: curriculum, paperId: !['overview', 'mixed', ''].includes(paper) ? paper : null, overview: paper === 'overview', mixedPapers: paper === 'mixed', batchId: batch || null, materialType, language }; }
  async function openVersion(id: string) {
    const value = await knowledgeRequest<VersionDetail>(knowledgePath(agent, `/versions/${id}`));
    setDetail(value); setBlocks([]); setEditing(null); setOriginalImage('');
  }
  function selectCourse(value: string) { setCourse(value); setCurriculum(''); setPaper(''); setBatch(''); setSelectedAssignments([]); setSelectedArtifacts([]); setPreview(null); setArtifactReview(null); }
  function selectAgent(value: string) {
    setAgent(value); setStatus(emptyStatus); setProgress([]); setContexts([]); setReviews([]); setReviewNotes({});
    setDetail(null); setBlocks([]); setEditing(null); setPreview(null); setEnrollment(''); setSelectedAssignments([]); setSelectedArtifacts([]);
  }
  async function upload(event: FormEvent) {
    event.preventDefault();
    await action(async () => {
      if (!agent || !course || !curriculum || !paper) throw new Error('Choose an Education Agent, course, curriculum, and paper mode before uploading.');
      let objectKey: string | undefined;
      if (file) {
        if (staged.current?.file !== file) staged.current = { file, key: await stageCourseFile(file) };
        objectKey = staged.current.key;
      }
      const body = { title: title || file?.name, destination: destination(), kind: file ? 'file' : 'text', ...(file ? { objectKey } : { content: text }) };
      const identity = JSON.stringify(body);
      if (uploadRequest.current.fingerprint !== identity) uploadRequest.current = { fingerprint: identity, key: crypto.randomUUID() };
      await knowledgeRequest(knowledgePath(agent, '/uploads'), 'POST', { ...body, idempotencyKey: uploadRequest.current.key });
      setFile(null); setText(''); staged.current = null;
    }, 'Upload recorded with its intended course. Processing does not publish it.');
  }
  async function saveMapping() {
    if (!detail) return;
    await action(async () => {
      const body = { ...destination(), mixedPapers: false, sourceVersionId: detail.id, blockIds: blocks, ...(editing ? { expectedRevision: editing.revision } : {}) };
      const identity = JSON.stringify({ agent, body });
      if (mappingRequest.current.fingerprint !== identity) mappingRequest.current = { fingerprint: identity, key: crypto.randomUUID() };
      await knowledgeRequest(knowledgePath(agent, editing ? `/assignments/${editing.id}` : '/assignments'), editing ? 'PUT' : 'POST', { ...body, idempotencyKey: editing?.idempotencyKey || mappingRequest.current.key });
      setEditing(null);
    }, 'Mapping saved for review. Previous approval cannot authorize an edited mapping.');
  }
  async function download(path: string, filename: string) { saveKnowledgeBlob(await knowledgeBlob(path), filename); }
  async function publish(release: KnowledgeRecord) {
    const head = status.heads.find(h => h.courseId === release.courseId && h.curriculumId === release.curriculumId);
    if (!window.confirm(`Publish this exact release for ${courseName}? Each included assignment retains its own paper and batch restrictions.`)) return;
    await action(() => knowledgeRequest(knowledgePath(agent, `/releases/${release.id}/publish`), 'POST', { expectedEpoch: head?.epoch ?? 0 }), 'Knowledge release activated.');
  }
  function selectEnrollment(id: string) { setEnrollment(id); setPreview(null); setAllowedPapers(status.access.find(a => a.enrollmentId === id)?.paperIds ?? []); }
  function enrollmentLabel(id: string | null) {
    if (!id) return 'No course selected';
    const row = status.enrollments.find(item => item.id === id);
    const courseLabel = name(catalog.courses.find(item => item.id === row?.courseId));
    const batchLabel = name(catalog.batches.find(item => item.id === row?.batchId));
    return row ? `${courseLabel || 'Course'}${batchLabel ? ` · ${batchLabel}` : ''}` : `Enrollment ${id.slice(0, 8)}`;
  }
  function paperLabel(id: string | null) { return id ? name(catalog.papers.find(item => item.id === id)) || `Paper ${id.slice(0, 8)}` : 'Course overview'; }
  function reviewNote(id: string) { return reviewNotes[id]?.trim() ?? ''; }
  async function resolveAcademicReview(review: AcademicReview, outcome: 'confirmed' | 'corrected') {
    const resolution = reviewNote(review.id);
    if (!resolution) return;
    await action(() => knowledgeRequest(`/education/academic-reviews/${review.id}/resolve`, 'POST', {
      outcome, resolution, requestCorrectionDelivery: outcome === 'corrected',
    }), outcome === 'corrected' ? 'Correction recorded for policy-checked delivery.' : 'Reviewed answer confirmed.');
    setReviewNotes(current => { const next = { ...current }; delete next[review.id]; return next; });
  }
  const previewBody = { enrollmentId: enrollment, query, selectedPaperId: ['overview', 'mixed', ''].includes(paper) ? null : paper };

  return <div className="ck-page">
    <header><h2>Course knowledge</h2><p>Prepare once per source version. Approve explicit audiences. Students select published knowledge, not a new model.</p></header>
    {error && <p role="alert" className="ck-error">{error}</p>}{notice && <p role="status" className="ck-notice">{notice}</p>}
    <section className="ck-panel ck-grid" aria-label="Knowledge destination">
      <label>Education Agent<select value={agent} onChange={e => selectAgent(e.target.value)}><option value="">Select agent</option>{agents.map(a => <option key={a.id} value={a.id}>{name(a)}</option>)}</select></label>
      <label>Course<select value={course} onChange={e => selectCourse(e.target.value)}><option value="">Select course</option>{catalog.courses.map(c => <option key={c.id} value={c.id}>{name(c)}</option>)}</select></label>
      <label>Curriculum<select value={curriculum} onChange={e => { setCurriculum(e.target.value); setPaper(''); setSelectedAssignments([]); }}><option value="">Select curriculum</option>{curricula.map(c => <option key={c.id} value={c.id}>{name(c)}</option>)}</select></label>
      <label>Paper<select value={paper} onChange={e => { setPaper(e.target.value); setPreview(null); }}><option value="">Select paper mode</option><option value="overview">Course overview only</option><option value="mixed">Mixed papers (upload only)</option>{papers.map(p => <option key={p.id} value={p.id}>{name(p)}</option>)}</select></label>
      <label>Audience<select value={batch} onChange={e => setBatch(e.target.value)}><option value="">All matching batches</option>{batches.map(b => <option key={b.id} value={b.id}>{name(b)}</option>)}</select></label>
      <label>Material type<select value={materialType} onChange={e => setMaterialType(e.target.value)}>{['notes', 'textbook', 'practice', 'worked_examples'].map(v => <option key={v}>{v}</option>)}</select></label>
      <label>Language<input value={language} onChange={e => setLanguage(e.target.value)} maxLength={80} /></label>
      <p className="ck-wide">Audience: <strong>{audience}</strong>. Only students with a valid matching enrollment can receive it.</p>
    </section>
    <details className="ck-panel"><summary>Configure curricula, papers, batches, and enrollment access</summary><fieldset disabled={!canManage || busy}>
      <div className="ck-grid"><label>Curriculum code<input value={curriculumCode} onChange={e => setCurriculumCode(e.target.value)} /></label><label>Curriculum name<input value={curriculumName} onChange={e => setCurriculumName(e.target.value)} /></label><button onClick={() => void action(() => knowledgeRequest('/education/knowledge/curricula', 'POST', { courseId: course, code: curriculumCode, name: curriculumName }), 'Curriculum created.')}>Create curriculum</button></div>
      <div className="ck-grid"><label>Paper code<input value={paperCode} onChange={e => setPaperCode(e.target.value)} /></label><label>Paper name<input value={paperName} onChange={e => setPaperName(e.target.value)} /></label><button onClick={() => void action(() => knowledgeRequest('/education/knowledge/papers', 'POST', { curriculumId: curriculum, code: paperCode, name: paperName }), 'Paper created.')}>Create paper</button><button disabled={!batch || !curriculum} onClick={() => void action(() => knowledgeRequest('/education/knowledge/batch-curriculum', 'PUT', { batchId: batch, curriculumId: curriculum }), 'Batch curriculum bound.')}>Bind selected batch to curriculum</button></div>
      <label>Enrollment<select value={enrollment} onChange={e => selectEnrollment(e.target.value)}><option value="">Select enrollment</option>{status.enrollments.filter(e => e.courseId === course).map(e => <option key={e.id} value={e.id}>{e.studentId} / {name(batches.find(b => b.id === e.batchId))} / {e.status}</option>)}</select></label>
      <div className="ck-checks">{papers.map(p => <label key={p.id}><input type="checkbox" checked={allowedPapers.includes(p.id)} onChange={() => setAllowedPapers(toggle(allowedPapers, p.id))} />{name(p)}</label>)}</div>
      <button disabled={!enrollment} onClick={() => void action(() => knowledgeRequest(knowledgePath(agent, `/enrollments/${enrollment}/access`), 'PUT', { curriculumId: curriculum, paperIds: allowedPapers, selectedPaperId: null, expectedRevision: status.access.find(a => a.enrollmentId === enrollment)?.revision ?? 0, active: true }), 'Enrollment access saved without document reprocessing.')}>Save authorized papers</button>
      <button disabled={!enrollment} onClick={() => void action(() => knowledgeRequest(knowledgePath(agent, `/enrollments/${enrollment}/access`), 'PUT', { curriculumId: curriculum, paperIds: allowedPapers, selectedPaperId: null, expectedRevision: status.access.find(a => a.enrollmentId === enrollment)?.revision ?? 0, active: false }), 'Course knowledge access revoked.')}>Revoke knowledge access</button>
    </fieldset></details>
    <section className="ck-panel"><h3>1. Upload into this course</h3><form onSubmit={event => void upload(event)}><fieldset disabled={!canManage || busy || !agent}>
      <label>Source title<input required value={title} onChange={e => setTitle(e.target.value)} maxLength={180} /></label>
      <label>File<input type="file" accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.tif,.tiff" onChange={e => { setFile(e.target.files?.[0] ?? null); staged.current = null; }} /></label>
      <label>Or native text<textarea value={text} onChange={e => setText(e.target.value)} disabled={!!file} rows={5} /></label>
      <button type="submit" disabled={!course || !curriculum || !paper || (!file && !text.trim())}>{busy ? 'Working…' : 'Upload and prepare'}</button>
    </fieldset></form><p>Legacy or bulk uploads without an assignment remain an administrative inbox, never shared student knowledge.</p>
    {status.sources.map(s => <div className="ck-row" key={s.id}><span>{name(s)} — {s.status}{status.jobs.find(j => j.sourceId === s.id)?.step ? ` / ${status.jobs.find(j => j.sourceId === s.id)?.step}` : ''}</span><Link to={`/agents/${agent}/knowledge`}>Extraction review</Link><button disabled={!canManage || busy || s.status !== 'ready'} onClick={() => void action(() => knowledgeRequest(knowledgePath(agent, `/sources/${s.id}/snapshot`), 'POST'), 'Reviewed source snapshot prepared.')}>Prepare immutable snapshot</button></div>)}</section>
    <section className="ck-panel"><h3>2. Review and map source blocks</h3><label>Source version<select value={detail?.id ?? ''} onChange={e => { if (e.target.value) void action(() => openVersion(e.target.value), 'Source blocks loaded.'); }}><option value="">Choose version</option>{status.versions.map(v => <option key={v.id} value={v.id}>{name(v)} / v{v.sourceRevision}{v.withdrawn ? ' (withdrawn)' : ''}</option>)}</select></label>
      {detail && <><p>{detail.sourceUnitNotice}</p><div className="ck-actions"><button onClick={() => void action(() => download(knowledgePath(agent, `/versions/${detail.id}/report`), 'course-knowledge-review.zip'), 'Extraction report downloaded.')}>Download text, structure, mapping, and validation</button><button disabled={!canManage || busy || !reason.trim()} onClick={() => void action(() => knowledgeRequest(knowledgePath(agent, `/versions/${detail.id}/withdraw`), 'POST', { reason }), 'Source and dependent material withdrawn.')}>Withdraw this source version</button></div>
      <div className="ck-review"><div>{detail.blocks.map(b => <article className="ck-block" key={b.id}><label><input type="checkbox" checked={blocks.includes(b.id)} onChange={() => setBlocks(toggle(blocks, b.id))} />{b.id} / {b.type} / {b.page_number ? `page ${b.page_number}` : `source unit ${b.unit}`}</label><pre>{b.text}</pre>{b.structure ? <details><summary>Source structure</summary><pre>{JSON.stringify(b.structure, null, 2)}</pre></details> : null}{b.related_block_ids.length > 0 && <small>Include linked blocks: {b.related_block_ids.join(', ')}</small>}<button onClick={() => void action(async () => { const image = await knowledgeBlob(`/knowledge/${detail.sourceId}/extraction/pages/${b.unit}`); setOriginalImage(URL.createObjectURL(image)); }, 'Original source unit loaded for staff review.')}>View original source unit</button></article>)}</div><div>{originalImage ? <img src={originalImage} alt="Original source unit for comparison with extracted blocks" /> : <p>Select an original source unit to compare it beside the extraction. Text-only sources have no page image.</p>}</div></div>
      <button disabled={!canManage || busy || !blocks.length || paper === 'mixed' || !paper || source?.withdrawn} onClick={() => void saveMapping()}>{editing ? 'Save new mapping revision' : 'Save selected blocks as assignment'}</button></>}
      <label>Review / withdrawal reason<textarea value={reason} onChange={e => setReason(e.target.value)} rows={2} /></label><label><input type="checkbox" checked={mismatch} onChange={e => setMismatch(e.target.checked)} />I reviewed any possible course mismatch and confirm the explicit destination.</label>
      {scopeAssignments.map(a => <article className="ck-block" key={a.id}><label><input type="checkbox" checked={selectedAssignments.includes(a.id)} onChange={() => setSelectedAssignments(toggle(selectedAssignments, a.id))} />{a.id.slice(0, 8)} / revision {a.revision} / {a.status} / index {a.indexStatus}</label><p>{a.overview ? 'Course overview' : name(papers.find(p => p.id === a.paperId))} / {a.batchId ? name(batches.find(b => b.id === a.batchId)) : 'All matching batches'} / {a.blockIds?.length} blocks</p>{a.indexError && <p role="alert">{a.indexError}</p>}{a.validation?.warnings?.map((w, i) => <p key={i} className="ck-error">{w.code}: {w.evidence}</p>)}<div className="ck-actions">
        <button disabled={!canManage || busy || a.status === 'withdrawn'} onClick={() => void action(async () => { const v = await knowledgeRequest<VersionDetail>(knowledgePath(agent, `/versions/${a.sourceVersionId}`)); setDetail(v); setBlocks(a.blockIds ?? []); setEditing(a); setPaper(a.overview ? 'overview' : a.paperId ?? ''); setBatch(a.batchId ?? ''); }, 'Mapping loaded for editing.')}>Edit mapping</button>
        <button disabled={!canManage || busy || a.status !== 'review' || !reason.trim()} onClick={() => void action(() => knowledgeRequest(knowledgePath(agent, `/assignments/${a.id}/approve`), 'POST', { expectedRevision: a.revision, expectedSourceHash: status.versions.find(v => v.id === a.sourceVersionId)?.recordHash, reason, mismatchConfirmed: mismatch }), 'Exact mapping revision approved.')}>Approve exact revision</button>
        <button disabled={!canManage || busy || a.status !== 'approved'} onClick={() => void action(() => knowledgeRequest(knowledgePath(agent, `/assignments/${a.id}/prepare`), 'POST', { expectedRevision: a.revision }), 'Durable index preparation requested.')}>Prepare / retry index</button>
        <button disabled={!canManage || busy || !reason.trim()} onClick={() => void action(() => knowledgeRequest(knowledgePath(agent, `/assignments/${a.id}/withdraw`), 'POST', { reason }), 'Assignment withdrawn immediately.')}>Withdraw assignment</button></div></article>)}
    </section>
    <section className="ck-panel"><h3>3. Derived learning material</h3><p>Generated material stays in review and inherits the intersection of all selected source audiences.</p><select aria-label="Artifact type" value={artifactType} onChange={e => setArtifactType(e.target.value)}>{['summary', 'flashcards', 'practice_questions', 'translation', 'worked_example'].map(t => <option key={t}>{t}</option>)}</select><button disabled={!canManage || busy || !selectedAssignments.length} onClick={() => void action(async () => { const a = await knowledgeRequest<KnowledgeRecord>(knowledgePath(agent, '/artifacts'), 'POST', { assignmentIds: selectedAssignments, artifactType }); setArtifactReview(a); setAnswerKeyVerified(false); }, 'Draft artifact generated; it is not student evidence yet.')}>Generate draft from selected assignments</button>
      {status.artifacts.map(a => <div className="ck-row" key={a.id}><label><input type="checkbox" checked={selectedArtifacts.includes(a.id)} onChange={() => setSelectedArtifacts(toggle(selectedArtifacts, a.id))} />{a.artifactType} / {a.reviewStatus}{a.withdrawn ? ' / withdrawn' : ''}</label><button onClick={() => void action(async () => { setArtifactReview(await knowledgeRequest<KnowledgeRecord>(knowledgePath(agent, `/artifacts/${a.id}`))); setAnswerKeyVerified(false); }, 'Artifact loaded for review.')}>Review content</button></div>)}
      {artifactReview && <><pre>{artifactReview.content}</pre><label><input type="checkbox" checked={answerKeyVerified} onChange={e => setAnswerKeyVerified(e.target.checked)} />A teacher has separately validated this practice answer key.</label><button disabled={!canManage || busy || !reason.trim() || !artifactReview.fingerprint} onClick={() => void action(() => knowledgeRequest(knowledgePath(agent, `/artifacts/${artifactReview.id}/approve`), 'POST', { expectedFingerprint: artifactReview.fingerprint, reason, answerKeyValidated: answerKeyVerified }), 'Derived material reviewed; include it in a later release.')}>Approve artifact</button></>}
    </section>
    <section className="ck-panel"><h3>4. Publish an exact release</h3><p>A candidate is a complete replacement manifest. Select every approved assignment and artifact that should remain in the next release.</p><button disabled={!canManage || busy || !selectedAssignments.length} onClick={() => void action(() => knowledgeRequest(knowledgePath(agent, '/releases'), 'POST', { courseId: course, curriculumId: curriculum, assignmentIds: selectedAssignments, artifactIds: selectedArtifacts }), 'Candidate verified. Review its contents before publication.')}>Build candidate release</button>
      {status.releases.filter(r => r.courseId === course && r.curriculumId === curriculum).map(r => <article key={r.id} className="ck-block"><strong>{r.id.slice(0, 8)} / {r.status}{status.heads.some(h => h.releaseId === r.id) ? ' / ACTIVE' : ''}</strong><pre>{JSON.stringify(r.manifest, null, 2)}</pre><button disabled={!canManage || busy || status.heads.some(h => h.releaseId === r.id)} onClick={() => void publish(r)}>Publish this exact release</button></article>)}
      <p>Published coverage is separate from processing: papers absent from the active manifest have no published paper material.</p>
    </section>
    <section className="ck-panel"><h3>5. Preview as an enrolled student</h3><label>Enrollment<select value={enrollment} onChange={e => selectEnrollment(e.target.value)}><option value="">Select enrollment</option>{status.enrollments.filter(e => e.courseId === course).map(e => <option key={e.id} value={e.id}>{e.studentId} / {e.status}</option>)}</select></label><label>Question<input value={query} onChange={e => setQuery(e.target.value)} /></label><button disabled={busy || !enrollment || !query} onClick={() => void action(async () => setPreview(await knowledgeRequest<StudentPreview>(knowledgePath(agent, '/preview'), 'POST', previewBody)), 'Student authorization preview completed.')}>Run the real student filter</button>
      {preview && <><p>{preview.notice}</p>{preview.evidence.map(e => <article key={e.entity_id} className="ck-block"><h4>{e.title}</h4><pre>{e.text}</pre><small>{JSON.stringify(e.metadata)}</small>{e.kind === 'course_chunk' && <button onClick={() => void action(async () => saveKnowledgeBlob(await knowledgeBlob(knowledgePath(agent, `/preview/excerpts/${e.entity_id}`), 'POST', previewBody), 'authorized-excerpt.txt'), 'Scoped excerpt downloaded.')}>Download only this authorized excerpt</button>}</article>)}</>}
    </section>
    <section className="ck-panel"><h3>Teacher review queue</h3><p>Low-confidence and ungrounded answers appear here. Resolving a review does not publish or alter course material.</p>{reviews.length === 0 && <p className="ck-empty">No academic reviews for this agent.</p>}{reviews.map(r => { const open = ['pending', 'open', 'assigned'].includes(r.status); return <article className="ck-block" key={r.id}><div className="ck-record-heading"><strong>{enrollmentLabel(r.enrollmentId)} · {paperLabel(r.paperId)}</strong><span className={`ck-state ck-state--${open ? 'attention' : 'complete'}`}>{r.status}</span></div><p><strong>Student question:</strong> {r.question}</p><details><summary>Answer and evidence</summary><p>{r.answer || 'No answer was delivered.'}</p><small>Reason: {r.reason} · Internal sources: {r.internalEvidence.length} · External sources: {r.externalEvidence.length}</small></details>{r.resolution && <p><strong>Resolution:</strong> {r.resolution}</p>}{open && <><label>Teacher resolution<textarea rows={3} value={reviewNotes[r.id] ?? ''} onChange={e => setReviewNotes(current => ({ ...current, [r.id]: e.target.value }))} placeholder="Record what was checked and the approved conclusion." /></label><div className="ck-actions"><button disabled={!canManage || busy || !reviewNote(r.id)} onClick={() => void resolveAcademicReview(r, 'confirmed')}>Confirm answer</button><button disabled={!canManage || busy || !reviewNote(r.id)} onClick={() => void resolveAcademicReview(r, 'corrected')}>Record correction</button></div></>}</article>; })}</section>
    <section className="ck-panel"><h3>Learning progress</h3><p>Activity indicators only; these values are not an exam-readiness score.</p>{progress.length === 0 && <p className="ck-empty">No paper practice has been recorded for this agent.</p>}{progress.map(item => { const percentage = item.objectiveAnswersGraded ? Math.round(item.objectiveAnswersCorrect / item.objectiveAnswersGraded * 100) : null; return <div className="ck-row ck-progress-row" key={item.id}><span><strong>{enrollmentLabel(item.enrollmentId)} · {paperLabel(item.paperId)}</strong><small>Student {item.studentId.slice(0, 8)} · {item.learningStatus.replaceAll('_', ' ')}</small></span><span className="ck-metrics"><strong>{percentage === null ? '—' : `${percentage}%`}</strong><small>{item.objectiveAnswersCorrect}/{item.objectiveAnswersGraded} graded correct · {item.practiceAttempts} attempts · {item.questionsAsked} questions</small></span></div>; })}</section>
    <section className="ck-panel"><h3>Tutor context diagnostics</h3><p>Resetting context clears remembered course and menu state; it does not change enrollment permission.</p>{contexts.length === 0 && <p className="ck-empty">No student has created tutor context for this agent.</p>}{contexts.map(item => <article className="ck-block" key={`${item.identityId}-${item.agentId}`}><div className="ck-record-heading"><strong>{enrollmentLabel(item.enrollmentId)}</strong><span className={`ck-state ck-state--${item.interactionState === 'ready_for_question' ? 'complete' : 'attention'}`}>{item.interactionState.replaceAll('_', ' ')}</span></div><small>Identity {item.identityId.slice(0, 8)} · revision {item.selectionRevision}{item.menuExpiresAt ? ` · menu expires ${new Date(item.menuExpiresAt).toLocaleString()}` : ''}</small>{item.pendingQuestion && <p><strong>Pending question:</strong> {item.pendingQuestion}</p>}<button disabled={!canManage || busy} onClick={() => { if (window.confirm('Reset this student’s remembered course and pending menu? Enrollment permissions will remain unchanged.')) void action(() => knowledgeRequest(`/education/tutor-contexts/${item.identityId}/${item.agentId}`, 'DELETE'), 'Tutor selection reset; authorization records were unchanged.'); }}>Reset remembered selection</button></article>)}</section>
  </div>;
}

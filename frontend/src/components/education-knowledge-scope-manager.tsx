import { BookOpen, Plus, ShieldCheck, Trash2 } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useToast } from '@/components/providers';
import { Badge, Button, Card, EmptyState, Field, Modal } from '@/components/ui';
import { educationApi } from '@/lib/education-api';
import { educationCatalogApi } from '@/lib/education-catalog-api';
import { educationKnowledgeApi, type EducationKnowledgeScope, type EducationKnowledgeScopeRef } from '@/lib/education-knowledge-api';
import { useApi } from '@/lib/use-api';
import type { KnowledgeSource } from '@/types';
import './education-knowledge-scope-manager.css';

interface Props { agentId: string; sources: KnowledgeSource[] }
interface ScopeDraft extends EducationKnowledgeScopeRef { key: string }

export function EducationKnowledgeScopeManager({ agentId, sources }: Props) {
  const { pushToast } = useToast();
  const sourceKey = sources.map((source) => source.id).sort().join(':');
  const courses = useApi(() => educationApi.courses.list({ status: 'active' }), [agentId]);
  const batches = useApi(() => educationApi.batches.list({ status: 'active' }), [agentId]);
  const curricula = useApi(() => educationCatalogApi.curricula(), [agentId]);
  const papers = useApi(() => educationCatalogApi.papers(), [agentId]);
  const scopes = useApi(async () => Object.fromEntries(await Promise.all(
    sources.map(async (source) => [source.id, await educationKnowledgeApi.sourceScopes(source.id)] as const),
  )) as Record<string, EducationKnowledgeScope[]>, [agentId, sourceKey]);
  const [editingSource, setEditingSource] = useState<KnowledgeSource | null>(null);
  const [draft, setDraft] = useState<ScopeDraft[]>([]);
  const [courseId, setCourseId] = useState('');
  const [curriculumId, setCurriculumId] = useState('');
  const [paperId, setPaperId] = useState('');
  const [batchId, setBatchId] = useState('');
  const [materialType, setMaterialType] = useState('notes');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const availableCurricula = useMemo(() => (curricula.data ?? []).filter((item) => item.courseId === courseId), [curricula.data, courseId]);
  const availablePapers = useMemo(() => (papers.data ?? []).filter((item) => item.curriculumId === curriculumId), [papers.data, curriculumId]);
  const availableBatches = useMemo(() => (batches.data ?? []).filter((batch) => batch.courseId === courseId && (!curriculumId || !batch.curriculumId || batch.curriculumId === curriculumId)), [batches.data, courseId, curriculumId]);
  const resetPicker = () => { setCourseId(''); setCurriculumId(''); setPaperId(''); setBatchId(''); setError(''); };
  const closeScope = () => { if (!saving) { setEditingSource(null); setDraft([]); resetPicker(); } };
  const openScope = (source: KnowledgeSource) => { setEditingSource(source); setDraft((scopes.data?.[source.id] ?? []).map((item) => ({ ...item, key: item.id }))); resetPicker(); };

  const addTuple = () => {
    if (!courseId || !curriculumId) { setError('Choose a Course and Curriculum.'); return; }
    if (draft.some((item) => item.courseId === courseId && item.curriculumId === curriculumId && (item.paperId ?? '') === paperId && (item.batchId ?? '') === batchId)) { setError('This course audience tuple is already selected.'); return; }
    setDraft((current) => [...current, { courseId, curriculumId, paperId: paperId || null, batchId: batchId || null, materialType, key: `${courseId}:${curriculumId}:${paperId}:${batchId}` }]);
    resetPicker();
  };
  const save = async () => {
    if (!editingSource) return;
    setSaving(true); setError('');
    try {
      await educationKnowledgeApi.setSourceScopes(editingSource.id, agentId, draft.map(({ key: _key, ...scope }) => scope));
      scopes.reload(); pushToast(draft.length ? 'Draft course mappings saved for review' : 'Source is unavailable to Education students');
      setEditingSource(null); setDraft([]); resetPicker();
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not save Education knowledge scope.'); }
    finally { setSaving(false); }
  };
  const scopeLabel = (scope: EducationKnowledgeScope | ScopeDraft) => {
    const course = courses.data?.find((item) => item.id === scope.courseId);
    const curriculum = curricula.data?.find((item) => item.id === scope.curriculumId);
    const paper = papers.data?.find((item) => item.id === scope.paperId);
    const batch = batches.data?.find((item) => item.id === scope.batchId);
    return [course?.code ?? 'Course', curriculum?.version ?? 'Curriculum', paper?.code ?? 'Overview', batch?.code ?? 'All batches'].join(' · ');
  };

  return <>
    <Card className="education-knowledge-scope-card">
      <div className="education-knowledge-scope-card__heading"><span><ShieldCheck /></span><div><h3>Education knowledge preparation</h3><p>Map source material to explicit course audiences, then review and publish it.</p></div></div>
      <div className="education-knowledge-scope-card__notice"><strong>Fail closed:</strong> unassigned, draft, or withdrawn material is unavailable to students.</div>
      {scopes.loading || courses.loading || batches.loading || curricula.loading || papers.loading ? <div className="table-loading">Loading Education scopes…</div> : sources.length ? <div className="education-knowledge-scope-list">{sources.map((source) => {
        const bindings = scopes.data?.[source.id] ?? [];
        return <div className="education-knowledge-scope-row" key={source.id}><div className="education-knowledge-scope-row__source"><strong>{source.name}</strong><small>{source.kind} · {source.chunks} chunks</small></div><div className="education-knowledge-scope-row__bindings">{bindings.length ? bindings.map((scope) => <Badge key={scope.id} tone={scope.approvalStatus === 'published' ? 'success' : scope.approvalStatus === 'withdrawn' ? 'danger' : 'purple'}>{scopeLabel(scope)} · {scope.approvalStatus ?? 'draft'}</Badge>) : <Badge tone="warning">Unassigned · blocked</Badge>}</div><Button variant="secondary" size="sm" onClick={() => openScope(source)}>Manage mappings</Button></div>;
      })}</div> : <EmptyState icon={BookOpen} title="No knowledge to map" description="Add a source with its intended Education destination before publishing." />}
    </Card>

    <Modal open={Boolean(editingSource)} onClose={closeScope} title={editingSource ? `Course mappings · ${editingSource.name}` : 'Course mappings'} description="Each row is an explicit Course, Curriculum, Paper, and Batch audience tuple. Course overview does not mean all papers." size="lg" footer={<><Button variant="secondary" disabled={saving} onClick={closeScope}>Cancel</Button><Button icon={ShieldCheck} disabled={saving} onClick={() => void save()}>{saving ? 'Saving…' : 'Save draft mappings'}</Button></>}>
      <div className="education-knowledge-scope-editor"><div className="education-knowledge-scope-editor__picker">
        <Field label="Course" htmlFor="education-knowledge-course"><select id="education-knowledge-course" value={courseId} onChange={(event) => { setCourseId(event.target.value); setCurriculumId(''); setPaperId(''); setBatchId(''); setError(''); }}><option value="">Choose Course</option>{(courses.data ?? []).map((course) => <option value={course.id} key={course.id}>{course.code} · {course.name}</option>)}</select></Field>
        <Field label="Curriculum" htmlFor="education-knowledge-curriculum"><select id="education-knowledge-curriculum" value={curriculumId} disabled={!courseId} onChange={(event) => { setCurriculumId(event.target.value); setPaperId(''); setBatchId(''); setError(''); }}><option value="">Choose Curriculum</option>{availableCurricula.map((item) => <option value={item.id} key={item.id}>{item.version} · {item.name}</option>)}</select></Field>
        <Field label="Paper" htmlFor="education-knowledge-paper"><select id="education-knowledge-paper" value={paperId} disabled={!curriculumId} onChange={(event) => setPaperId(event.target.value)}><option value="">Course overview</option>{availablePapers.map((item) => <option value={item.id} key={item.id}>{item.code} · {item.name}</option>)}</select></Field>
        <Field label="Audience" htmlFor="education-knowledge-batch"><select id="education-knowledge-batch" value={batchId} disabled={!curriculumId} onChange={(event) => setBatchId(event.target.value)}><option value="">All matching batches</option>{availableBatches.map((batch) => <option value={batch.id} key={batch.id}>{batch.code} · {batch.name}</option>)}</select></Field>
        <Field label="Material type" htmlFor="education-knowledge-material-type"><select id="education-knowledge-material-type" value={materialType} onChange={(event) => setMaterialType(event.target.value)}><option value="notes">Notes</option><option value="textbook">Textbook</option><option value="practice">Practice</option><option value="worked_examples">Worked examples</option></select></Field>
        <Button variant="secondary" icon={Plus} onClick={addTuple}>Add assignment</Button>
      </div>{error ? <p className="form-error" role="alert">{error}</p> : null}<div className="education-knowledge-scope-editor__selected">{draft.length ? draft.map((scope) => <div key={scope.key}><span>{scopeLabel(scope)}</span><button type="button" aria-label={`Remove ${scopeLabel(scope)}`} onClick={() => setDraft((current) => current.filter((item) => item.key !== scope.key))}><Trash2 /></button></div>) : <p>No assignment selected. This source will remain blocked from Education retrieval.</p>}</div></div>
    </Modal>
  </>;
}

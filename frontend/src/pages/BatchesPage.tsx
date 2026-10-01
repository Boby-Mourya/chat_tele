import { Archive, CalendarRange, Pencil, Plus, RotateCcw, Search } from 'lucide-react';
import { useMemo, useState, type FormEvent } from 'react';
import { useToast } from '@/components/providers';
import { Badge, Button, Card, EmptyState, Field, Modal, PageLoader } from '@/components/ui';
import {
  educationApi,
  type BatchStatus,
  type EducationBatch,
  type EducationCourse,
} from '@/lib/education-api';
import { relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';
import './BatchesPage.css';

type BatchFilter = 'all' | BatchStatus;

interface BatchFormState {
  courseId: string;
  code: string;
  name: string;
  description: string;
  startsOn: string;
  endsOn: string;
}

const emptyForm: BatchFormState = {
  courseId: '',
  code: '',
  name: '',
  description: '',
  startsOn: '',
  endsOn: '',
};

function formatDate(value: string | null): string {
  if (!value) return 'Open';
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(`${value}T00:00:00Z`));
}

export function BatchesPage() {
  const batches = useApi(() => educationApi.batches.list());
  const courses = useApi(() => educationApi.courses.list());
  const { pushToast } = useToast();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<BatchFilter>('all');
  const [courseFilter, setCourseFilter] = useState('all');
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<EducationBatch | null>(null);
  const [form, setForm] = useState<BatchFormState>(emptyForm);
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const [archiveTarget, setArchiveTarget] = useState<EducationBatch | null>(null);
  const [archiving, setArchiving] = useState(false);
  const [reactivating, setReactivating] = useState<string>();

  const courseById = useMemo(
    () => new Map((courses.data ?? []).map((course) => [course.id, course])),
    [courses.data],
  );
  const activeCourses = useMemo(
    () => (courses.data ?? []).filter((course) => course.status === 'active'),
    [courses.data],
  );
  const records = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (batches.data ?? []).filter((batch) => {
      const course = courseById.get(batch.courseId);
      const matchesStatus = status === 'all' || batch.status === status;
      const matchesCourse = courseFilter === 'all' || batch.courseId === courseFilter;
      const matchesSearch = !query || `${batch.code} ${batch.name} ${batch.description} ${course?.code ?? ''} ${course?.name ?? ''}`.toLowerCase().includes(query);
      return matchesStatus && matchesCourse && matchesSearch;
    });
  }, [batches.data, courseById, courseFilter, search, status]);

  const activeCount = (batches.data ?? []).filter((batch) => batch.status === 'active').length;
  const archivedCount = (batches.data ?? []).filter((batch) => batch.status === 'archived').length;

  const openCreate = () => {
    setEditing(null);
    setForm({ ...emptyForm, courseId: activeCourses[0]?.id ?? '' });
    setFormError('');
    setEditorOpen(true);
  };

  const openEdit = (batch: EducationBatch) => {
    setEditing(batch);
    setForm({
      courseId: batch.courseId,
      code: batch.code,
      name: batch.name,
      description: batch.description,
      startsOn: batch.startsOn ?? '',
      endsOn: batch.endsOn ?? '',
    });
    setFormError('');
    setEditorOpen(true);
  };

  const closeEditor = () => {
    if (saving) return;
    setEditorOpen(false);
    setEditing(null);
    setForm(emptyForm);
    setFormError('');
  };

  const submitBatch = async (event: FormEvent) => {
    event.preventDefault();
    const code = form.code.trim();
    const name = form.name.trim();
    if (!editing && !form.courseId) {
      setFormError('Choose an active course for this batch.');
      return;
    }
    if (!code) {
      setFormError('Batch code is required.');
      return;
    }
    if (name.length < 2) {
      setFormError('Batch name must contain at least 2 characters.');
      return;
    }
    if (form.startsOn && form.endsOn && form.endsOn < form.startsOn) {
      setFormError('Batch end date cannot be before start date.');
      return;
    }

    setSaving(true);
    setFormError('');
    try {
      if (editing) {
        await educationApi.batches.update(editing.id, {
          code,
          name,
          description: form.description,
          startsOn: form.startsOn || null,
          endsOn: form.endsOn || null,
        });
        pushToast(`${name} updated`);
      } else {
        await educationApi.batches.create({
          courseId: form.courseId,
          code,
          name,
          description: form.description,
          startsOn: form.startsOn || null,
          endsOn: form.endsOn || null,
        });
        pushToast(`${name} created`);
      }
      closeEditor();
      batches.reload();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Batch could not be saved.');
    } finally {
      setSaving(false);
    }
  };

  const archiveBatch = async () => {
    if (!archiveTarget) return;
    setArchiving(true);
    try {
      await educationApi.batches.archive(archiveTarget.id);
      pushToast(`${archiveTarget.name} archived`);
      setArchiveTarget(null);
      batches.reload();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Batch could not be archived', 'error');
    } finally {
      setArchiving(false);
    }
  };

  const reactivateBatch = async (batch: EducationBatch) => {
    setReactivating(batch.id);
    try {
      await educationApi.batches.update(batch.id, { status: 'active' });
      pushToast(`${batch.name} reactivated`);
      batches.reload();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Batch could not be reactivated', 'error');
    } finally {
      setReactivating(undefined);
    }
  };

  if ((batches.loading && !batches.data) || (courses.loading && !courses.data)) return <PageLoader />;
  const loadError = batches.error || courses.error;
  if (loadError) {
    return <div className="page batches-page"><Card><EmptyState
      icon={CalendarRange}
      title="Batches are unavailable"
      description={loadError}
      action={<Button onClick={() => { batches.reload(); courses.reload(); }}>Try again</Button>}
    /></Card></div>;
  }

  return <div className="page batches-page">
    <div className="page-heading page-heading--split">
      <div>
        <h2>Batches</h2>
        <p>Manage course cohorts and their access dates inside the active workspace.</p>
      </div>
      <Button icon={Plus} onClick={openCreate} disabled={!activeCourses.length}>Create batch</Button>
    </div>

    <div className="batch-stats" aria-label="Batch summary">
      <Card><span className="batch-stat-icon"><CalendarRange /></span><div><strong>{batches.data?.length ?? 0}</strong><small>Total batches</small></div></Card>
      <Card><span className="batch-stat-icon batch-stat-icon--active"><CalendarRange /></span><div><strong>{activeCount}</strong><small>Active</small></div></Card>
      <Card><span className="batch-stat-icon batch-stat-icon--archived"><Archive /></span><div><strong>{archivedCount}</strong><small>Archived</small></div></Card>
    </div>

    <Card className="batch-catalog-card">
      <div className="batch-toolbar">
        <div>
          <h3>Batch catalog</h3>
          <p>{records.length} shown · {batches.data?.length ?? 0} total</p>
        </div>
        <div className="batch-toolbar__filters">
          <label className="batch-search">
            <span className="sr-only">Search batches</span>
            <Search />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search batch or course"
              aria-label="Search batches"
            />
          </label>
          <label className="batch-select-filter">
            <span className="sr-only">Filter batches by course</span>
            <select
              value={courseFilter}
              onChange={(event) => setCourseFilter(event.target.value)}
              aria-label="Filter batches by course"
            >
              <option value="all">All courses</option>
              {(courses.data ?? []).map((course) => <option key={course.id} value={course.id}>{course.code} · {course.name}</option>)}
            </select>
          </label>
          <label className="batch-select-filter">
            <span className="sr-only">Filter batches by status</span>
            <select
              value={status}
              onChange={(event) => setStatus(event.target.value as BatchFilter)}
              aria-label="Filter batches by status"
            >
              <option value="all">All statuses</option>
              <option value="active">Active</option>
              <option value="archived">Archived</option>
            </select>
          </label>
        </div>
      </div>

      {records.length ? <div className="batch-table-wrap"><table className="batch-table">
        <thead><tr><th>Code</th><th>Batch</th><th>Course</th><th>Access dates</th><th>Status</th><th>Updated</th><th><span className="sr-only">Actions</span></th></tr></thead>
        <tbody>{records.map((batch) => {
          const course = courseById.get(batch.courseId);
          return <tr key={batch.id}>
            <td><code>{batch.code}</code></td>
            <td><strong>{batch.name}</strong><small>{batch.description || 'No description'}</small></td>
            <td><strong>{course?.code ?? 'Unknown course'}</strong><small>{course?.name ?? batch.courseId}</small></td>
            <td><span>{formatDate(batch.startsOn)}</span><small>to {formatDate(batch.endsOn)}</small></td>
            <td><Badge tone={batch.status === 'active' ? 'success' : 'neutral'}>{batch.status}</Badge></td>
            <td><time dateTime={batch.updatedAt}>{relativeTime(batch.updatedAt)}</time></td>
            <td><div className="batch-actions">
              <Button variant="secondary" size="sm" icon={Pencil} onClick={() => openEdit(batch)}>Edit</Button>
              {batch.status === 'active'
                ? <Button variant="ghost" size="sm" icon={Archive} onClick={() => setArchiveTarget(batch)}>Archive</Button>
                : <Button
                    variant="secondary"
                    size="sm"
                    icon={RotateCcw}
                    disabled={reactivating === batch.id}
                    onClick={() => void reactivateBatch(batch)}
                  >Reactivate</Button>}
            </div></td>
          </tr>;
        })}</tbody>
      </table></div> : <EmptyState
        icon={CalendarRange}
        title={batches.data?.length ? 'No matching batches' : activeCourses.length ? 'Create your first batch' : 'Create an active course first'}
        description={batches.data?.length
          ? 'Try another search, course, or status filter.'
          : activeCourses.length
            ? 'Batches organize students within a course and provide durable access-date boundaries for future enrollments.'
            : 'A batch must belong to an active course. Create or reactivate a course before adding batches.'}
        action={!batches.data?.length && activeCourses.length ? <Button icon={Plus} onClick={openCreate}>Create batch</Button> : undefined}
      />}
    </Card>

    <Modal
      open={editorOpen}
      onClose={closeEditor}
      title={editing ? 'Edit batch' : 'Create batch'}
      description={editing
        ? 'The parent course is fixed after batch creation to protect future enrollment references.'
        : 'Batch codes are normalized and unique inside the active workspace.'}
      closeDisabled={saving}
      footer={<>
        <Button variant="secondary" onClick={closeEditor} disabled={saving}>Cancel</Button>
        <Button type="submit" form="batch-editor-form" disabled={saving}>{saving ? 'Saving…' : editing ? 'Save changes' : 'Create batch'}</Button>
      </>}
    >
      <form id="batch-editor-form" className="batch-editor" noValidate onSubmit={(event) => void submitBatch(event)}>
        <Field label="Course" htmlFor="batch-course" hint={editing ? 'Course cannot be changed after creation.' : 'Only active courses can receive new batches.'}>
          <select
            id="batch-course"
            value={form.courseId}
            disabled={Boolean(editing)}
            onChange={(event) => setForm((current) => ({ ...current, courseId: event.target.value }))}
          >
            {!form.courseId ? <option value="">Select course</option> : null}
            {(editing ? (courses.data ?? []).filter((course) => course.id === form.courseId) : activeCourses)
              .map((course: EducationCourse) => <option key={course.id} value={course.id}>{course.code} · {course.name}</option>)}
          </select>
        </Field>
        <div className="two-fields">
          <Field label="Batch code" htmlFor="batch-code" hint="Example: CPA-2026-A">
            <input
              id="batch-code"
              value={form.code}
              maxLength={40}
              onChange={(event) => setForm((current) => ({ ...current, code: event.target.value.toUpperCase() }))}
              placeholder="CPA-2026-A"
              autoComplete="off"
            />
          </Field>
          <Field label="Batch name" htmlFor="batch-name">
            <input
              id="batch-name"
              value={form.name}
              maxLength={160}
              onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              placeholder="CPA 2026 Cohort A"
              autoComplete="off"
            />
          </Field>
        </div>
        <div className="two-fields">
          <Field label="Start date" htmlFor="batch-starts-on" hint="Optional">
            <input
              id="batch-starts-on"
              type="date"
              value={form.startsOn}
              onChange={(event) => setForm((current) => ({ ...current, startsOn: event.target.value }))}
            />
          </Field>
          <Field label="End date" htmlFor="batch-ends-on" hint="Optional">
            <input
              id="batch-ends-on"
              type="date"
              min={form.startsOn || undefined}
              value={form.endsOn}
              onChange={(event) => setForm((current) => ({ ...current, endsOn: event.target.value }))}
            />
          </Field>
        </div>
        <Field label="Description" htmlFor="batch-description" hint="Optional. Describe the cohort, schedule, or intake.">
          <textarea
            id="batch-description"
            rows={4}
            maxLength={2000}
            value={form.description}
            onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
            placeholder="Morning cohort"
          />
        </Field>
        {formError ? <p className="batch-form-error" role="alert">{formError}</p> : null}
      </form>
    </Modal>

    <Modal
      open={Boolean(archiveTarget)}
      onClose={() => { if (!archiving) setArchiveTarget(null); }}
      title="Archive batch?"
      description="Archiving removes the batch from active selection without deleting its durable record."
      size="sm"
      closeDisabled={archiving}
      footer={<>
        <Button variant="secondary" disabled={archiving} onClick={() => setArchiveTarget(null)}>Cancel</Button>
        <Button variant="danger" disabled={archiving} onClick={() => void archiveBatch()}>{archiving ? 'Archiving…' : 'Archive batch'}</Button>
      </>}
    >
      <p className="batch-archive-copy">{archiveTarget ? <><strong>{archiveTarget.code}</strong> · {archiveTarget.name}</> : null}</p>
    </Modal>
  </div>;
}

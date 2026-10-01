import { Archive, BookOpen, Pencil, Plus, RotateCcw, Search } from 'lucide-react';
import { useMemo, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useToast } from '@/components/providers';
import { Badge, Button, Card, EmptyState, Field, Modal, PageLoader } from '@/components/ui';
import {
  educationApi,
  type CourseStatus,
  type EducationCourse,
} from '@/lib/education-api';
import { relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';
import './CoursesPage.css';

type CourseFilter = 'all' | CourseStatus;

interface CourseFormState {
  code: string;
  name: string;
  description: string;
}

const emptyForm: CourseFormState = { code: '', name: '', description: '' };

export function CoursesPage() {
  const courses = useApi(() => educationApi.courses.list());
  const { pushToast } = useToast();
  const [params] = useSearchParams();
  const [search, setSearch] = useState(() => params.get('search') ?? '');
  const [status, setStatus] = useState<CourseFilter>('all');
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<EducationCourse | null>(null);
  const [form, setForm] = useState<CourseFormState>(emptyForm);
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const [archiveTarget, setArchiveTarget] = useState<EducationCourse | null>(null);
  const [archiving, setArchiving] = useState(false);
  const [reactivating, setReactivating] = useState<string>();

  const records = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (courses.data ?? []).filter((course) => {
      const matchesStatus = status === 'all' || course.status === status;
      const matchesSearch = !query || `${course.code} ${course.name} ${course.description}`.toLowerCase().includes(query);
      return matchesStatus && matchesSearch;
    });
  }, [courses.data, search, status]);

  const activeCount = (courses.data ?? []).filter((course) => course.status === 'active').length;
  const archivedCount = (courses.data ?? []).filter((course) => course.status === 'archived').length;

  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm);
    setFormError('');
    setEditorOpen(true);
  };

  const openEdit = (course: EducationCourse) => {
    setEditing(course);
    setForm({ code: course.code, name: course.name, description: course.description });
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

  const submitCourse = async (event: FormEvent) => {
    event.preventDefault();
    const code = form.code.trim();
    const name = form.name.trim();
    if (!code) {
      setFormError('Course code is required.');
      return;
    }
    if (name.length < 2) {
      setFormError('Course name must contain at least 2 characters.');
      return;
    }
    setSaving(true);
    setFormError('');
    try {
      if (editing) {
        await educationApi.courses.update(editing.id, {
          code,
          name,
          description: form.description,
        });
        pushToast(`${name} updated`);
      } else {
        await educationApi.courses.create({ code, name, description: form.description });
        pushToast(`${name} created`);
      }
      closeEditor();
      courses.reload();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Course could not be saved.');
    } finally {
      setSaving(false);
    }
  };

  const archiveCourse = async () => {
    if (!archiveTarget) return;
    setArchiving(true);
    try {
      await educationApi.courses.archive(archiveTarget.id);
      pushToast(`${archiveTarget.name} archived`);
      setArchiveTarget(null);
      courses.reload();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Course could not be archived', 'error');
    } finally {
      setArchiving(false);
    }
  };

  const reactivateCourse = async (course: EducationCourse) => {
    setReactivating(course.id);
    try {
      await educationApi.courses.update(course.id, { status: 'active' });
      pushToast(`${course.name} reactivated`);
      courses.reload();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Course could not be reactivated', 'error');
    } finally {
      setReactivating(undefined);
    }
  };

  if (courses.loading && !courses.data) return <PageLoader />;
  if (courses.error) {
    return <div className="page courses-page"><Card><EmptyState
      icon={BookOpen}
      title="Courses are unavailable"
      description={courses.error}
      action={<Button onClick={courses.reload}>Try again</Button>}
    /></Card></div>;
  }

  return <div className="page courses-page">
    <div className="page-heading page-heading--split">
      <div>
        <h2>Courses</h2>
        <p>Manage the workspace course catalog that Education batches and enrollments will reference.</p>
      </div>
      <Button icon={Plus} onClick={openCreate}>Create course</Button>
    </div>

    <div className="course-stats" aria-label="Course summary">
      <Card><span className="course-stat-icon"><BookOpen /></span><div><strong>{courses.data?.length ?? 0}</strong><small>Total courses</small></div></Card>
      <Card><span className="course-stat-icon course-stat-icon--active"><BookOpen /></span><div><strong>{activeCount}</strong><small>Active</small></div></Card>
      <Card><span className="course-stat-icon course-stat-icon--archived"><Archive /></span><div><strong>{archivedCount}</strong><small>Archived</small></div></Card>
    </div>

    <Card className="course-catalog-card">
      <div className="course-toolbar">
        <div>
          <h3>Course catalog</h3>
          <p>{records.length} shown · {courses.data?.length ?? 0} total</p>
        </div>
        <div className="course-toolbar__filters">
          <label className="course-search">
            <span className="sr-only">Search courses</span>
            <Search />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search code, name, or description"
              aria-label="Search courses"
            />
          </label>
          <label className="course-status-filter">
            <span className="sr-only">Filter courses by status</span>
            <select
              value={status}
              onChange={(event) => setStatus(event.target.value as CourseFilter)}
              aria-label="Filter courses by status"
            >
              <option value="all">All statuses</option>
              <option value="active">Active</option>
              <option value="archived">Archived</option>
            </select>
          </label>
        </div>
      </div>

      {records.length ? <div className="course-table-wrap"><table className="course-table">
        <thead><tr><th>Code</th><th>Course</th><th>Status</th><th>Updated</th><th><span className="sr-only">Actions</span></th></tr></thead>
        <tbody>{records.map((course) => <tr key={course.id}>
          <td><code>{course.code}</code></td>
          <td><strong>{course.name}</strong><small>{course.description || 'No description'}</small></td>
          <td><Badge tone={course.status === 'active' ? 'success' : 'neutral'}>{course.status}</Badge></td>
          <td><time dateTime={course.updatedAt}>{relativeTime(course.updatedAt)}</time></td>
          <td><div className="course-actions">
            <Button variant="secondary" size="sm" icon={Pencil} onClick={() => openEdit(course)}>Edit</Button>
            {course.status === 'active'
              ? <Button variant="ghost" size="sm" icon={Archive} onClick={() => setArchiveTarget(course)}>Archive</Button>
              : <Button
                  variant="secondary"
                  size="sm"
                  icon={RotateCcw}
                  disabled={reactivating === course.id}
                  onClick={() => void reactivateCourse(course)}
                >Reactivate</Button>}
          </div></td>
        </tr>)}</tbody>
      </table></div> : <EmptyState
        icon={BookOpen}
        title={courses.data?.length ? 'No matching courses' : 'Create your first course'}
        description={courses.data?.length
          ? 'Try another search or status filter.'
          : 'Courses are the first Education catalog layer. Batches and student enrollments will be added separately after this feature is complete.'}
        action={!courses.data?.length ? <Button icon={Plus} onClick={openCreate}>Create course</Button> : undefined}
      />}
    </Card>

    <Modal
      open={editorOpen}
      onClose={closeEditor}
      title={editing ? 'Edit course' : 'Create course'}
      description="Course codes are normalized and unique inside the active workspace."
      closeDisabled={saving}
      footer={<>
        <Button variant="secondary" onClick={closeEditor} disabled={saving}>Cancel</Button>
        <Button type="submit" form="course-editor-form" disabled={saving}>{saving ? 'Saving…' : editing ? 'Save changes' : 'Create course'}</Button>
      </>}
    >
      <form id="course-editor-form" className="course-editor" onSubmit={(event) => void submitCourse(event)}>
        <div className="two-fields">
          <Field label="Course code" htmlFor="course-code" hint="Example: CMA-P1">
            <input
              id="course-code"
              value={form.code}
              maxLength={40}
              onChange={(event) => setForm((current) => ({ ...current, code: event.target.value.toUpperCase() }))}
              placeholder="CMA-P1"
              autoComplete="off"
            />
          </Field>
          <Field label="Course name" htmlFor="course-name">
            <input
              id="course-name"
              value={form.name}
              maxLength={160}
              onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              placeholder="CMA Part 1"
              autoComplete="off"
            />
          </Field>
        </div>
        <Field label="Description" htmlFor="course-description" hint="Optional. Describe what this course represents in your academy.">
          <textarea
            id="course-description"
            rows={5}
            maxLength={2000}
            value={form.description}
            onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
            placeholder="Course catalog description"
          />
        </Field>
        {formError ? <p className="course-form-error" role="alert">{formError}</p> : null}
      </form>
    </Modal>

    <Modal
      open={Boolean(archiveTarget)}
      onClose={() => { if (!archiving) setArchiveTarget(null); }}
      title="Archive course?"
      description="Archiving removes the course from active selection without deleting its durable record."
      size="sm"
      closeDisabled={archiving}
      footer={<>
        <Button variant="secondary" disabled={archiving} onClick={() => setArchiveTarget(null)}>Cancel</Button>
        <Button variant="danger" disabled={archiving} onClick={() => void archiveCourse()}>{archiving ? 'Archiving…' : 'Archive course'}</Button>
      </>}
    >
      <p className="course-archive-copy">{archiveTarget ? <><strong>{archiveTarget.code}</strong> · {archiveTarget.name}</> : null}</p>
    </Modal>
  </div>;
}

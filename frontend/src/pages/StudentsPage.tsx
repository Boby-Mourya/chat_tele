import { Archive, GraduationCap, Link2, Pencil, Plus, RotateCcw, Search, UserRound, X } from 'lucide-react';
import { useMemo, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { StudentEnrollmentsModal } from '@/components/student-enrollments-modal';
import { StudentIdentitiesModal } from '@/components/student-identities-modal';
import { useToast } from '@/components/providers';
import { Badge, Button, Card, EmptyState, Field, Modal, PageLoader } from '@/components/ui';
import {
  educationStudentApi,
  type EducationStudent,
  type StudentCustomFields,
  type StudentStatus,
} from '@/lib/education-student-api';
import { relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';
import './StudentsPage.css';

type StudentFilter = 'all' | StudentStatus;

interface CustomFieldRow {
  id: string;
  key: string;
  value: string;
}

interface StudentFormState {
  whatsappNumber: string;
  whatsappVerified: boolean;
  telegramPhoneNumber: string;
  telegramPhoneVerified: boolean;
  studentNumber: string;
  name: string;
  email: string;
  customFields: CustomFieldRow[];
}

const emptyForm: StudentFormState = {
  whatsappNumber: '',
  whatsappVerified: false,
  telegramPhoneNumber: '',
  telegramPhoneVerified: false,
  studentNumber: '',
  name: '',
  email: '',
  customFields: [],
};

function rowId(): string {
  return crypto.randomUUID?.() ?? Math.random().toString(36).slice(2);
}

function rowsFromFields(fields: StudentCustomFields): CustomFieldRow[] {
  return Object.entries(fields).map(([key, value]) => ({ id: rowId(), key, value: String(value ?? '') }));
}

function fieldsFromRows(rows: CustomFieldRow[]): StudentCustomFields {
  return Object.fromEntries(
    rows
      .map((row) => [row.key.trim(), row.value.trim()] as const)
      .filter(([key]) => Boolean(key)),
  );
}

export function StudentsPage() {
  const students = useApi(() => educationStudentApi.list());
  const { pushToast } = useToast();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<StudentFilter>('all');
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<EducationStudent | null>(null);
  const [identityStudent, setIdentityStudent] = useState<EducationStudent | null>(null);
  const [enrollmentStudent, setEnrollmentStudent] = useState<EducationStudent | null>(null);
  const [form, setForm] = useState<StudentFormState>(emptyForm);
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const [archiveTarget, setArchiveTarget] = useState<EducationStudent | null>(null);
  const [archiving, setArchiving] = useState(false);
  const [reactivating, setReactivating] = useState<string>();

  const records = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (students.data ?? []).filter((student) => {
      const matchesStatus = status === 'all' || student.status === status;
      const custom = Object.entries(student.customFields)
        .map(([key, value]) => `${key} ${String(value ?? '')}`)
        .join(' ');
      const matchesSearch = !query
        || `${student.studentNumber} ${student.name} ${student.email ?? ''} ${student.whatsappNumber ?? ''} ${student.telegramPhoneNumber ?? ''} ${custom}`.toLowerCase().includes(query);
      return matchesStatus && matchesSearch;
    });
  }, [search, status, students.data]);

  const activeCount = (students.data ?? []).filter((student) => student.status === 'active').length;
  const archivedCount = (students.data ?? []).filter((student) => student.status === 'archived').length;

  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm);
    setFormError('');
    setEditorOpen(true);
  };

  const openEdit = (student: EducationStudent) => {
    setEditing(student);
    setForm({
      whatsappNumber: student.whatsappNumber ?? '',
      whatsappVerified: student.whatsappVerified ?? false,
      telegramPhoneNumber: student.telegramPhoneNumber ?? '',
      telegramPhoneVerified: student.telegramPhoneVerified ?? false,
      studentNumber: student.studentNumber,
      name: student.name,
      email: student.email ?? '',
      customFields: rowsFromFields(student.customFields),
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

  const submitStudent = async (event: FormEvent) => {
    event.preventDefault();
    const studentNumber = form.studentNumber.trim();
    const name = form.name.trim().replace(/\s+/g, ' ');
    const email = form.email.trim().toLowerCase();
    const customFields = fieldsFromRows(form.customFields);
    if (!studentNumber) {
      setFormError('Student ID is required.');
      return;
    }
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(studentNumber)) {
      setFormError('Student ID may only use letters, numbers, dots, dashes, or underscores.');
      return;
    }
    if (name.length < 2) {
      setFormError('Student name must contain at least 2 characters.');
      return;
    }
    if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setFormError('Enter a valid email address.');
      return;
    }
    const keys = form.customFields.map((row) => row.key.trim()).filter(Boolean);
    if (new Set(keys.map((key) => key.toLowerCase())).size !== keys.length) {
      setFormError('Custom field names must be unique.');
      return;
    }
    if (form.customFields.some((row) => !row.key.trim() && row.value.trim())) {
      setFormError('Add a name for every custom field value.');
      return;
    }

    setSaving(true);
    setFormError('');
    try {
      if (editing) {
        await educationStudentApi.update(editing.id, {
          studentNumber,
          name,
          email: email || null,
          whatsappNumber: form.whatsappNumber.trim() || null,
          whatsappVerified: form.whatsappVerified,
          telegramPhoneNumber: form.telegramPhoneNumber.trim() || null,
          telegramPhoneVerified: Boolean(form.telegramPhoneNumber.trim() && form.telegramPhoneVerified),
          customFields,
        });
        pushToast(`${name} updated`);
      } else {
        await educationStudentApi.create({
          studentNumber,
          name,
          email: email || null,
          whatsappNumber: form.whatsappNumber.trim() || null,
          whatsappVerified: form.whatsappVerified,
          telegramPhoneNumber: form.telegramPhoneNumber.trim() || null,
          telegramPhoneVerified: Boolean(form.telegramPhoneNumber.trim() && form.telegramPhoneVerified),
          customFields,
        });
        pushToast(`${name} created`);
      }
      closeEditor();
      students.reload();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Student could not be saved.');
    } finally {
      setSaving(false);
    }
  };

  const archiveStudent = async () => {
    if (!archiveTarget) return;
    setArchiving(true);
    try {
      await educationStudentApi.archive(archiveTarget.id);
      pushToast(`${archiveTarget.name} archived`);
      setArchiveTarget(null);
      students.reload();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Student could not be archived', 'error');
    } finally {
      setArchiving(false);
    }
  };

  const reactivateStudent = async (student: EducationStudent) => {
    setReactivating(student.id);
    try {
      await educationStudentApi.update(student.id, { status: 'active' });
      pushToast(`${student.name} reactivated`);
      students.reload();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Student could not be reactivated', 'error');
    } finally {
      setReactivating(undefined);
    }
  };

  const addCustomField = () => {
    if (form.customFields.length >= 50) return;
    setForm((current) => ({
      ...current,
      customFields: [...current.customFields, { id: rowId(), key: '', value: '' }],
    }));
  };

  const updateCustomField = (id: string, field: 'key' | 'value', value: string) => {
    setForm((current) => ({
      ...current,
      customFields: current.customFields.map((row) => row.id === id ? { ...row, [field]: value } : row),
    }));
  };

  const removeCustomField = (id: string) => {
    setForm((current) => ({
      ...current,
      customFields: current.customFields.filter((row) => row.id !== id),
    }));
  };

  if (students.loading && !students.data) return <PageLoader />;
  if (students.error) {
    return <div className="page students-page"><Card><EmptyState
      icon={UserRound}
      title="Students are unavailable"
      description={students.error}
      action={<Button onClick={students.reload}>Try again</Button>}
    /></Card></div>;
  }

  return <div className="page students-page">
    <div className="page-heading page-heading--split">
      <div>
        <h2>Students</h2>
        <p>Manage durable student profiles, verified channel identities, and Course/Batch/Agent enrollment access in the active workspace.</p>
      </div>
      <Button icon={Plus} onClick={openCreate}>Add student</Button>
    </div>

    <div className="student-stats" aria-label="Student summary">
      <Card><span className="student-stat-icon"><UserRound /></span><div><strong>{students.data?.length ?? 0}</strong><small>Total students</small></div></Card>
      <Card><span className="student-stat-icon student-stat-icon--active"><UserRound /></span><div><strong>{activeCount}</strong><small>Active</small></div></Card>
      <Card><span className="student-stat-icon student-stat-icon--archived"><Archive /></span><div><strong>{archivedCount}</strong><small>Archived</small></div></Card>
    </div>

    <Card className="student-directory-card">
      <div className="student-toolbar">
        <div>
          <h3>Student directory</h3>
          <p>{records.length} shown · {students.data?.length ?? 0} total</p>
        </div>
        <div className="student-toolbar__filters">
          <label className="student-search">
            <span className="sr-only">Search students</span>
            <Search />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search ID, name, email, or custom field"
              aria-label="Search students"
            />
          </label>
          <label className="student-status-filter">
            <span className="sr-only">Filter students by status</span>
            <select
              value={status}
              onChange={(event) => setStatus(event.target.value as StudentFilter)}
              aria-label="Filter students by status"
            >
              <option value="all">All statuses</option>
              <option value="active">Active</option>
              <option value="archived">Archived</option>
            </select>
          </label>
        </div>
      </div>

      {records.length ? <div className="student-table-wrap"><table className="student-table">
        <thead><tr><th>Student ID</th><th>Student</th><th>Custom fields</th><th>Status</th><th>Updated</th><th><span className="sr-only">Actions</span></th></tr></thead>
        <tbody>{records.map((student) => <tr key={student.id}>
          <td><code>{student.studentNumber}</code></td>
          <td><strong>{student.name}</strong><small>{student.email || 'No email'}</small><small>WhatsApp: {student.whatsappNumber || 'Not added'}{student.whatsappNumber ? student.whatsappVerified ? ' - Verified' : ' - Verification needed' : ''}</small><small>Telegram: {student.telegramPhoneNumber || 'Not added'}{student.telegramPhoneNumber ? student.telegramVerified ? ' - Account linked' : student.telegramPhoneVerified ? ' - Phone verified; account not linked' : ' - Verification needed' : ''}</small></td>
          <td>{Object.keys(student.customFields).length
            ? <div className="student-custom-summary">{Object.entries(student.customFields).slice(0, 3).map(([key, value]) => <span key={key}><b>{key}</b>: {String(value ?? '')}</span>)}</div>
            : <span className="student-muted">None</span>}</td>
          <td><Badge tone={student.status === 'active' ? 'success' : 'neutral'}>{student.status}</Badge></td>
          <td><time dateTime={student.updatedAt}>{relativeTime(student.updatedAt)}</time></td>
          <td><div className="student-actions">
            <Link className="button button--secondary button--sm" to={`/education/students/${student.id}`}>Details</Link>
            <Button variant="secondary" size="sm" icon={Link2} onClick={() => setIdentityStudent(student)}>Identities</Button>
            <Button variant="secondary" size="sm" icon={GraduationCap} onClick={() => setEnrollmentStudent(student)}>Enrollments</Button>
            <Button variant="secondary" size="sm" icon={Pencil} onClick={() => openEdit(student)}>Edit</Button>
            {student.status === 'active'
              ? <Button variant="ghost" size="sm" icon={Archive} onClick={() => setArchiveTarget(student)}>Archive</Button>
              : <Button
                  variant="secondary"
                  size="sm"
                  icon={RotateCcw}
                  disabled={reactivating === student.id}
                  onClick={() => void reactivateStudent(student)}
                >Reactivate</Button>}
          </div></td>
        </tr>)}</tbody>
      </table></div> : <EmptyState
        icon={UserRound}
        title={students.data?.length ? 'No matching students' : 'Add your first student'}
        description={students.data?.length
          ? 'Try another search or status filter.'
          : 'Create a durable Student profile, then link identities and assign Course/Batch/Agent enrollment access.'}
        action={!students.data?.length ? <Button icon={Plus} onClick={openCreate}>Add student</Button> : undefined}
      />}
    </Card>

    <StudentIdentitiesModal
      student={identityStudent}
      open={Boolean(identityStudent)}
      onClose={() => { setIdentityStudent(null); students.reload(); }}
    />

    <StudentEnrollmentsModal
      student={enrollmentStudent}
      open={Boolean(enrollmentStudent)}
      onClose={() => setEnrollmentStudent(null)}
    />

    <Modal
      open={editorOpen}
      onClose={closeEditor}
      title={editing ? 'Edit student' : 'Add student'}
      description="Student IDs are normalized and unique inside the active workspace."
      closeDisabled={saving}
      footer={<>
        <Button variant="secondary" onClick={closeEditor} disabled={saving}>Cancel</Button>
        <Button type="submit" form="student-editor-form" disabled={saving}>{saving ? 'Saving…' : editing ? 'Save changes' : 'Add student'}</Button>
      </>}
    >
      <form id="student-editor-form" className="student-editor" noValidate onSubmit={(event) => void submitStudent(event)}>
        <div className="two-fields">
          <Field label="Student ID" htmlFor="student-number" hint="Example: NS-1001">
            <input
              id="student-number"
              value={form.studentNumber}
              maxLength={80}
              onChange={(event) => setForm((current) => ({ ...current, studentNumber: event.target.value.toUpperCase() }))}
              placeholder="NS-1001"
              autoComplete="off"
            />
          </Field>
          <Field label="Student name" htmlFor="student-name">
            <input
              id="student-name"
              value={form.name}
              maxLength={160}
              onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              placeholder="Asha Verma"
              autoComplete="name"
            />
          </Field>
        </div>
        <Field label="Student WhatsApp number" htmlFor="student-whatsapp" hint="Include the country code, e.g. +919876543210. Use the student's number, not the bot's business number.">
          <input id="student-whatsapp" type="tel" value={form.whatsappNumber} maxLength={40} placeholder="+919876543210" onChange={(event) => setForm((current) => ({ ...current, whatsappNumber: event.target.value, whatsappVerified: false }))} />
        </Field>
        {form.whatsappNumber.trim() ? <label><input type="checkbox" checked={form.whatsappVerified} onChange={(event) => setForm((current) => ({ ...current, whatsappVerified: event.target.checked }))} /> I have confirmed this WhatsApp number belongs to this student.</label> : null}
        <p>A verified number and an active Course / Batch / Bot enrollment are required for WhatsApp course access.</p>
        <Field label="Student Telegram phone number" htmlFor="student-telegram-phone" hint="Enter the phone number registered with Telegram, including country code (e.g. +919876543210).">
          <input id="student-telegram-phone" type="tel" value={form.telegramPhoneNumber} maxLength={40} placeholder="+919876543210" autoComplete="off" onChange={(event) => setForm((current) => ({ ...current, telegramPhoneNumber: event.target.value, telegramPhoneVerified: false }))} />
        </Field>
        {form.telegramPhoneNumber.trim() ? <label><input type="checkbox" checked={form.telegramPhoneVerified} onChange={(event) => setForm((current) => ({ ...current, telegramPhoneVerified: event.target.checked }))} /> I have confirmed this Telegram phone number belongs to this student.</label> : null}
        <p>Save changes to confirm the number. The student shares their phone number once in the bot to link their Telegram account. Course answers require an active enrollment.</p>
        <Field label="Email" htmlFor="student-email" hint="Optional profile contact. Login/channel identities are managed separately.">
          <input
            id="student-email"
            type="email"
            value={form.email}
            maxLength={320}
            onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))}
            placeholder="asha@example.com"
            autoComplete="email"
          />
        </Field>

        <div className="student-custom-fields">
          <div className="student-custom-fields__header">
            <div><strong>Custom fields</strong><small>Optional profile metadata. Up to 50 scalar values.</small></div>
            <Button type="button" variant="secondary" size="sm" icon={Plus} onClick={addCustomField} disabled={form.customFields.length >= 50}>Add field</Button>
          </div>
          {form.customFields.length ? <div className="student-custom-fields__rows">
            {form.customFields.map((row) => <div className="student-custom-row" key={row.id}>
              <input
                aria-label="Custom field name"
                value={row.key}
                maxLength={80}
                onChange={(event) => updateCustomField(row.id, 'key', event.target.value)}
                placeholder="Field name"
              />
              <input
                aria-label="Custom field value"
                value={row.value}
                onChange={(event) => updateCustomField(row.id, 'value', event.target.value)}
                placeholder="Value"
              />
              <button type="button" onClick={() => removeCustomField(row.id)} aria-label="Remove custom field"><X /></button>
            </div>)}
          </div> : <p className="student-custom-empty">No custom fields yet.</p>}
        </div>
        {formError ? <p className="student-form-error" role="alert">{formError}</p> : null}
      </form>
    </Modal>

    <Modal
      open={Boolean(archiveTarget)}
      onClose={() => { if (!archiving) setArchiveTarget(null); }}
      title="Archive student?"
      description="Archiving removes the student from active selection without deleting the durable profile."
      size="sm"
      closeDisabled={archiving}
      footer={<>
        <Button variant="secondary" disabled={archiving} onClick={() => setArchiveTarget(null)}>Cancel</Button>
        <Button variant="danger" disabled={archiving} onClick={() => void archiveStudent()}>{archiving ? 'Archiving…' : 'Archive student'}</Button>
      </>}
    >
      <p className="student-archive-copy">{archiveTarget ? <><strong>{archiveTarget.studentNumber}</strong> · {archiveTarget.name}</> : null}</p>
    </Modal>
  </div>;
}

import { Link2, Plus, RotateCcw, ShieldCheck, ShieldX, Star } from 'lucide-react';
import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { useToast } from '@/components/providers';
import { Badge, Button, Field, Modal, Switch } from '@/components/ui';
import {
  educationStudentIdentityApi,
  type EducationStudentIdentity,
  type StudentIdentityStatus,
  type StudentIdentityType,
} from '@/lib/education-student-identity-api';
import type { EducationStudent } from '@/lib/education-student-api';
import './student-identities-modal.css';

interface StudentIdentitiesModalProps {
  student: EducationStudent | null;
  open: boolean;
  onClose: () => void;
}

interface IdentityFormState {
  identityType: StudentIdentityType;
  identifier: string;
  label: string;
  verified: boolean;
  primary: boolean;
}

const emptyForm: IdentityFormState = {
  identityType: 'whatsapp',
  identifier: '',
  label: '',
  verified: false,
  primary: false,
};

const identityLabels: Record<StudentIdentityType, string> = {
  whatsapp: 'WhatsApp',
  telegram: 'Telegram',
  website_login: 'Website login',
  alternate_phone: 'Alternate phone',
};

function placeholderFor(type: StudentIdentityType): string {
  if (type === 'telegram') return '123456789';
  if (type === 'website_login') return 'student@example.com or username';
  return '+91 98765 43210';
}

function hintFor(type: StudentIdentityType): string {
  if (type === 'telegram') return 'Use the numeric Telegram user ID, not @username.';
  if (type === 'website_login') return 'Case-insensitive website account identifier.';
  return 'International number with country code. It will be normalized to E.164.';
}

function statusTone(status: StudentIdentityStatus): 'success' | 'warning' | 'danger' {
  if (status === 'verified') return 'success';
  if (status === 'pending') return 'warning';
  return 'danger';
}

function validateIdentifier(type: StudentIdentityType, rawIdentifier: string): string | null {
  let identifier = rawIdentifier.trim();
  if (type === 'whatsapp' || type === 'alternate_phone') {
    identifier = identifier.replace(/[\s().-]+/g, '');
    if (identifier.startsWith('00')) identifier = `+${identifier.slice(2)}`;
    return /^\+[1-9]\d{7,14}$/.test(identifier)
      ? null
      : 'Enter an international phone number with country code.';
  }
  if (type === 'telegram') {
    return /^[1-9]\d{4,19}$/.test(identifier) ? null : 'Enter the numeric Telegram user ID.';
  }
  return identifier.length >= 2 && identifier.length <= 320 && !/\s/.test(identifier)
    ? null
    : 'Website login must contain 2 to 320 characters without spaces.';
}

export function StudentIdentitiesModal({ student, open, onClose }: StudentIdentitiesModalProps) {
  const { pushToast } = useToast();
  const [identities, setIdentities] = useState<EducationStudentIdentity[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [filter, setFilter] = useState<'all' | StudentIdentityStatus>('all');
  const [form, setForm] = useState<IdentityFormState>(emptyForm);
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const [actingId, setActingId] = useState<string>();

  const visibleIdentities = useMemo(
    () => identities.filter((identity) => filter === 'all' || identity.status === filter),
    [filter, identities],
  );

  const load = async () => {
    if (!student) return;
    setLoading(true);
    setLoadError('');
    try {
      setIdentities(await educationStudentIdentityApi.list(student.id));
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Student identities could not be loaded.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!open || !student) return undefined;
    let cancelled = false;
    void educationStudentIdentityApi.list(student.id)
      .then((records) => {
        if (cancelled) return;
        setIdentities(records);
        setLoadError('');
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setLoadError(error instanceof Error ? error.message : 'Student identities could not be loaded.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [open, student]);

  const close = () => {
    if (saving || actingId) return;
    setFilter('all');
    setForm(emptyForm);
    setFormError('');
    setLoadError('');
    setLoading(true);
    onClose();
  };

  const submitIdentity = async (event: FormEvent) => {
    event.preventDefault();
    if (!student || student.status !== 'active') return;
    const identifierError = validateIdentifier(form.identityType, form.identifier);
    if (identifierError) {
      setFormError(identifierError);
      return;
    }
    setSaving(true);
    setFormError('');
    try {
      await educationStudentIdentityApi.create(student.id, {
        identityType: form.identityType,
        identifier: form.identifier,
        label: form.label.trim() || null,
        status: form.verified ? 'verified' : 'pending',
        isPrimary: form.primary,
      });
      pushToast(`${identityLabels[form.identityType]} identity linked`);
      setForm(emptyForm);
      await load();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Identity could not be linked.');
    } finally {
      setSaving(false);
    }
  };

  const updateIdentity = async (
    identity: EducationStudentIdentity,
    patch: Parameters<typeof educationStudentIdentityApi.update>[2],
    successMessage: string,
  ) => {
    if (!student) return;
    setActingId(identity.id);
    try {
      await educationStudentIdentityApi.update(student.id, identity.id, patch);
      pushToast(successMessage);
      await load();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Identity could not be updated.', 'error');
    } finally {
      setActingId(undefined);
    }
  };

  const revokeIdentity = async (identity: EducationStudentIdentity) => {
    if (!student) return;
    setActingId(identity.id);
    try {
      await educationStudentIdentityApi.revoke(student.id, identity.id);
      pushToast(`${identityLabels[identity.identityType]} identity revoked`);
      await load();
    } catch (error) {
      pushToast(error instanceof Error ? error.message : 'Identity could not be revoked.', 'error');
    } finally {
      setActingId(undefined);
    }
  };

  return <Modal
    open={open}
    onClose={close}
    title={student ? `${student.name} · Identities` : 'Student identities'}
    description="Link external identities to this Student profile. Verification does not grant course access by itself; Enrollment authorization is checked separately."
    size="lg"
    closeDisabled={saving || Boolean(actingId)}
    footer={<Button variant="secondary" onClick={close} disabled={saving || Boolean(actingId)}>Close</Button>}
  >
    {student ? <div className="identity-manager">
      <div className="identity-manager__student">
        <span><strong>{student.studentNumber}</strong><small>{student.email ?? 'No profile email'}</small></span>
        <Badge tone={student.status === 'active' ? 'success' : 'neutral'}>{student.status}</Badge>
      </div>

      {student.status === 'active' ? <form className="identity-create" onSubmit={(event) => void submitIdentity(event)} noValidate>
        <div className="identity-create__heading">
          <div><h3>Link identity</h3><p>Each normalized identity can belong to only one Student in this Workspace.</p></div>
          <Button type="submit" size="sm" icon={Plus} disabled={saving}>{saving ? 'Linking…' : 'Link identity'}</Button>
        </div>
        <div className="identity-create__grid">
          <Field label="Identity type" htmlFor="student-identity-type">
            <select
              id="student-identity-type"
              value={form.identityType}
              onChange={(event) => setForm((current) => ({
                ...current,
                identityType: event.target.value as StudentIdentityType,
                identifier: '',
              }))}
            >
              <option value="whatsapp">WhatsApp</option>
              <option value="telegram">Telegram</option>
              <option value="website_login">Website login</option>
              <option value="alternate_phone">Alternate phone</option>
            </select>
          </Field>
          <Field label="Identifier" htmlFor="student-identity-identifier" hint={hintFor(form.identityType)}>
            <input
              id="student-identity-identifier"
              value={form.identifier}
              maxLength={320}
              onChange={(event) => setForm((current) => ({ ...current, identifier: event.target.value }))}
              placeholder={placeholderFor(form.identityType)}
              autoComplete="off"
            />
          </Field>
          <Field label="Label" htmlFor="student-identity-label" hint="Optional admin-facing label.">
            <input
              id="student-identity-label"
              value={form.label}
              maxLength={80}
              onChange={(event) => setForm((current) => ({ ...current, label: event.target.value }))}
              placeholder="Primary WhatsApp"
              autoComplete="off"
            />
          </Field>
        </div>
        <div className="identity-create__switches">
          <Switch
            checked={form.verified}
            onChange={(verified) => setForm((current) => ({ ...current, verified }))}
            label="Mark as verified"
            description="Use only when the academy has already verified ownership."
          />
          <Switch
            checked={form.primary}
            onChange={(primary) => setForm((current) => ({ ...current, primary }))}
            label="Primary identity"
            description="Makes this the preferred identity for its type. The first identity is primary automatically."
          />
        </div>
        {formError ? <p className="identity-error" role="alert">{formError}</p> : null}
      </form> : <div className="identity-archived-note">
        <ShieldX /><div><strong>Student is archived</strong><p>Reactivate the Student profile before linking a new identity.</p></div>
      </div>}

      <div className="identity-list-section">
        <div className="identity-list-section__heading">
          <div><h3>Linked identities</h3><p>{identities.length} total</p></div>
          <label>
            <span className="sr-only">Filter identities by status</span>
            <select value={filter} onChange={(event) => setFilter(event.target.value as 'all' | StudentIdentityStatus)} aria-label="Filter identities by status">
              <option value="all">All statuses</option>
              <option value="verified">Verified</option>
              <option value="pending">Pending</option>
              <option value="revoked">Revoked</option>
            </select>
          </label>
        </div>

        {loading ? <div className="identity-loading">Loading identities…</div> : loadError ? <div className="identity-load-error" role="alert">
          <p>{loadError}</p><Button variant="secondary" size="sm" onClick={() => void load()}>Try again</Button>
        </div> : visibleIdentities.length ? <div className="identity-list">
          {visibleIdentities.map((identity) => <article className={`identity-row ${identity.status === 'revoked' ? 'is-revoked' : ''}`} key={identity.id}>
            <span className="identity-row__icon">{identity.status === 'verified' ? <ShieldCheck /> : <Link2 />}</span>
            <div className="identity-row__main">
              <div className="identity-row__title">
                <strong>{identityLabels[identity.identityType]}</strong>
                {identity.isPrimary ? <Badge tone="brand">Primary</Badge> : null}
                <Badge tone={statusTone(identity.status)}>{identity.status}</Badge>
              </div>
              <code>{identity.identifier}</code>
              <small>{identity.label || 'No label'}{identity.verifiedAt ? ` · verified ${new Date(identity.verifiedAt).toLocaleDateString()}` : ''}</small>
            </div>
            <div className="identity-row__actions">
              {identity.status === 'pending' ? <Button
                variant="secondary"
                size="sm"
                icon={ShieldCheck}
                disabled={actingId === identity.id}
                onClick={() => void updateIdentity(identity, { status: 'verified' }, `${identityLabels[identity.identityType]} identity verified`)}
              >Verify</Button> : null}
              {identity.status !== 'revoked' && !identity.isPrimary ? <Button
                variant="ghost"
                size="sm"
                icon={Star}
                disabled={actingId === identity.id}
                onClick={() => void updateIdentity(identity, { isPrimary: true }, `${identityLabels[identity.identityType]} set as primary`)}
              >Make primary</Button> : null}
              {identity.status !== 'revoked' ? <Button
                variant="danger"
                size="sm"
                icon={ShieldX}
                disabled={actingId === identity.id}
                onClick={() => void revokeIdentity(identity)}
              >Revoke</Button> : <Button
                variant="secondary"
                size="sm"
                icon={RotateCcw}
                disabled={actingId === identity.id}
                onClick={() => void updateIdentity(identity, { status: 'pending' }, `${identityLabels[identity.identityType]} restored for verification`)}
              >Restore</Button>}
            </div>
          </article>)}
        </div> : <div className="identity-empty">
          <Link2 /><div><strong>{identities.length ? 'No identities match this filter' : 'No identities linked yet'}</strong><p>{identities.length ? 'Choose another status filter.' : 'Link WhatsApp, Telegram, Website Login, or an alternate phone.'}</p></div>
        </div>}
      </div>
    </div> : null}
  </Modal>;
}

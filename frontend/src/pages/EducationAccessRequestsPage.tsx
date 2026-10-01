import { CheckCircle2, Clock3, RefreshCw, Search, ShieldCheck, XCircle } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useToast } from '@/components/providers';
import { Badge, Button, Card, EmptyState, Field, PageLoader } from '@/components/ui';
import {
  educationAccessRequestApi,
  type EducationAccessRequest,
  type EducationAccessRequestStatus,
} from '@/lib/education-access-request-api';
import { educationEnrollmentApi, type EducationEnrollment } from '@/lib/education-enrollment-api';
import { educationStudentApi, type EducationStudent } from '@/lib/education-student-api';
import { relativeTime } from '@/lib/format';
import './EducationAccessRequestsPage.css';

type RequestFilter = 'all' | EducationAccessRequestStatus;

interface ReviewDraft {
  studentId: string;
  enrollmentId: string;
  note: string;
}

function tone(status: EducationAccessRequestStatus): 'warning' | 'success' | 'danger' {
  if (status === 'approved') return 'success';
  if (status === 'denied') return 'danger';
  return 'warning';
}

function identityLabel(value: string): string {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (character) => character.toUpperCase());
}

export function EducationAccessRequestsPage() {
  const { pushToast } = useToast();
  const [requests, setRequests] = useState<EducationAccessRequest[]>();
  const [students, setStudents] = useState<EducationStudent[]>([]);
  const [enrollments, setEnrollments] = useState<EducationEnrollment[]>([]);
  const [filter, setFilter] = useState<RequestFilter>('pending');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reviewing, setReviewing] = useState<string>();
  const [drafts, setDrafts] = useState<Record<string, ReviewDraft>>({});

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const [requestValues, studentValues, enrollmentValues] = await Promise.all([
        educationAccessRequestApi.list(),
        educationStudentApi.list({ status: 'active' }),
        educationEnrollmentApi.list({ status: 'active' }),
      ]);
      setRequests(requestValues);
      setStudents(studentValues);
      setEnrollments(enrollmentValues);
      setDrafts((current) => {
        const next = { ...current };
        for (const request of requestValues) {
          if (next[request.id]) continue;
          next[request.id] = {
            studentId: request.studentId ?? '',
            enrollmentId: request.enrollmentId ?? '',
            note: '',
          };
        }
        return next;
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Education access requests could not be loaded.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  const studentById = useMemo(
    () => new Map(students.map((student) => [student.id, student])),
    [students],
  );
  const visible = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (requests ?? []).filter((request) => {
      if (filter !== 'all' && request.status !== filter) return false;
      if (!query) return true;
      const student = request.studentId ? studentById.get(request.studentId) : undefined;
      return [
        request.studentNumber,
        request.email ?? '',
        request.normalizedIdentifier,
        request.message ?? '',
        student?.name ?? '',
      ].join(' ').toLowerCase().includes(query);
    });
  }, [filter, requests, search, studentById]);

  const draftFor = (request: EducationAccessRequest): ReviewDraft => drafts[request.id] ?? {
    studentId: request.studentId ?? '',
    enrollmentId: request.enrollmentId ?? '',
    note: '',
  };

  const updateDraft = (requestId: string, patch: Partial<ReviewDraft>) => {
    setDrafts((current) => ({
      ...current,
      [requestId]: { ...(current[requestId] ?? { studentId: '', enrollmentId: '', note: '' }), ...patch },
    }));
  };

  const eligibleEnrollments = (request: EducationAccessRequest, studentId: string) => enrollments.filter(
    (enrollment) => enrollment.studentId === studentId && enrollment.agentId === request.agentId,
  );

  const review = async (request: EducationAccessRequest, action: 'approve' | 'deny') => {
    const draft = draftFor(request);
    if (action === 'approve' && (!draft.studentId || !draft.enrollmentId)) {
      pushToast('Select an active Student and Enrollment before approving access.', 'error');
      return;
    }
    setReviewing(request.id);
    try {
      const updated = await educationAccessRequestApi.review(request.id, {
        action,
        studentId: action === 'approve' ? draft.studentId : undefined,
        enrollmentId: action === 'approve' ? draft.enrollmentId : undefined,
        note: draft.note || null,
      });
      setRequests((current) => (current ?? []).map((item) => item.id === updated.id ? updated : item));
      pushToast(action === 'approve' ? 'Student access request approved' : 'Student access request denied');
    } catch (reason) {
      pushToast(reason instanceof Error ? reason.message : 'Access request could not be reviewed.', 'error');
    } finally {
      setReviewing(undefined);
    }
  };

  if (loading && !requests) return <PageLoader />;

  return <div className="page access-requests-page">
    <div className="page-heading page-heading--split">
      <div>
        <h2>Education access requests</h2>
        <p>Review students who could not complete self-service identity verification. Approval only verifies the identity; normal Education authorization still decides course access.</p>
      </div>
      <Button variant="secondary" icon={RefreshCw} onClick={() => void load()} disabled={loading}>Refresh</Button>
    </div>

    <div className="access-request-stats" aria-label="Access request summary">
      <Card><Clock3 /><div><strong>{(requests ?? []).filter((item) => item.status === 'pending').length}</strong><small>Pending review</small></div></Card>
      <Card><CheckCircle2 /><div><strong>{(requests ?? []).filter((item) => item.status === 'approved').length}</strong><small>Approved</small></div></Card>
      <Card><XCircle /><div><strong>{(requests ?? []).filter((item) => item.status === 'denied').length}</strong><small>Denied</small></div></Card>
    </div>

    <Card className="access-request-directory">
      <div className="access-request-toolbar">
        <div className="access-request-tabs" role="group" aria-label="Filter access requests">
          {(['pending', 'all', 'approved', 'denied'] as RequestFilter[]).map((value) => <Button
            key={value}
            size="sm"
            variant={filter === value ? 'primary' : 'secondary'}
            onClick={() => setFilter(value)}
          >{value === 'all' ? 'All' : identityLabel(value)}</Button>)}
        </div>
        <label className="access-request-search">
          <span className="sr-only">Search education access requests</span>
          <Search />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search student, email, identity" />
        </label>
      </div>

      {error ? <div className="form-error" role="alert">{error}</div> : null}
      {!error && visible.length === 0 ? <EmptyState
        icon={ShieldCheck}
        title="No access requests"
        description={filter === 'pending' ? 'There are no student access requests waiting for review.' : 'No requests match the current filter.'}
      /> : null}

      <div className="access-request-list">
        {visible.map((request) => {
          const draft = draftFor(request);
          const student = request.studentId ? studentById.get(request.studentId) : undefined;
          const eligible = eligibleEnrollments(request, draft.studentId);
          const busy = reviewing === request.id;
          return <article className="access-request-card" key={request.id}>
            <div className="access-request-card__heading">
              <div>
                <span className="access-request-card__student">{student?.name ?? request.studentNumber}</span>
                <strong>{request.studentNumber}</strong>
                <small>{request.email ?? 'No email'} · {relativeTime(request.createdAt)}</small>
              </div>
              <Badge tone={tone(request.status)}>{request.status}</Badge>
            </div>
            <div className="access-request-facts">
              <span><b>Identity</b>{identityLabel(request.identityType)}</span>
              <span><b>Identifier</b><code>{request.normalizedIdentifier}</code></span>
              <span><b>Agent</b><code>{request.agentId}</code></span>
              <span><b>Matched enrollment</b>{request.enrollmentId ? <code>{request.enrollmentId}</code> : 'Needs reviewer selection'}</span>
            </div>
            {request.message ? <blockquote className="access-request-message">{request.message}</blockquote> : null}

            {request.status === 'pending' ? <div className="access-request-review">
              <div className="two-fields">
                <Field label="Student" htmlFor={`access-student-${request.id}`}>
                  <select
                    id={`access-student-${request.id}`}
                    value={draft.studentId}
                    onChange={(event) => updateDraft(request.id, { studentId: event.target.value, enrollmentId: '' })}
                  >
                    <option value="">Select active Student</option>
                    {students.map((item) => <option key={item.id} value={item.id}>{item.studentNumber} · {item.name}</option>)}
                  </select>
                </Field>
                <Field label="Active enrollment" htmlFor={`access-enrollment-${request.id}`}>
                  <select
                    id={`access-enrollment-${request.id}`}
                    value={draft.enrollmentId}
                    disabled={!draft.studentId}
                    onChange={(event) => updateDraft(request.id, { enrollmentId: event.target.value })}
                  >
                    <option value="">Select Enrollment for this Education Agent</option>
                    {eligible.map((item) => <option key={item.id} value={item.id}>{item.id} · active</option>)}
                  </select>
                </Field>
              </div>
              <Field label="Review note" htmlFor={`access-note-${request.id}`} hint="Optional internal reason recorded with the review.">
                <textarea
                  id={`access-note-${request.id}`}
                  value={draft.note}
                  maxLength={1000}
                  onChange={(event) => updateDraft(request.id, { note: event.target.value })}
                  placeholder="Verification details or denial reason"
                />
              </Field>
              <div className="access-request-actions">
                <Button icon={CheckCircle2} disabled={busy} onClick={() => void review(request, 'approve')}>Approve & verify identity</Button>
                <Button variant="danger" icon={XCircle} disabled={busy} onClick={() => void review(request, 'deny')}>Deny request</Button>
              </div>
            </div> : <div className="access-request-resolution">
              <strong>{request.status === 'approved' ? 'Identity verified by reviewer' : 'Request denied'}</strong>
              <p>{request.resolutionNote || 'No review note was added.'}</p>
              {request.reviewedAt ? <small>Reviewed {relativeTime(request.reviewedAt)}</small> : null}
            </div>}
          </article>;
        })}
      </div>
    </Card>
  </div>;
}

import {
  Activity, ArrowLeft, BadgeCheck, BookOpen, CalendarRange, GraduationCap, History, MessagesSquare, ShieldCheck, UserRound,
} from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { Badge, Card, EmptyState, PageLoader } from '@/components/ui';
import {
  educationStudentDetailApi,
  type StudentAccessState,
  type StudentDetailActivity,
} from '@/lib/education-student-detail-api';
import { relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';
import './EducationStudentDetailPage.css';

function dateLabel(value: string | null): string {
  if (!value) return 'No limit';
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { year: 'numeric', month: 'short', day: 'numeric' }).format(date);
}

function accessTone(state: StudentAccessState): 'success' | 'warning' | 'danger' | 'neutral' {
  if (state === 'active') return 'success';
  if (state === 'pending' || state === 'scheduled' || state === 'suspended') return 'warning';
  if (state === 'revoked' || state === 'expired') return 'danger';
  return 'neutral';
}

function activityTitle(event: StudentDetailActivity): string {
  if (event.eventType === 'education.conversation.resolved.v1') return 'Education conversation resolved';
  return event.eventType.replace(/^education\./, '').replace(/\.v\d+$/, '').replace(/[._]/g, ' ');
}

function activityTopics(details: Record<string, unknown>): string[] {
  const value = details.topicsAsked;
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === 'string' && Boolean(item.trim())).slice(0, 5);
}

function detailEntries(details: Record<string, unknown>): Array<[string, string]> {
  return Object.entries(details)
    .filter(([key, value]) => key !== 'topicsAsked' && value !== null && value !== undefined && value !== '')
    .slice(0, 8)
    .map(([key, value]) => [
      key.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[._]/g, ' '),
      typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
        ? String(value)
        : JSON.stringify(value) ?? String(value),
    ]);
}

export function EducationStudentDetailPage() {
  const { studentId } = useParams<{ studentId: string }>();
  const detail = useApi(() => {
    if (!studentId) return Promise.reject(new Error('Student ID is missing'));
    return educationStudentDetailApi.get(studentId);
  }, [studentId]);

  if (detail.loading && !detail.data) return <PageLoader />;
  if (detail.error || !detail.data) {
    return <div className="page student-detail-page">
      <Card><EmptyState
        icon={UserRound}
        title="Student detail is unavailable"
        description={detail.error ?? 'Student not found'}
        action={<Link className="button button--secondary button--md" to="/education/students">Back to students</Link>}
      /></Card>
    </div>;
  }

  const { student, identities, enrollments, conversations, activity, summary } = detail.data;
  return <div className="page student-detail-page">
    <div className="page-heading page-heading--split">
      <div>
        <Link className="student-detail-back" to="/education/students"><ArrowLeft /> Students</Link>
        <div className="student-detail-title-row">
          <div>
            <h2>{student.name}</h2>
            <p><code>{student.studentNumber}</code> · {student.email || 'No email address'}</p>
          </div>
          <Badge tone={student.status === 'active' ? 'success' : 'neutral'}>{student.status}</Badge>
        </div>
      </div>
      <Link className="button button--secondary button--md" to="/conversations"><MessagesSquare />Open conversation inbox</Link>
    </div>

    <div className="student-detail-stats" aria-label="Student access and activity summary">
      <Card><BadgeCheck /><div><strong>{summary.verifiedIdentityCount}</strong><small>Verified identities</small></div></Card>
      <Card><ShieldCheck /><div><strong>{summary.activeAccessCount}</strong><small>Active enrollments</small></div></Card>
      <Card><MessagesSquare /><div><strong>{summary.conversationCount}</strong><small>Education conversations</small></div></Card>
      <Card><Activity /><div><strong>{summary.activityCount}</strong><small>Activity events</small></div></Card>
    </div>

    <div className="student-detail-layout">
      <div className="student-detail-main">
        <Card>
          <div className="student-detail-section-heading"><div><GraduationCap /><span><h3>Enrollments & access</h3><p>Course, Batch and assigned Education Agent validity.</p></span></div></div>
          {enrollments.length ? <div className="student-detail-table-wrap"><table className="student-detail-table">
            <thead><tr><th>Course / Batch</th><th>Agent</th><th>Enrollment</th><th>Validity</th><th>Access</th></tr></thead>
            <tbody>{enrollments.map((enrollment) => <tr key={enrollment.id}>
              <td><strong>{enrollment.courseName}</strong><small>{enrollment.courseCode} · {enrollment.batchName} ({enrollment.batchCode})</small></td>
              <td><strong>{enrollment.agentName}</strong><small>{enrollment.agentPublicId}</small></td>
              <td><Badge tone={accessTone(enrollment.status)}>{enrollment.status}</Badge></td>
              <td><span className="student-detail-validity"><CalendarRange />{dateLabel(enrollment.startsOn)} → {dateLabel(enrollment.endsOn)}</span></td>
              <td><Badge tone={accessTone(enrollment.accessState)}>{enrollment.accessState}</Badge></td>
            </tr>)}</tbody>
          </table></div> : <EmptyState icon={GraduationCap} title="No enrollments" description="This Student does not currently have a Course/Batch/Agent assignment." />}
        </Card>

        <Card>
          <div className="student-detail-section-heading"><div><MessagesSquare /><span><h3>Education conversations</h3><p>Conversations attached through the existing Education authorization context.</p></span></div></div>
          {conversations.length ? <div className="student-detail-conversations">{conversations.map((conversation) => <article key={conversation.id}>
            <div><strong>{conversation.publicId}</strong><small>{conversation.agentName} · {conversation.channel}</small></div>
            <div><Badge tone={conversation.state === 'resolved' ? 'success' : conversation.state === 'escalated' ? 'warning' : 'neutral'}>{conversation.state}</Badge><small>{relativeTime(conversation.updatedAt)}</small></div>
            {conversation.resolution ? <p>Resolution: {conversation.resolution}</p> : null}
          </article>)}</div> : <EmptyState icon={MessagesSquare} title="No Education conversations" description="Authorized Education conversations will appear here without changing the existing inbox." />}
        </Card>

        <Card>
          <div className="student-detail-section-heading"><div><History /><span><h3>Activity history</h3><p>Latest append-only Education history events. Total recorded: {summary.activityCount}.</p></span></div></div>
          {activity.length ? <ol className="student-detail-timeline">{activity.map((event) => {
            const entries = detailEntries(event.details);
            const topics = activityTopics(event.details);
            return <li key={event.id}>
              <span className="student-detail-timeline-dot" />
              <div className="student-detail-activity-card">
                <div className="student-detail-activity-heading">
                  <div><strong>{activityTitle(event)}</strong><small>{event.courseName} · {event.batchName} · {event.agentName}</small></div>
                  <time dateTime={event.createdAt}>{relativeTime(event.createdAt)}</time>
                </div>
                <p>Conversation <code>{event.conversationPublicId}</code>{event.resolution ? ` · ${event.resolution}` : ''}</p>
                {topics.length ? <div className="student-detail-activity-topics"><strong>Topics asked</strong><ul>{topics.map((topic) => <li key={topic}>{topic}</li>)}</ul></div> : null}
                {entries.length ? <dl>{entries.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl> : null}
              </div>
            </li>;
          })}</ol> : <EmptyState icon={History} title="No activity history" description="Resolved Education conversations and support activity will appear here." />}
        </Card>
      </div>

      <aside className="student-detail-side">
        <Card>
          <div className="student-detail-section-heading"><div><UserRound /><span><h3>Profile</h3><p>Workspace-scoped Student record.</p></span></div></div>
          <dl className="student-detail-profile">
            <div><dt>Student ID</dt><dd><code>{student.studentNumber}</code></dd></div>
            <div><dt>Name</dt><dd>{student.name}</dd></div>
            <div><dt>Email</dt><dd>{student.email || '—'}</dd></div>
            <div><dt>Status</dt><dd>{student.status}</dd></div>
            <div><dt>Last activity</dt><dd>{summary.lastActiveAt ? relativeTime(summary.lastActiveAt) : 'No activity yet'}</dd></div>
          </dl>
          {Object.keys(student.customFields).length ? <div className="student-detail-custom-fields"><h4>Custom fields</h4><dl>{Object.entries(student.customFields).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value ?? '—')}</dd></div>)}</dl></div> : null}
        </Card>

        <Card>
          <div className="student-detail-section-heading"><div><ShieldCheck /><span><h3>Identities</h3><p>Channel/login identity verification status.</p></span></div></div>
          {identities.length ? <div className="student-detail-identities">{identities.map((identity) => <article key={identity.id}>
            <div><strong>{identity.identityType.replace('_', ' ')}</strong>{identity.isPrimary ? <Badge tone="neutral">Primary</Badge> : null}</div>
            <code>{identity.identifier}</code>
            <div><Badge tone={identity.status === 'verified' ? 'success' : identity.status === 'revoked' ? 'danger' : 'warning'}>{identity.status}</Badge>{identity.label ? <small>{identity.label}</small> : null}</div>
          </article>)}</div> : <EmptyState icon={ShieldCheck} title="No identities" description="Add an identity from the Students directory when the Student needs channel or login access." />}
        </Card>

        <Card className="student-detail-scope-note">
          <BookOpen />
          <div><strong>Authorization remains unchanged</strong><p>This page only reads existing Education scope. RAG/private knowledge still requires the normal verified identity and active Enrollment authorization path.</p></div>
        </Card>
      </aside>
    </div>
  </div>;
}

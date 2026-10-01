import { Activity, Bot, ChevronDown, Clock3, Filter, GraduationCap, Inbox, Search, UserRound } from 'lucide-react';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useWorkspace } from '@/components/providers';
import { Badge, EmptyState, PageLoader } from '@/components/ui';
import { api } from '@/lib/api';
import { educationActivityApi } from '@/lib/education-activity-api';
import { educationApi, type EducationBatch, type EducationCourse } from '@/lib/education-api';
import { educationEnrollmentApi, type EducationEnrollment } from '@/lib/education-enrollment-api';
import { educationStudentApi, type EducationStudent } from '@/lib/education-student-api';
import { relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';
import './EducationActivityPage.css';

function topicsAsked(details: Record<string, unknown>): string[] {
  const value = details.topicsAsked;
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === 'string' && Boolean(item.trim())).slice(0, 5);
}

function ActivityTopics({ details }: { details: Record<string, unknown> }) {
  const topics = topicsAsked(details);
  if (!topics.length) return null;
  return <div className="education-activity-topics">
    <strong>Topics asked</strong>
    <ul>{topics.map((topic) => <li key={topic}>{topic}</li>)}</ul>
  </div>;
}

export function EducationActivityPage() {
  const { activeWorkspace } = useWorkspace();
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [agentId, setAgentId] = useState('all');
  const [courseId, setCourseId] = useState('all');
  const [batchId, setBatchId] = useState('all');
  const [studentId, setStudentId] = useState('all');
  const [eventType, setEventType] = useState('all');

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  const agents = useApi(() => api.agents.list(), [activeWorkspace?.id]);
  const educationAgents = useMemo(
    () => (agents.data ?? []).filter((agent) => agent.purpose === 'education'),
    [agents.data],
  );
  const courses = useApi(
    () => educationApi.courses.list({ status: 'active' }),
    [activeWorkspace?.id],
  );
  const batches = useApi(
    () => courseId !== 'all'
      ? educationApi.batches.list({ courseId, status: 'active' })
      : Promise.resolve([] as EducationBatch[]),
    [activeWorkspace?.id, courseId],
  );
  const enrollments = useApi(
    () => courseId !== 'all' && batchId !== 'all'
      ? educationEnrollmentApi.list({
        courseId,
        batchId,
        agentId: agentId === 'all' ? undefined : agentId,
      })
      : Promise.resolve([] as EducationEnrollment[]),
    [activeWorkspace?.id, agentId, courseId, batchId],
  );
  const students = useApi(
    () => batchId !== 'all'
      ? educationStudentApi.list({ status: 'active' })
      : Promise.resolve([] as EducationStudent[]),
    [activeWorkspace?.id, batchId],
  );
  const eligibleStudentIds = useMemo(
    () => new Set((enrollments.data ?? []).map((enrollment) => enrollment.studentId)),
    [enrollments.data],
  );
  const eligibleStudents = useMemo(
    () => (students.data ?? []).filter((student) => eligibleStudentIds.has(student.id)),
    [students.data, eligibleStudentIds],
  );

  useEffect(() => {
    if (
      studentId !== 'all'
      && !eligibleStudents.some((student) => student.id === studentId)
      && !students.loading
      && !enrollments.loading
    ) {
      setStudentId('all');
    }
  }, [eligibleStudents, enrollments.loading, studentId, students.loading]);

  const result = useApi(
    () => educationActivityApi.list({
      agentId: agentId === 'all' ? undefined : agentId,
      courseId: courseId === 'all' ? undefined : courseId,
      batchId: batchId === 'all' ? undefined : batchId,
      studentId: studentId === 'all' ? undefined : studentId,
      eventType: eventType === 'all' ? undefined : eventType,
      search: debouncedSearch || undefined,
      page: 1,
      pageSize: 50,
    }),
    [activeWorkspace?.id, agentId, courseId, batchId, studentId, eventType, debouncedSearch],
  );

  const changeAgent = (nextAgentId: string) => {
    setAgentId(nextAgentId);
    setCourseId('all');
    setBatchId('all');
    setStudentId('all');
  };

  const changeCourse = (nextCourseId: string) => {
    setCourseId(nextCourseId);
    setBatchId('all');
    setStudentId('all');
  };

  const changeBatch = (nextBatchId: string) => {
    setBatchId(nextBatchId);
    setStudentId('all');
  };

  if (result.loading && !result.data) return <PageLoader />;

  const items = result.data?.items ?? [];
  return <div className="education-activity-page">
    <header className="education-activity-header">
      <div>
        <span className="education-activity-kicker"><Activity /> Education operations</span>
        <h1>Education activity</h1>
        <p>Review append-only student support history for the active workspace without changing the underlying events.</p>
      </div>
      <Badge tone="brand">{result.data?.total ?? 0} events</Badge>
    </header>

    <section className="education-activity-filters" aria-label="Education activity filters">
      <label className="education-activity-search">
        <Search />
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search student, course, batch, agent, conversation…"
          aria-label="Search Education activity"
        />
      </label>
      <FilterSelect label="Filter by agent" value={agentId} onChange={changeAgent}>
        <option value="all">All Education agents</option>
        {educationAgents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
      </FilterSelect>
      <FilterSelect label="Filter by course" value={courseId} onChange={changeCourse}>
        <option value="all">All courses</option>
        {(courses.data ?? []).map((course: EducationCourse) => (
          <option key={course.id} value={course.id}>{course.code} · {course.name}</option>
        ))}
      </FilterSelect>
      <FilterSelect label="Filter by batch" value={batchId} onChange={changeBatch} disabled={courseId === 'all'}>
        <option value="all">All batches</option>
        {(batches.data ?? []).map((batch) => (
          <option key={batch.id} value={batch.id}>{batch.code} · {batch.name}</option>
        ))}
      </FilterSelect>
      <FilterSelect
        label="Filter by student"
        value={studentId}
        onChange={setStudentId}
        disabled={batchId === 'all'}
      >
        <option value="all">All students</option>
        {eligibleStudents.map((student) => (
          <option key={student.id} value={student.id}>{student.studentNumber} · {student.name}</option>
        ))}
      </FilterSelect>
      <FilterSelect label="Filter by event type" value={eventType} onChange={setEventType}>
        <option value="all">All activity types</option>
        <option value="conversation.resolved">Conversation resolved</option>
      </FilterSelect>
    </section>

    {result.error ? <div className="education-activity-error" role="alert">{result.error}</div> : null}

    {items.length ? <section className="education-activity-list" aria-label="Education activity results">
      {items.map((item) => <article className="education-activity-card" key={item.id}>
        <div className="education-activity-card__timeline"><span><Activity /></span></div>
        <div className="education-activity-card__body">
          <div className="education-activity-card__topline">
            <div>
              <strong>{eventLabel(item.eventType)}</strong>
              <small><Clock3 /> {relativeTime(item.createdAt)}</small>
            </div>
            <Badge tone={item.resolution ? 'success' : 'neutral'}>{item.resolution ?? 'Recorded'}</Badge>
          </div>
          <div className="education-activity-card__student">
            <UserRound />
            <div>
              <Link to={`/education/students/${item.studentId}`}>{item.studentName}</Link>
              <small>{item.studentNumber}{item.studentEmail ? ` · ${item.studentEmail}` : ''}</small>
            </div>
          </div>
          <dl className="education-activity-meta">
            <div><dt><GraduationCap /> Course</dt><dd>{item.courseCode} · {item.courseName}</dd></div>
            <div><dt><GraduationCap /> Batch</dt><dd>{item.batchCode} · {item.batchName}</dd></div>
            <div><dt><Bot /> Agent</dt><dd>{item.agentName}</dd></div>
            <div><dt><Inbox /> Conversation</dt><dd><Link to={`/conversations?selected=${item.conversationId}`}>{item.conversationPublicId}</Link></dd></div>
          </dl>
          <ActivityTopics details={item.details} />
          <div className="education-activity-card__footer">
            <span>Resolved {new Date(item.resolvedAt).toLocaleString()}</span>
            <span>Event: <code>{item.eventType}</code></span>
          </div>
        </div>
      </article>)}
    </section> : <EmptyState
      icon={Activity}
      title="No Education activity found"
      description="Try another Agent, Course, Batch, Student, event type, or search."
    />}
  </div>;
}

function FilterSelect({
  label,
  value,
  onChange,
  disabled = false,
  children,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return <label className="education-activity-select">
    <Filter />
    <select
      aria-label={label}
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
    >
      {children}
    </select>
    <ChevronDown />
  </label>;
}

function eventLabel(eventType: string): string {
  return eventType
    .split('.')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

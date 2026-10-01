import { BotEnrollmentPanel } from '@/components/bot-enrollment-panel';
import { ClipboardList, Filter, GraduationCap, Plus, Search, UserRound } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { StudentEnrollmentsModal } from '@/components/student-enrollments-modal';
import { useWorkspace } from '@/components/providers';
import { Badge, Button, Card, EmptyState, Field, Modal, PageLoader } from '@/components/ui';
import { api } from '@/lib/api';
import { educationApi, type EducationBatch, type EducationCourse } from '@/lib/education-api';
import {
  activeStudentsForEnrollment,
  batchesForCourse,
  enrollmentAdminSummary,
  filterEnrollmentAdminRecords,
  type EnrollmentStatusFilter,
} from '@/lib/education-enrollment-admin';
import {
  educationEnrollmentApi,
  type EducationEnrollment,
  type EnrollmentStatus,
} from '@/lib/education-enrollment-api';
import { educationStudentApi, type EducationStudent } from '@/lib/education-student-api';
import { relativeTime } from '@/lib/format';
import { useApi } from '@/lib/use-api';
import type { Agent } from '@/types';
import './EducationEnrollmentsPage.css';

const statusLabels: Record<EnrollmentStatus, string> = {
  pending: 'Pending',
  active: 'Active',
  suspended: 'Suspended',
  expired: 'Expired',
  revoked: 'Revoked',
  graduated: 'Graduated',
};

function statusTone(status: EnrollmentStatus): 'success' | 'warning' | 'danger' | 'neutral' | 'brand' {
  if (status === 'active') return 'success';
  if (status === 'pending' || status === 'suspended') return 'warning';
  if (status === 'revoked') return 'danger';
  if (status === 'graduated') return 'brand';
  return 'neutral';
}

function dateLabel(value: string | null): string {
  if (!value) return 'No limit';
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { year: 'numeric', month: 'short', day: 'numeric' }).format(parsed);
}

export function EducationEnrollmentsPage() {
  const { activeWorkspace } = useWorkspace();
  const enrollments = useApi(() => educationEnrollmentApi.list(), [activeWorkspace?.id]);
  const students = useApi(() => educationStudentApi.list(), [activeWorkspace?.id]);
  const courses = useApi(() => educationApi.courses.list(), [activeWorkspace?.id]);
  const batches = useApi(() => educationApi.batches.list(), [activeWorkspace?.id]);
  const agents = useApi(() => api.agents.list(), [activeWorkspace?.id]);

  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<EnrollmentStatusFilter>('all');
  const [courseId, setCourseId] = useState('all');
  const [batchId, setBatchId] = useState('all');
  const [params, setParams] = useSearchParams();
  const agentId = params.get('agentId') || 'all';
  const setAgentId = (id: string) => setParams(id === 'all' ? {} : { agentId: id });
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerStudentId, setPickerStudentId] = useState('');
  const [pickerSearch, setPickerSearch] = useState('');
  const [managedStudent, setManagedStudent] = useState<EducationStudent | null>(null);

  const studentById = useMemo(
    () => new Map((students.data ?? []).map((student) => [student.id, student])),
    [students.data],
  );
  const courseById = useMemo(
    () => new Map((courses.data ?? []).map((course) => [course.id, course])),
    [courses.data],
  );
  const batchById = useMemo(
    () => new Map((batches.data ?? []).map((batch) => [batch.id, batch])),
    [batches.data],
  );
  const agentById = useMemo(
    () => new Map((agents.data ?? []).map((agent) => [agent.id, agent])),
    [agents.data],
  );
  const educationAgents = useMemo(
    () => (agents.data ?? []).filter((agent) => agent.purpose === 'education'),
    [agents.data],
  );
  const visibleBatches = useMemo(
    () => batchesForCourse(batches.data ?? [], courseId),
    [batches.data, courseId],
  );
  const records = useMemo(
    () => filterEnrollmentAdminRecords(
      enrollments.data ?? [],
      students.data ?? [],
      courses.data ?? [],
      batches.data ?? [],
      agents.data ?? [],
      { status, courseId, batchId, agentId, search },
    ),
    [agentId, agents.data, batchId, batches.data, courseId, courses.data, enrollments.data, search, status, students.data],
  );
  const recordGroups = useMemo(() => {
    const grouped = new Map<string, EducationEnrollment[]>();
    for (const enrollment of records) {
      const current = grouped.get(enrollment.studentId) ?? [];
      current.push(enrollment);
      grouped.set(enrollment.studentId, current);
    }
    return [...grouped.entries()]
      .map(([studentId, items]) => ({
        studentId,
        items: [...items].sort((left, right) => {
          const leftCourse = courseById.get(left.courseId)?.name ?? left.courseId;
          const rightCourse = courseById.get(right.courseId)?.name ?? right.courseId;
          return leftCourse.localeCompare(rightCourse) || right.updatedAt.localeCompare(left.updatedAt);
        }),
      }))
      .sort((left, right) => {
        const leftStudent = studentById.get(left.studentId);
        const rightStudent = studentById.get(right.studentId);
        return (leftStudent?.name ?? left.studentId).localeCompare(rightStudent?.name ?? right.studentId)
          || (leftStudent?.studentNumber ?? '').localeCompare(rightStudent?.studentNumber ?? '');
      });
  }, [courseById, records, studentById]);
  const courseAccessByStudent = useMemo(() => {
    const result = new Map<string, Set<string>>();
    for (const enrollment of enrollments.data ?? []) {
      if (!['pending', 'active', 'suspended'].includes(enrollment.status)) continue;
      const coursesForStudent = result.get(enrollment.studentId) ?? new Set<string>();
      coursesForStudent.add(enrollment.courseId);
      result.set(enrollment.studentId, coursesForStudent);
    }
    return result;
  }, [enrollments.data]);
  const activeStudents = useMemo(
    () => activeStudentsForEnrollment(students.data ?? [], pickerSearch),
    [pickerSearch, students.data],
  );
  const summary = useMemo(
    () => enrollmentAdminSummary(enrollments.data ?? []),
    [enrollments.data],
  );

  const loading = [enrollments, students, courses, batches, agents].some((state) => state.loading && !state.data);
  const error = enrollments.error || students.error || courses.error || batches.error || agents.error;

  const reloadAll = () => {
    enrollments.reload();
    students.reload();
    courses.reload();
    batches.reload();
    agents.reload();
  };

  const changeCourse = (nextCourseId: string) => {
    setCourseId(nextCourseId);
    setBatchId('all');
  };

  const openPicker = () => {
    setPickerStudentId('');
    setPickerSearch('');
    setPickerOpen(true);
  };

  const managePickedStudent = () => {
    const student = studentById.get(pickerStudentId);
    if (!student) return;
    setPickerOpen(false);
    setManagedStudent(student);
  };

  const closeManager = () => {
    setManagedStudent(null);
    enrollments.reload();
    students.reload();
  };

  if (loading) return <PageLoader />;
  if (error) {
    return <div className="page education-enrollments-page"><Card><EmptyState
      icon={GraduationCap}
      title="Enrollments are unavailable"
      description={error}
      action={<Button onClick={reloadAll}>Try again</Button>}
    /></Card></div>;
  }

  return <div className="page education-enrollments-page">
    <div className="page-heading page-heading--split">
      <div>
        <h2>Enrollments</h2>
        <p>Choose a bot to manage its students, course access, bulk enrollment and CRM/LMS automation.</p>
      </div>
      <Button icon={Plus} onClick={openPicker}>Add enrollment</Button>
    </div>

    <Card className="bot-enrollment-panel"><Field label="Enrollment bot" htmlFor="enrollment-bot-picker"><select id="enrollment-bot-picker" value={agentId} onChange={(event) => setAgentId(event.target.value)}><option value="all">All education bots</option>{educationAgents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name} - {agent.whatsappNumber || 'No WhatsApp number'} - {agent.status}</option>)}</select></Field></Card>
    {educationAgents.filter((agent) => agent.id === agentId).map((agent) => <BotEnrollmentPanel key={agent.id} agent={agent} courses={courses.data ?? []} batches={batches.data ?? []} onSaved={reloadAll} />)}
    <div className="education-enrollment-stats" aria-label="Enrollment summary">
      <Card><ClipboardList /><div><strong>{summary.total}</strong><small>Total enrollments</small></div></Card>
      <Card><GraduationCap /><div><strong>{summary.active}</strong><small>Active access</small></div></Card>
      <Card><UserRound /><div><strong>{summary.pending}</strong><small>Pending review</small></div></Card>
      <Card><Filter /><div><strong>{summary.restricted}</strong><small>Restricted / ended</small></div></Card>
    </div>

    <Card className="education-enrollment-directory">
      <div className="education-enrollment-toolbar">
        <div>
          <h3>Enrollment directory</h3>
          <p>{records.length} shown · {summary.total} total</p>
        </div>
        <div className="education-enrollment-toolbar__filters">
          <label className="education-enrollment-search">
            <span className="sr-only">Search enrollments</span>
            <Search />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search Student, Course, Batch, or Agent"
              aria-label="Search enrollments"
            />
          </label>
          <label>
            <span className="sr-only">Filter enrollments by status</span>
            <select value={status} onChange={(event) => setStatus(event.target.value as EnrollmentStatusFilter)} aria-label="Filter enrollments by status">
              <option value="all">All statuses</option>
              {Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label>
            <span className="sr-only">Filter enrollments by course</span>
            <select value={courseId} onChange={(event) => changeCourse(event.target.value)} aria-label="Filter enrollments by course">
              <option value="all">All courses</option>
              {(courses.data ?? []).map((course: EducationCourse) => <option key={course.id} value={course.id}>{course.code} · {course.name}</option>)}
            </select>
          </label>
          <label>
            <span className="sr-only">Filter enrollments by batch</span>
            <select value={batchId} onChange={(event) => setBatchId(event.target.value)} aria-label="Filter enrollments by batch">
              <option value="all">All batches</option>
              {visibleBatches.map((batch: EducationBatch) => <option key={batch.id} value={batch.id}>{batch.code} · {batch.name}</option>)}
            </select>
          </label>
          <label>
            <span className="sr-only">Filter enrollments by agent</span>
            <select value={agentId} onChange={(event) => setAgentId(event.target.value)} aria-label="Filter enrollments by agent">
              <option value="all">All Education agents</option>
              {educationAgents.map((agent: Agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
            </select>
          </label>
        </div>
      </div>

      {records.length ? <div className="education-enrollment-table-wrap"><table className="education-enrollment-table">
        <thead><tr><th>Student</th><th>Course / Batch</th><th>Education Agent</th><th>Validity</th><th>Status</th><th>Updated</th><th><span className="sr-only">Actions</span></th></tr></thead>
        <tbody>{recordGroups.flatMap((group) => group.items.map((enrollment, index) => {
          const student = studentById.get(group.studentId);
          const course = courseById.get(enrollment.courseId);
          const batch = batchById.get(enrollment.batchId);
          const agent = agentById.get(enrollment.agentId);
          const studentCourses = courseAccessByStudent.get(group.studentId) ?? new Set<string>();
          const courseCount = studentCourses.size;
          const courseNames = [...studentCourses].map(id => courseById.get(id)?.name ?? id).join(', ');
          return <tr key={enrollment.id} className={index === 0 ? 'education-enrollment-group-start' : undefined}>
            {index === 0 && <td rowSpan={group.items.length} className="education-enrollment-student-cell">{student ? <><Link to={`/education/students/${student.id}`}>{student.name}</Link><small>{student.studentNumber}{student.email ? ` · ${student.email}` : ''}</small>{courseCount > 1 && <span className="education-multi-course" title={courseNames}>{courseCount} courses</span>}</> : <code>{enrollment.studentId}</code>}</td>}
            <td><strong>{course?.name ?? enrollment.courseId}</strong><small>{course?.code ?? 'Course'} · {batch ? `${batch.code} · ${batch.name}` : enrollment.batchId}</small></td>
            <td><strong>{agent?.name ?? enrollment.agentId}</strong><small>{agent?.whatsappNumber || agent?.publicId || 'Education Agent'}</small></td>
            <td><span>{dateLabel(enrollment.startsOn)} → {dateLabel(enrollment.endsOn)}</span></td>
            <td><Badge tone={statusTone(enrollment.status)}>{statusLabels[enrollment.status]}</Badge></td>
            <td><time dateTime={enrollment.updatedAt}>{relativeTime(enrollment.updatedAt)}</time></td>
            {index === 0 && <td rowSpan={group.items.length} className="education-enrollment-action-cell">{student ? <Button variant="secondary" size="sm" aria-label="Manage access" onClick={() => setManagedStudent(student)}>Manage all access</Button> : null}</td>}
          </tr>;
        }))}</tbody>
      </table></div> : <EmptyState
        icon={GraduationCap}
        title={summary.total ? 'No matching enrollments' : 'No enrollment access yet'}
        description={summary.total
          ? 'Try another Student, Course, Batch, Agent, or status filter.'
          : 'Choose an active Student, then assign a Course, Batch, and Education Agent using the existing enrollment workflow.'}
        action={!summary.total ? <Button icon={Plus} onClick={openPicker}>Add enrollment</Button> : undefined}
      />}
    </Card>

    <Modal
      open={pickerOpen}
      onClose={() => setPickerOpen(false)}
      title="Choose student"
      description="Select an active Student. The existing enrollment manager will handle Course, Batch, Agent, dates, and status rules."
      footer={<>
        <Button variant="secondary" onClick={() => setPickerOpen(false)}>Cancel</Button>
        <Button onClick={managePickedStudent} disabled={!pickerStudentId}>Continue</Button>
      </>}
    >
      <div className="education-enrollment-picker">
        <label className="education-enrollment-search">
          <Search />
          <input
            value={pickerSearch}
            onChange={(event) => setPickerSearch(event.target.value)}
            placeholder="Search active students"
            aria-label="Search active students"
          />
        </label>
        <label>
          <span>Active student</span>
          <select value={pickerStudentId} onChange={(event) => setPickerStudentId(event.target.value)} aria-label="Choose active student">
            <option value="">Select student</option>
            {activeStudents.map((student) => <option key={student.id} value={student.id}>{student.studentNumber} · {student.name}</option>)}
          </select>
        </label>
        {!activeStudents.length ? <p>No active Students match this search. Reactivate or create a Student first.</p> : null}
      </div>
    </Modal>

    <StudentEnrollmentsModal
      defaultAgentId={agentId === 'all' ? undefined : agentId}
      student={managedStudent}
      open={Boolean(managedStudent)}
      onClose={closeManager}
    />
  </div>;
}

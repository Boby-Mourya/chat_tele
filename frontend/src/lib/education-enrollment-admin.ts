import type { EducationBatch, EducationCourse } from '@/lib/education-api';
import type { EducationEnrollment, EnrollmentStatus } from '@/lib/education-enrollment-api';
import type { EducationStudent } from '@/lib/education-student-api';
import type { Agent } from '@/types';

export type EnrollmentStatusFilter = 'all' | EnrollmentStatus;
export type EnrollmentAdminAgent = Pick<Agent, 'id' | 'publicId' | 'name'>;

export interface EnrollmentAdminFilters {
  status: EnrollmentStatusFilter;
  courseId: string;
  batchId: string;
  agentId: string;
  search: string;
}

export interface EnrollmentAdminSummary {
  total: number;
  active: number;
  pending: number;
  restricted: number;
}

export function enrollmentAdminSummary(enrollments: readonly EducationEnrollment[]): EnrollmentAdminSummary {
  return {
    total: enrollments.length,
    active: enrollments.filter((item) => item.status === 'active').length,
    pending: enrollments.filter((item) => item.status === 'pending').length,
    restricted: enrollments.filter((item) => (
      item.status === 'suspended' || item.status === 'expired' || item.status === 'revoked'
    )).length,
  };
}

export function batchesForCourse(
  batches: readonly EducationBatch[],
  courseId: string,
): EducationBatch[] {
  return batches.filter((batch) => courseId === 'all' || batch.courseId === courseId);
}

export function activeStudentsForEnrollment(
  students: readonly EducationStudent[],
  search: string,
): EducationStudent[] {
  const query = search.trim().toLowerCase();
  return students
    .filter((student) => student.status === 'active')
    .filter((student) => (
      !query
      || `${student.studentNumber} ${student.name} ${student.email ?? ''}`.toLowerCase().includes(query)
    ))
    .sort((left, right) => left.name.localeCompare(right.name) || left.studentNumber.localeCompare(right.studentNumber));
}

export function filterEnrollmentAdminRecords(
  enrollments: readonly EducationEnrollment[],
  students: readonly EducationStudent[],
  courses: readonly EducationCourse[],
  batches: readonly EducationBatch[],
  agents: readonly EnrollmentAdminAgent[],
  filters: EnrollmentAdminFilters,
): EducationEnrollment[] {
  const studentById = new Map(students.map((student) => [student.id, student]));
  const courseById = new Map(courses.map((course) => [course.id, course]));
  const batchById = new Map(batches.map((batch) => [batch.id, batch]));
  const agentById = new Map(agents.map((agent) => [agent.id, agent]));
  const query = filters.search.trim().toLowerCase();

  return enrollments.filter((enrollment) => {
    if (filters.status !== 'all' && enrollment.status !== filters.status) return false;
    if (filters.courseId !== 'all' && enrollment.courseId !== filters.courseId) return false;
    if (filters.batchId !== 'all' && enrollment.batchId !== filters.batchId) return false;
    if (filters.agentId !== 'all' && enrollment.agentId !== filters.agentId) return false;
    if (!query) return true;

    const student = studentById.get(enrollment.studentId);
    const course = courseById.get(enrollment.courseId);
    const batch = batchById.get(enrollment.batchId);
    const agent = agentById.get(enrollment.agentId);
    return [
      student?.studentNumber,
      student?.name,
      student?.email,
      course?.code,
      course?.name,
      batch?.code,
      batch?.name,
      agent?.publicId,
      agent?.name,
      enrollment.status,
    ].filter(Boolean).join(' ').toLowerCase().includes(query);
  });
}

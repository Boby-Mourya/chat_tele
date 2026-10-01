import { describe, expect, it } from 'vitest';
import {
  activeStudentsForEnrollment,
  batchesForCourse,
  enrollmentAdminSummary,
  filterEnrollmentAdminRecords,
} from '@/lib/education-enrollment-admin';

const students = [
  { id: 'student-1', tenantId: 'tenant-1', workspaceId: 'workspace-1', studentNumber: 'NS-1001', name: 'Asha Student', email: 'asha@example.com', customFields: {}, status: 'active', createdAt: '', updatedAt: '' },
  { id: 'student-2', tenantId: 'tenant-1', workspaceId: 'workspace-1', studentNumber: 'NS-1002', name: 'Ravi Archived', email: 'ravi@example.com', customFields: {}, status: 'archived', createdAt: '', updatedAt: '' },
] as const;

const courses = [
  { id: 'course-1', tenantId: 'tenant-1', workspaceId: 'workspace-1', code: 'CPA', name: 'CPA Program', description: '', status: 'active', createdAt: '', updatedAt: '' },
  { id: 'course-2', tenantId: 'tenant-1', workspaceId: 'workspace-1', code: 'CMA', name: 'CMA Program', description: '', status: 'active', createdAt: '', updatedAt: '' },
] as const;

const batches = [
  { id: 'batch-1', tenantId: 'tenant-1', workspaceId: 'workspace-1', courseId: 'course-1', code: 'CPA-26', name: 'CPA 2026', description: '', startsOn: null, endsOn: null, status: 'active', createdAt: '', updatedAt: '' },
  { id: 'batch-2', tenantId: 'tenant-1', workspaceId: 'workspace-1', courseId: 'course-2', code: 'CMA-26', name: 'CMA 2026', description: '', startsOn: null, endsOn: null, status: 'active', createdAt: '', updatedAt: '' },
] as const;

const agents = [
  { id: 'agent-1', publicId: 'agent-cpa', name: 'CPA Mentor' },
  { id: 'agent-2', publicId: 'agent-cma', name: 'CMA Mentor' },
] as const;

const enrollments = [
  { id: 'enrollment-1', tenantId: 'tenant-1', workspaceId: 'workspace-1', studentId: 'student-1', courseId: 'course-1', batchId: 'batch-1', agentId: 'agent-1', startsOn: '2026-01-01', endsOn: null, status: 'active', createdAt: '', updatedAt: '' },
  { id: 'enrollment-2', tenantId: 'tenant-1', workspaceId: 'workspace-1', studentId: 'student-2', courseId: 'course-2', batchId: 'batch-2', agentId: 'agent-2', startsOn: null, endsOn: '2026-12-31', status: 'suspended', createdAt: '', updatedAt: '' },
] as const;

describe('education enrollment admin helpers', () => {
  it('summarizes access without dropping terminal history', () => {
    expect(enrollmentAdminSummary(enrollments)).toEqual({ total: 2, active: 1, pending: 0, restricted: 1 });
  });

  it('keeps Course/Batch/Agent/status/search filters composable', () => {
    expect(filterEnrollmentAdminRecords(
      enrollments,
      students,
      courses,
      batches,
      agents,
      { status: 'active', courseId: 'course-1', batchId: 'batch-1', agentId: 'agent-1', search: 'asha@example.com' },
    ).map((item) => item.id)).toEqual(['enrollment-1']);

    expect(filterEnrollmentAdminRecords(
      enrollments,
      students,
      courses,
      batches,
      agents,
      { status: 'all', courseId: 'course-1', batchId: 'all', agentId: 'all', search: 'ravi' },
    )).toEqual([]);
  });

  it('narrows Batch choices by Course and excludes archived Students from new enrollment', () => {
    expect(batchesForCourse(batches, 'course-1').map((batch) => batch.id)).toEqual(['batch-1']);
    expect(activeStudentsForEnrollment(students, '').map((student) => student.id)).toEqual(['student-1']);
    expect(activeStudentsForEnrollment(students, 'ravi')).toEqual([]);
  });
});

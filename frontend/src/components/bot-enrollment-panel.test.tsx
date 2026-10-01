import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider } from '@/components/providers';
import { BotEnrollmentPanel } from './bot-enrollment-panel';
import { demoAgents } from '@/lib/demo-data';
import type { EducationCourse, EducationBatch } from '@/lib/education-api';

const mocks = vi.hoisted(() => ({ preview: vi.fn(), commit: vi.fn(), parse: vi.fn() }));
vi.mock('@/lib/education-student-import-api', () => ({ educationStudentImportApi: mocks }));
vi.mock('@/lib/education-enrollment-events-api', () => ({ enrollmentReadiness: vi.fn().mockResolvedValue({ whatsappConnected: true, verifiedStudentNumbers: 0, pendingStudentNumbers: 1, knowledgeSources: 0, aiProviderConfigured: false }) }));
vi.mock('@/lib/education-student-import-file-api', () => ({ parseStudentImportFile: mocks.parse, serializeStudentImportRows: JSON.stringify }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
const agent = { ...demoAgents[0]!, purpose: 'education' as const, whatsappNumber: '+919876543210' };
const course = { id: 'course-1', name: 'CMA', code: 'CMA', status: 'active' } as EducationCourse;
const batch = { id: 'batch-1', name: '2026', code: 'CMA-2026', courseId: course.id, status: 'active', startsOn: null, endsOn: null } as EducationBatch;

describe('bot enrollment setup', () => {
  it('assigns the upload to the selected bot and previews before committing', async () => {
    const row = { studentNumber: 'ST-1', name: 'Student One', identityType: 'whatsapp', identifier: '+919812345678', courseCode: 'OLD', batchCode: 'OLD', agentPublicId: 'old-bot' };
    mocks.parse.mockResolvedValue([row]);
    mocks.preview.mockImplementation(async (rows) => ({ totalRows: 1, validRows: 1, invalidRows: 0, rows: [{ rowNumber: 1, valid: true, row: rows[0], errors: [], warnings: [] }] }));
    mocks.commit.mockResolvedValue({ committed: true, preview: null, result: { createdStudents: 1, createdEnrollments: 1 } });
    const onSaved = vi.fn();
    render(<MemoryRouter><ToastProvider><BotEnrollmentPanel agent={agent} courses={[course]} batches={[batch]} onSaved={onSaved} /></ToastProvider></MemoryRouter>);
    await userEvent.upload(screen.getByLabelText('Upload bot enrollments'), new File(['csv'], 'students.csv', { type: 'text/csv' }));
    await waitFor(() => expect(mocks.preview).toHaveBeenCalledWith([expect.objectContaining({ agentPublicId: agent.publicId, courseCode: course.code, batchCode: batch.code })]));
    expect(mocks.commit).not.toHaveBeenCalled();
    await userEvent.click(await screen.findByRole('button', { name: 'Enroll 1 students' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });
  it('shows a bot-specific endpoint and a payment/access request example', async () => {
    render(<MemoryRouter><ToastProvider><BotEnrollmentPanel agent={agent} courses={[course]} batches={[batch]} onSaved={() => {}} /></ToastProvider></MemoryRouter>);
    await userEvent.click(screen.getByRole('button', { name: 'Automatic enrollment API' }));
    expect(screen.getByLabelText('POST endpoint')).toHaveValue(`${window.location.origin}/api/v1/education/agents/${agent.id}/enrollment-events`);
    const input = screen.getByLabelText('JSON request example') as HTMLTextAreaElement;
    const body = JSON.parse(input.value);
    expect(body.paymentStatus).toBe('paid'); expect(body.accessGranted).toBe(true);
    expect(body.row.agentPublicId).toBe(agent.publicId); expect(body.row.identityVerified).toBe(false);
  });
});

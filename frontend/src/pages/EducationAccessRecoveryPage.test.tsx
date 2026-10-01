import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { EducationAccessRecoveryPage } from '@/pages/EducationAccessRecoveryPage';

const mocks = vi.hoisted(() => ({
  start: vi.fn(),
  verify: vi.fn(),
  createSupportRequest: vi.fn(),
}));

vi.mock('@/lib/education-access-recovery-api', () => ({
  educationAccessRecoveryApi: {
    start: mocks.start,
    verify: mocks.verify,
  },
}));

vi.mock('@/lib/education-access-request-api', () => ({
  educationAccessRequestApi: {
    create: mocks.createSupportRequest,
  },
}));

function renderPage(path = '/education-access-recovery?agent=agt_public_test') {
  return render(<MemoryRouter initialEntries={[path]}><EducationAccessRecoveryPage /></MemoryRouter>);
}

describe('EducationAccessRecoveryPage', () => {
  beforeEach(() => {
    mocks.start.mockResolvedValue({
      accepted: true,
      requestId: '11111111-1111-1111-1111-111111111111',
      expiresInSeconds: 600,
    });
    mocks.verify.mockResolvedValue({ verified: true, alreadyVerified: false });
    mocks.createSupportRequest.mockResolvedValue({
      accepted: true,
      requestId: '22222222-2222-2222-2222-222222222222',
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('prefills the public Agent id and submits Student proof without requiring a SaaS login', async () => {
    const user = userEvent.setup();
    renderPage();

    expect(screen.getByLabelText('Education Agent ID')).toHaveValue('agt_public_test');
    await user.type(screen.getByLabelText('Student ID'), 'student-001');
    await user.type(screen.getByLabelText('Student email'), 'Student@Example.com');
    await user.type(screen.getByLabelText('WhatsApp number'), '+919876543210');
    await user.click(screen.getByRole('button', { name: /send verification code/i }));

    await waitFor(() => expect(mocks.start).toHaveBeenCalledWith({
      agentPublicId: 'agt_public_test',
      studentNumber: 'student-001',
      email: 'Student@Example.com',
      identityType: 'whatsapp',
      identifier: '+919876543210',
    }));
    expect(await screen.findByText('Enter verification code')).toBeInTheDocument();
    expect(screen.getByText(/if those details match an active enrollment/i)).toBeInTheDocument();
  });

  it('verifies the six-digit code using the opaque request id returned by start', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText('Student ID'), 'STUDENT-001');
    await user.type(screen.getByLabelText('Student email'), 'student@example.com');
    await user.type(screen.getByLabelText('WhatsApp number'), '+919876543210');
    await user.click(screen.getByRole('button', { name: /send verification code/i }));

    await screen.findByText('Enter verification code');
    await user.type(screen.getByLabelText('Six-digit code'), '123456');
    await user.click(screen.getByRole('button', { name: /verify student identity/i }));

    await waitFor(() => expect(mocks.verify).toHaveBeenCalledWith(
      '11111111-1111-1111-1111-111111111111',
      '123456',
    ));
    expect(await screen.findByText('Access verified')).toBeInTheDocument();
    expect(screen.getByText(/return to the Education Agent and send the message again/i)).toBeInTheDocument();
  });

  it('does not disclose enrollment validity in the start confirmation', async () => {
    const user = userEvent.setup();
    renderPage('/education-access-recovery');
    await user.type(screen.getByLabelText('Education Agent ID'), 'agt_unknown');
    await user.type(screen.getByLabelText('Student ID'), 'UNKNOWN');
    await user.type(screen.getByLabelText('Student email'), 'unknown@example.com');
    await user.type(screen.getByLabelText('WhatsApp number'), '+919999999999');
    await user.click(screen.getByRole('button', { name: /send verification code/i }));

    expect(await screen.findByText(/if those details match an active enrollment/i)).toBeInTheDocument();
    expect(screen.queryByText(/student not found/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/enrollment not found/i)).not.toBeInTheDocument();
  });

  it('submits the same student proof to academy support without exposing whether it matched', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText('Student ID'), 'STUDENT-009');
    await user.type(screen.getByLabelText('Student email'), 'student9@example.com');
    await user.type(screen.getByLabelText('WhatsApp number'), '+919811112222');
    await user.type(screen.getByLabelText('Support note'), 'My OTP never arrives.');
    await user.click(screen.getByRole('button', { name: /request academy support/i }));

    await waitFor(() => expect(mocks.createSupportRequest).toHaveBeenCalledWith({
      agentPublicId: 'agt_public_test',
      studentNumber: 'STUDENT-009',
      email: 'student9@example.com',
      identityType: 'whatsapp',
      identifier: '+919811112222',
      message: 'My OTP never arrives.',
    }));
    expect(screen.getByText(/request has been sent for academy review/i)).toBeInTheDocument();
    expect(screen.getByText(/does not disclose whether the submitted enrollment details matched/i)).toBeInTheDocument();
  });
});

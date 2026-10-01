import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MFASecurityPanel } from '@/components/mfa-security-panel';

const mocks = vi.hoisted(() => ({
  status: vi.fn(),
  setup: vi.fn(),
  confirm: vi.fn(),
  regenerateRecoveryCodes: vi.fn(),
  disable: vi.fn(),
  pushToast: vi.fn(),
  createQrAssets: vi.fn(),
}));

vi.mock('@/components/providers', () => ({
  useToast: () => ({ pushToast: mocks.pushToast }),
}));

vi.mock('@/lib/mfa-api', () => ({
  mfaApi: {
    status: mocks.status,
    setup: mocks.setup,
    confirm: mocks.confirm,
    regenerateRecoveryCodes: mocks.regenerateRecoveryCodes,
    disable: mocks.disable,
  },
}));

vi.mock('@/lib/qr', () => ({
  createQrAssets: mocks.createQrAssets,
}));

const recoveryCodes = [
  'AAAA-BBBB-CCCC',
  'DDDD-EEEE-FFFF',
  'GGGG-HHHH-JJJJ',
  'KKKK-LLLL-MMMM',
  'NNNN-PPPP-QQQQ',
  'RRRR-SSSS-TTTT',
  'UUUU-VVVV-WWWW',
  'XXXX-YYYY-ZZZZ',
  '2345-6789-ABCD',
  'EFGH-JKLM-NPQR',
];

const disabledStatus = {
  configured: false,
  enabled: false,
  confirmedAt: null,
  unusedRecoveryCodes: 0,
};

const enabledStatus = {
  configured: true,
  enabled: true,
  confirmedAt: '2026-09-10T10:00:00Z',
  unusedRecoveryCodes: 10,
};

describe('MFASecurityPanel', () => {
  beforeEach(() => {
    mocks.status.mockReset();
    mocks.setup.mockReset();
    mocks.confirm.mockReset();
    mocks.regenerateRecoveryCodes.mockReset();
    mocks.disable.mockReset();
    mocks.pushToast.mockReset();
    mocks.createQrAssets.mockReset();
    mocks.createQrAssets.mockResolvedValue({ pngDataUrl: 'data:image/png;base64,qr', svg: '<svg />' });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('runs the complete setup flow before enabling MFA', async () => {
    const user = userEvent.setup();
    mocks.status.mockResolvedValueOnce(disabledStatus).mockResolvedValue(enabledStatus);
    mocks.setup.mockResolvedValue({
      secret: 'JBSWY3DPEHPK3PXP',
      otpauthUri: 'otpauth://totp/Northstar%3Aowner%40example.com?secret=JBSWY3DPEHPK3PXP',
      recoveryCodes,
    });
    mocks.confirm.mockResolvedValue({ accessToken: 'rotated-access' });

    render(<MFASecurityPanel />);

    expect(await screen.findByText('Not enabled')).toBeInTheDocument();
    await user.type(screen.getByLabelText('Current password'), 'Password-2026!');
    await user.click(screen.getByRole('button', { name: /Set up authenticator/ }));

    await waitFor(() => expect(mocks.setup).toHaveBeenCalledWith('Password-2026!'));
    expect(await screen.findByText('JBSWY3DPEHPK3PXP')).toBeInTheDocument();
    expect(screen.getByText('AAAA-BBBB-CCCC')).toBeInTheDocument();
    expect(await screen.findByAltText('Authenticator setup QR code')).toBeInTheDocument();

    await user.click(screen.getByLabelText(/I saved these recovery codes securely/));
    await user.type(screen.getByLabelText('6-digit code'), '123456');
    await user.click(screen.getByRole('button', { name: 'Enable MFA' }));

    await waitFor(() => expect(mocks.confirm).toHaveBeenCalledWith('123456'));
    expect(await screen.findByText('Enabled')).toBeInTheDocument();
    expect(mocks.pushToast).toHaveBeenCalledWith('Multi-factor authentication enabled');
  });

  it('requires explicit confirmation that recovery codes were saved', async () => {
    const user = userEvent.setup();
    mocks.status.mockResolvedValue(disabledStatus);
    mocks.setup.mockResolvedValue({
      secret: 'JBSWY3DPEHPK3PXP',
      otpauthUri: 'otpauth://totp/example',
      recoveryCodes,
    });

    render(<MFASecurityPanel />);
    await screen.findByText('Not enabled');
    await user.type(screen.getByLabelText('Current password'), 'Password-2026!');
    await user.click(screen.getByRole('button', { name: /Set up authenticator/ }));
    await screen.findByText('AAAA-BBBB-CCCC');
    await user.type(screen.getByLabelText('6-digit code'), '123456');
    await user.click(screen.getByRole('button', { name: 'Enable MFA' }));

    expect(screen.getByRole('alert')).toHaveTextContent('Save your recovery codes');
    expect(mocks.confirm).not.toHaveBeenCalled();
  });

  it('regenerates recovery codes and can disable MFA with a recovery factor', async () => {
    const user = userEvent.setup();
    const nextCodes = recoveryCodes.map((code) => `NEW-${code}`);
    mocks.status.mockResolvedValue(enabledStatus);
    mocks.regenerateRecoveryCodes.mockResolvedValue({ recoveryCodes: nextCodes });
    mocks.disable.mockResolvedValue({ accessToken: 'disabled-rotated-access' });

    render(<MFASecurityPanel />);
    expect(await screen.findByText('Enabled')).toBeInTheDocument();

    await user.type(screen.getByLabelText('Current password'), 'Password-2026!');
    await user.click(screen.getByRole('button', { name: 'Use a recovery code' }));
    await user.type(screen.getByLabelText('Recovery code'), 'abcd-efgh-jklm');
    await user.click(screen.getByRole('button', { name: /Regenerate recovery codes/ }));

    await waitFor(() => expect(mocks.regenerateRecoveryCodes).toHaveBeenCalledWith({
      currentPassword: 'Password-2026!',
      recoveryCode: 'ABCD-EFGH-JKLM',
    }));
    expect(await screen.findByText('NEW-AAAA-BBBB-CCCC')).toBeInTheDocument();

    await user.type(screen.getByLabelText('Current password'), 'Password-2026!');
    await user.type(screen.getByLabelText('Recovery code'), 'newa-newb-newc');
    await user.click(screen.getByRole('button', { name: 'Disable MFA' }));

    await waitFor(() => expect(mocks.disable).toHaveBeenCalledWith({
      currentPassword: 'Password-2026!',
      recoveryCode: 'NEWA-NEWB-NEWC',
    }));
  });
});

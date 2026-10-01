import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '@/components/providers';
import { HelpSupportPage } from '@/pages/HelpSupportPage';
import { demoHelpHome } from '@/lib/help-demo-data';

const apiMocks = vi.hoisted(() => ({ home: vi.fn(), supportRequests: vi.fn(), createSupportRequest: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: { help: apiMocks } }));

describe('HelpSupportPage', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); });
  it('validates and submits a support request with safe context', async () => {
    const user = userEvent.setup();
    apiMocks.home.mockResolvedValue(demoHelpHome());
    apiMocks.supportRequests.mockResolvedValue([]);
    apiMocks.createSupportRequest.mockResolvedValue({ id: 'request-1' });
    render(<MemoryRouter initialEntries={['/help/support?from=%2Fagents']}><ToastProvider><HelpSupportPage /></ToastProvider></MemoryRouter>);
    await user.type(await screen.findByLabelText('Subject'), 'Agent setup issue');
    await user.type(screen.getByLabelText('Description'), 'I need help finishing this agent configuration correctly.');
    await user.click(screen.getByRole('button', { name: 'Send support request' }));
    expect(apiMocks.createSupportRequest).toHaveBeenCalledWith(expect.objectContaining({ contextPath: '/agents', includeDiagnostics: true }));
  });
});

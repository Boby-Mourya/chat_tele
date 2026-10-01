import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LeadLayoutEditor } from './lead-layout-editor';
import { LeadDetailsEditor } from './lead-details-editor';
import { defaultLayout, leadColumnValue, type LeadLayout } from '@/lib/lead-layout-api';
import { demoLeads } from '@/lib/demo-data';

const mocks = vi.hoisted(() => ({ save: vi.fn(), importTemplate: vi.fn(), edit: vi.fn() }));
vi.mock('@/lib/lead-layout-api', async (original) => {
  const actual = await original<typeof import('@/lib/lead-layout-api')>();
  return { ...actual, leadLayoutApi: mocks };
});
vi.mock('@/lib/lead-crm-api', () => ({ leadCrmApi: { connections: async () => [] } }));

describe('custom lead layouts', () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); });
  beforeEach(() => { mocks.save.mockImplementation(async (layout: LeadLayout) => ({ ...layout, version: layout.version + 1 })); });
  it('previews uploaded headers and saves their order and sources', async () => {
    const user = userEvent.setup(); const onSaved = vi.fn();
    mocks.importTemplate.mockResolvedValue({ name: 'Uploaded format', version: 0, columns: [
      { ...defaultLayout.columns[0], id: 'email', label: 'Student email', source: 'email' },
      { ...defaultLayout.columns[0], id: 'course', label: 'Course', source: 'fields.course' },
    ] });
    render(<LeadLayoutEditor initial={defaultLayout} records={demoLeads} onClose={vi.fn()} onSaved={onSaved} />);
    await user.upload(screen.getByLabelText('Upload sample format'), new File(['Student email,Course\n'], 'format.csv', { type: 'text/csv' }));
    expect(await screen.findByRole('columnheader', { name: 'Student email' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Move Course up' }));
    await user.click(screen.getByRole('button', { name: 'Save layout' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(mocks.save.mock.calls[0]![0].columns.map((c: { source: string }) => c.source)).toEqual(['fields.course', 'email']);
  });
  it('submits typed custom lead details without losing false values', async () => {
    const user = userEvent.setup(); mocks.edit.mockResolvedValue(demoLeads[0]);
    const layout: LeadLayout = { ...defaultLayout, columns: [{ ...defaultLayout.columns[0]!, source: 'fields.follow_up', label: 'Follow up', type: 'boolean' }] };
    render(<LeadDetailsEditor lead={demoLeads[0]!} layout={layout} onClose={vi.fn()} onSaved={vi.fn()} />);
    await user.selectOptions(screen.getByLabelText('Follow up'), 'false');
    await user.click(screen.getByRole('button', { name: 'Save lead' }));
    await waitFor(() => expect(mocks.edit).toHaveBeenCalledWith(demoLeads[0]!.id, expect.objectContaining({ fields: { follow_up: false } })));
  });
  it('formats dates consistently without shifting the calendar date', () => {
    expect(leadColumnValue({ ...demoLeads[0]!, consent: true }, { ...defaultLayout.columns[0]!, source: 'consent', format: 'upper' })).toBe('TRUE');
    const lead = { ...demoLeads[0]!, createdAt: '2026-09-15T00:01:00+05:30' };
    expect(leadColumnValue(lead, { ...defaultLayout.columns[0]!, source: 'createdAt', format: 'dd/mm/yyyy' })).toBe('15/09/2026');
  });
});

import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ExtractionReviewModal } from '@/components/extraction-review-modal';
import type { ExtractionRecord } from '@/lib/api';
import type { KnowledgeSource } from '@/types';

const mocks = vi.hoisted(() => ({ extraction: vi.fn(), extractionPage: vi.fn(), approveExtraction: vi.fn(), retryExtraction: vi.fn(), extractionArchive: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: { knowledge: mocks } }));
const source: KnowledgeSource = { id: 'source', agentId: 'agent', name: 'lesson.pdf', kind: 'file', status: 'needs_review', sizeLabel: '', chunks: 0, updatedAt: '' };
const base: ExtractionRecord = {
  schema_version: 2, extraction_revision: 3, source_sha256: 'hash', review_status: 'needs_review', checks: [], release_blockers: [],
  pages: [{ number: 1, native_text: 'Value -12.50', visual_text: 'Value 12.50', selected_text: null, image: null, requires_second_review: true,
    blocks: [{ id: 'P0001-R0001', type: 'paragraph', status: 'candidate', native_text: 'Value -12.50', selected_text: null,
      visual: { kind: 'paragraph', text: 'Value 12.50', complete: true } }] }],
  issues: [{ id: 'I000001', page: 1, code: 'NUMERIC_CONFLICT', message: 'Sign differs', status: 'open' }],
};

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  mocks.extraction.mockResolvedValue(structuredClone(base));
  mocks.approveExtraction.mockResolvedValue({ ...source });
});

describe('Extraction source review', () => {
  it('sends versioned structured decisions and keeps a pending second review open', async () => {
    const user = userEvent.setup();
    const approved = vi.fn();
    render(<ExtractionReviewModal source={source} onClose={vi.fn()} onApproved={approved} />);
    await screen.findByText(/Independent second review: required/);
    await user.clear(screen.getByLabelText('Selected region text'));
    await user.type(screen.getByLabelText('Selected region text'), 'Value -12.50');
    await user.selectOptions(screen.getByLabelText('Decision for I000001'), 'source_verified');
    await user.type(screen.getByLabelText('Source evidence and reason for I000001'), 'Visible minus sign in original');
    await user.type(screen.getByLabelText('Reason for page review'), 'Compared to the original');
    await user.click(screen.getByRole('checkbox', { name: /I checked every source/ }));
    await user.click(screen.getByRole('button', { name: 'Save page review' }));
    await screen.findByRole('status');
    expect(mocks.approveExtraction).toHaveBeenCalledWith('source', expect.objectContaining({
      extractionRevision: 3,
      pages: [expect.objectContaining({ selectedText: 'Value -12.50', structureConfirmed: true,
        blocks: [expect.objectContaining({ id: 'P0001-R0001', structure: expect.objectContaining({ text: 'Value -12.50' }) })] })],
      issueResolutions: [{ id: 'I000001', action: 'source_verified', reason: 'Visible minus sign in original' }],
    }));
    expect(approved).not.toHaveBeenCalled();
  });

  it('blocks technical failures without offering a source-verification override', async () => {
    mocks.extraction.mockResolvedValue({ ...base, issues: [{ id: 'T1', page: 1, code: 'VISION_UNAVAILABLE', message: 'Failed call', technical: true, status: 'open' }] });
    render(<ExtractionReviewModal source={source} onClose={vi.fn()} onApproved={vi.fn()} />);
    await screen.findByText('Failed call');
    expect(screen.getByRole('button', { name: 'Save page review' })).toBeDisabled();
    expect(screen.queryByLabelText('Decision for T1')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Download evidence' })).toBeEnabled();
  });

  it('invalidates confirmation when structured content changes', async () => {
    const user = userEvent.setup();
    render(<ExtractionReviewModal source={source} onClose={vi.fn()} onApproved={vi.fn()} />);
    await screen.findByLabelText('Selected region text');
    const confirm = screen.getByRole('checkbox', { name: /I checked every source/ });
    await user.click(confirm);
    expect(confirm).toBeChecked();
    await user.type(screen.getByLabelText('Selected region text'), 'changed');
    expect(confirm).not.toBeChecked();
  });

  it('notifies the parent only after the server releases the extraction', async () => {
    const user = userEvent.setup();
    const approved = vi.fn();
    mocks.approveExtraction.mockResolvedValue({ ...source, status: 'processing' });
    render(<ExtractionReviewModal source={source} onClose={vi.fn()} onApproved={approved} />);
    await screen.findByLabelText('Reason for page review');
    await user.type(screen.getByLabelText('Reason for page review'), 'Second source review');
    await user.click(screen.getByRole('checkbox', { name: /I checked every source/ }));
    await user.click(screen.getByRole('button', { name: 'Save page review' }));
    await waitFor(() => expect(approved).toHaveBeenCalledWith('Verified extraction released'));
  });
});

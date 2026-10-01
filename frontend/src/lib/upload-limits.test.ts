import { expect, it, vi } from 'vitest';
import { api } from './api';
import { KNOWLEDGE_UPLOAD_MAX_BYTES, knowledgeFileSizeError } from './upload-limits';

it('accepts exactly 500 MB and rejects even one byte over the cap', () => {
  expect(knowledgeFileSizeError({ size: 524_288_000 })).toBeNull();
  expect(knowledgeFileSizeError({ size: 524_288_001 })).toBe('Files must be 500 MB or smaller.');
  expect(knowledgeFileSizeError({ size: 0 })).toBe('Choose a file that is not empty.');
});

it('rejects an oversized document before hashing or sending any request', async () => {
  const file = new File(['small fixture'], 'large.pdf', { type: 'application/pdf' });
  Object.defineProperty(file, 'size', { value: KNOWLEDGE_UPLOAD_MAX_BYTES + 1 });
  const fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  try {
    await expect(api.knowledge.add('agent-1', { kind: 'file', name: 'large.pdf', file })).rejects.toThrow('Files must be 500 MB or smaller.');
    expect(fetchMock).not.toHaveBeenCalled();
  } finally { vi.unstubAllGlobals(); }
});

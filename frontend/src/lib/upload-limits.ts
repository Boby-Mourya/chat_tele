// Use the same binary MB convention as knowledge-source size labels and the API.
export const KNOWLEDGE_UPLOAD_MAX_MB = 500;
export const KNOWLEDGE_UPLOAD_MAX_BYTES = KNOWLEDGE_UPLOAD_MAX_MB * 1_048_576;

export function knowledgeFileSizeError(file: Pick<File, 'size'>): string | null {
  if (file.size <= 0) return 'Choose a file that is not empty.';
  if (file.size > KNOWLEDGE_UPLOAD_MAX_BYTES) return `Files must be ${KNOWLEDGE_UPLOAD_MAX_MB} MB or smaller.`;
  return null;
}

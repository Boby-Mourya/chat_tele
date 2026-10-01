const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';

export type EducationRecoveryIdentityType = 'whatsapp' | 'telegram' | 'website_login';

export interface EducationAccessRecoveryStartInput {
  agentPublicId: string;
  studentNumber: string;
  email: string;
  identityType: EducationRecoveryIdentityType;
  identifier: string;
}

export interface EducationAccessRecoveryAccepted {
  accepted: boolean;
  requestId: string;
  expiresInSeconds: number;
}

export interface EducationAccessRecoveryResult {
  verified: boolean;
  alreadyVerified: boolean;
}

async function errorMessage(response: Response, fallback: string): Promise<Error> {
  let payload: unknown;
  try { payload = await response.json() as unknown; } catch { payload = undefined; }
  if (payload && typeof payload === 'object') {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === 'string' && detail.trim()) return new Error(detail);
    const nested = (payload as { error?: unknown }).error;
    if (nested && typeof nested === 'object') {
      const message = (nested as { message?: unknown }).message;
      if (typeof message === 'string' && message.trim()) return new Error(message);
    }
  }
  return new Error(fallback);
}

export const educationAccessRecoveryApi = {
  async start(input: EducationAccessRecoveryStartInput): Promise<EducationAccessRecoveryAccepted> {
    const response = await fetch(`${API_URL}/education/access-recovery/start`, {
      method: 'POST',
      credentials: 'include',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...input,
        agentPublicId: input.agentPublicId.trim(),
        studentNumber: input.studentNumber.trim(),
        email: input.email.trim().toLowerCase(),
        identifier: input.identifier.trim(),
      }),
    });
    if (!response.ok) throw await errorMessage(response, 'Unable to start education access recovery.');
    return response.json() as Promise<EducationAccessRecoveryAccepted>;
  },

  async verify(requestId: string, code: string): Promise<EducationAccessRecoveryResult> {
    const response = await fetch(`${API_URL}/education/access-recovery/verify`, {
      method: 'POST',
      credentials: 'include',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ requestId, code: code.trim() }),
    });
    if (!response.ok) throw await errorMessage(response, 'Verification code is invalid or expired.');
    return response.json() as Promise<EducationAccessRecoveryResult>;
  },
};

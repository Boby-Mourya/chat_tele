export function apiErrorMessage(reason: unknown, fallback: string): string {
  if (reason instanceof Error && 'detail' in reason && reason.detail && typeof reason.detail === 'object') {
    const payload = reason.detail as { error?: { message?: unknown }; detail?: unknown };
    const message = payload.error?.message ?? payload.detail;
    if (typeof message === 'string' && message.trim()) return message;
  }
  return reason instanceof Error ? reason.message : fallback;
}

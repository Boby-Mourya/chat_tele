import { request } from '@/lib/api';

export type LLMProviderId = 'nvidia' | 'openai' | 'anthropic' | 'google' | 'ollama' | 'openai-compatible';
export interface LLMModelOption {
  id: string;
  name: string;
  description: string;
  provider: LLMProviderId;
  contextWindow: number;
  supportsReasoning: boolean;
}
export interface LLMProviderOption {
  id: LLMProviderId;
  name: string;
  description: string;
  protocol: 'openai-compatible' | 'anthropic-messages' | 'gemini';
  defaultBaseUrl: string;
  requiresApiKey: boolean;
  supportsLocalUrl: boolean;
  models: LLMModelOption[];
}
export interface LLMConnection {
  id: string;
  name: string;
  provider: LLMProviderId;
  endpointUrl: string;
  status: string;
  hasApiKey: boolean;
  metadata: Record<string, string>;
  createdAt: string;
  updatedAt: string;
}

export const llmApi = {
  providers: () => request<LLMProviderOption[]>('/llm/providers'),
  connections: () => request<LLMConnection[]>('/llm/connections'),
  createConnection: (input: { provider: LLMProviderId; name: string; endpointUrl?: string; apiKey?: string; metadata?: Record<string, string> }) =>
    request<LLMConnection>('/llm/connections', { method: 'POST', body: JSON.stringify(input) }),
  updateConnection: (id: string, input: { name?: string; endpointUrl?: string; apiKey?: string; clearApiKey?: boolean; metadata?: Record<string, string> }) =>
    request<LLMConnection>(`/llm/connections/${id}`, { method: 'PATCH', body: JSON.stringify(input) }),
  deleteConnection: (id: string) => request<void>(`/llm/connections/${id}`, { method: 'DELETE' }),
};

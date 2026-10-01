import { Code2, Database } from 'lucide-react';
import { Zoho, Salesforce, HubSpot, Dynamics, Pipedrive, Freshsales, Slack, WhatsApp, Messenger, Instagram, Telegram } from '@/components/provider-logo';

export const integrationCategories = ['All integrations', 'CRM', 'Channels', 'Developer'] as const;
export type IntegrationCategory = typeof integrationCategories[number];
export const integrationCatalog = [
  { id: 'zoho', name: 'Zoho CRM', category: 'CRM', icon: Zoho, description: 'Keep leads, contacts and customer updates in sync.', accent: 'zoho' },
  { id: 'salesforce', name: 'Salesforce', category: 'CRM', icon: Salesforce, description: 'Connect your sales team and keep lead records up to date.', accent: 'salesforce' },
  { id: 'hubspot', name: 'HubSpot', category: 'CRM', icon: HubSpot, description: 'Bring new leads and customer contacts into HubSpot.', accent: 'hubspot' },
  { id: 'dynamics365', name: 'Microsoft Dynamics 365', category: 'CRM', icon: Dynamics, description: 'Sync leads with your Dynamics 365 organization.', accent: 'dynamics' },
  { id: 'pipedrive', name: 'Pipedrive', category: 'CRM', icon: Pipedrive, description: 'Send qualified leads to your sales workspace.', accent: 'pipedrive' },
  { id: 'freshsales', name: 'Freshsales', category: 'CRM', icon: Freshsales, description: 'Connect your Freshsales account using an API key.', accent: 'freshsales' },
  { id: 'widget', name: 'Website widget', category: 'Channels', icon: Code2, description: 'Embed your agent on your website and start conversations.', accent: 'channel' },
  { id: 'slack', name: 'Slack', category: 'Channels', icon: Slack, description: 'Let your agent answer questions in Slack.', accent: 'channel' },
  { id: 'whatsapp', name: 'WhatsApp', category: 'Channels', icon: WhatsApp, description: 'Support your WhatsApp Business customers.', accent: 'channel' },
  { id: 'facebook_messenger', name: 'Facebook Messenger', category: 'Channels', icon: Messenger, description: 'Answer customers in your Facebook Page inbox.', accent: 'channel' },
  { id: 'instagram', name: 'Instagram', category: 'Channels', icon: Instagram, description: 'Respond to messages from your professional account.', accent: 'channel' },
  { id: 'telegram', name: 'Telegram', category: 'Channels', icon: Telegram, description: 'Connect a Telegram bot to your workspace agent.', accent: 'channel' },
  { id: 'generic_rest', name: 'Custom CRM API', category: 'Developer', icon: Database, description: 'Connect another CRM through its REST API.', accent: 'channel' },
] as const;
export type CatalogIntegration = typeof integrationCatalog[number];
export interface ConnectionField { key: string; label: string; hint?: string; type?: 'password' | 'url'; placeholder?: string }
export const channelFields: Record<string, ConnectionField[]> = {
  slack: [
    { key: 'bot_token', label: 'Bot user OAuth token', type: 'password', placeholder: 'xoxb-…', hint: 'Find this under OAuth & Permissions in your Slack app.' },
    { key: 'signing_secret', label: 'Signing secret', type: 'password', hint: 'Find this under Basic Information → App Credentials.' },
  ],
  telegram: [
    { key: 'bot_token', label: 'Bot token', type: 'password', hint: 'Use the token supplied by BotFather.' },
    { key: 'webhook_secret', label: 'Webhook secret', type: 'password', hint: 'Choose a secret using letters, numbers, underscores or hyphens. Use the same value when registering the webhook.' },
  ],
  instagram: [
    { key: 'accountId', label: 'Instagram professional account ID' },
    { key: 'access_token', label: 'Access token', type: 'password' },
    { key: 'app_secret', label: 'Meta app secret', type: 'password' },
    { key: 'verify_token', label: 'Webhook verify token', type: 'password', hint: 'Choose a secret and use the same value in your Meta webhook settings.' },
  ],
  facebook_messenger: [
    { key: 'accountId', label: 'Facebook Page ID' },
    { key: 'page_access_token', label: 'Page access token', type: 'password' },
    { key: 'app_secret', label: 'Meta app secret', type: 'password' },
    { key: 'verify_token', label: 'Webhook verify token', type: 'password', hint: 'Choose a secret and use the same value in your Meta webhook settings.' },
  ],
};
export function channelSetupPayload(provider: string, values: Record<string, string>) {
  const credentials = Object.fromEntries((channelFields[provider] ?? []).filter(field => field.key !== 'accountId').map(field => [field.key, values[field.key]]));
  const configuration: Record<string, unknown> = { agentId: values.agentId, leadCaptureDefault: { createLead: true, qualify: false, syncToCRM: false } };
  if (provider === 'instagram') Object.assign(configuration, { instagramAccountId: values.accountId, apiVersion: 'v26.0' });
  if (provider === 'facebook_messenger') Object.assign(configuration, { pageId: values.accountId, apiVersion: 'v26.0' });
  return { provider, name: values.name!.trim(), agentId: values.agentId, credentials, configuration };
}

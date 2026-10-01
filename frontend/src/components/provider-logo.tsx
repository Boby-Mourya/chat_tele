import { forwardRef } from 'react';
import { MessageCircle, type LucideProps } from 'lucide-react';

// Preserve the vendor's colors and proportions inside themed icon slots.
function brandIcon(provider: string, name: string) {
  const Icon = forwardRef<SVGSVGElement, LucideProps>(({ size = 24, className = '', ...props }, ref) => (
    <svg ref={ref} width={size} height={size} viewBox="0 0 32 32" fill="none" className={`provider-logo provider-logo--${provider} ${className}`} role="img" aria-label={name} {...props}>
      <image href={`/brands/${provider}.svg`} width="32" height="32" preserveAspectRatio="xMidYMid meet" />
    </svg>
  ));
  Icon.displayName = `${name}Logo`;
  return Icon;
}

export const WhatsApp = brandIcon('whatsapp', 'WhatsApp');
export const Facebook = brandIcon('facebook', 'Facebook');
export const Messenger = brandIcon('facebook_messenger', 'Messenger');
export const Instagram = brandIcon('instagram', 'Instagram');
export const Slack = brandIcon('slack', 'Slack');
export const Telegram = brandIcon('telegram', 'Telegram');
export const Teams = brandIcon('teams', 'Microsoft Teams');
export const Notion = brandIcon('notion', 'Notion');
export const Zapier = brandIcon('zapier', 'Zapier');
export const Zoho = brandIcon('zoho', 'Zoho');
export const Salesforce = brandIcon('salesforce', 'Salesforce');
export const HubSpot = brandIcon('hubspot', 'HubSpot');
export const Dynamics = brandIcon('dynamics365', 'Microsoft Dynamics 365');
export const Pipedrive = brandIcon('pipedrive', 'Pipedrive');
export const Freshsales = brandIcon('freshsales', 'Freshsales');

const logos: Record<string, typeof WhatsApp> = { whatsapp: WhatsApp, facebook: Facebook, facebook_messenger: Messenger, instagram: Instagram, slack: Slack, telegram: Telegram, teams: Teams, notion: Notion, zapier: Zapier, zoho: Zoho, salesforce: Salesforce, hubspot: HubSpot, dynamics365: Dynamics, pipedrive: Pipedrive, freshsales: Freshsales };
export function ProviderLogo({ provider, ...props }: LucideProps & { provider: string }) {
  const Icon = logos[provider] ?? MessageCircle;
  return <Icon {...props} />;
}

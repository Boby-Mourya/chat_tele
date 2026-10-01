import { Badge } from '@/components/ui';
import type { HelpAudienceRole } from '@/lib/help-types';

export function HelpRoleBadge({ roles }: { roles: HelpAudienceRole[] }) {
  if (roles.length === 4) return null;
  const label = roles.includes('owner') && roles.includes('admin') && roles.length === 2 ? 'Owner / Admin' : roles.map((role) => role[0]!.toUpperCase() + role.slice(1)).join(', ');
  return <Badge tone="purple">Applies to: {label}</Badge>;
}

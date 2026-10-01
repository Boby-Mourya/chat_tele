import {
  BarChart3, BookOpen, CircleHelp, Code2, ContactRound, LifeBuoy, MessagesSquare,
  PlugZap, Rocket, Settings2, ShieldCheck, Sparkles, type LucideIcon,
} from 'lucide-react';

const icons: Record<string, LucideIcon> = {
  BarChart3, BookOpen, CircleHelp, Code2, ContactRound, LifeBuoy, MessagesSquare,
  PlugZap, Rocket, Settings2, ShieldCheck, Sparkles,
};

export function HelpIcon({ name }: { name: string }) {
  const Icon = icons[name] ?? CircleHelp;
  return <Icon aria-hidden="true" />;
}

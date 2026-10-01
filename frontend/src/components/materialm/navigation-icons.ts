import {
  BarChart3, BookOpen, ClipboardList, Code2, ContactRound, FileSpreadsheet,
  GraduationCap, History, Inbox, LayoutDashboard, Layers, PlugZap, ShieldCheck, Sparkles, UsersRound,
} from 'lucide-react';
import type { NavigationItem } from '@/lib/materialm-navigation';
import type { LucideIcon } from 'lucide-react';

export const navigationIcons: Record<NavigationItem['icon'], LucideIcon> = {
  overview: LayoutDashboard, agents: Sparkles, inbox: Inbox, leads: ContactRound,
  integrations: PlugZap, education: GraduationCap, analytics: BarChart3, audit: ShieldCheck,
  deploy: Code2, students: UsersRound, courses: BookOpen, batches: Layers,
  enrollments: ClipboardList, imports: FileSpreadsheet, access: ShieldCheck, activity: History,
};

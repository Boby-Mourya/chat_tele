import type { HelpArticle, HelpArticleSummary, HelpCategory, HelpCategoryDetail, HelpHome, HelpSearchPage } from '@/lib/help-types';

const now = '2026-09-09T00:00:00.000Z';
const allRoles = ['owner', 'admin', 'member', 'analyst'] as const;
const adminRoles = ['owner', 'admin'] as const;

export const demoHelpCategories: HelpCategory[] = [
  { id: 'help-cat-start', slug: 'getting-started', title: 'Getting Started', description: 'Start with Northstar and reach your first successful setup.', icon: 'Rocket', articleCount: 3, sortOrder: 10 },
  { id: 'help-cat-agents', slug: 'agents', title: 'Agents', description: 'Create, configure, duplicate, and understand AI agents.', icon: 'Sparkles', articleCount: 4, sortOrder: 20 },
  { id: 'help-cat-knowledge', slug: 'knowledge', title: 'Knowledge', description: 'Add sources, understand processing, and improve grounded answers.', icon: 'BookOpen', articleCount: 4, sortOrder: 30 },
  { id: 'help-cat-conversations', slug: 'conversations', title: 'Conversations', description: 'Use the inbox, states, escalation, and human replies.', icon: 'MessagesSquare', articleCount: 3, sortOrder: 40 },
  { id: 'help-cat-deploy', slug: 'deploy', title: 'Deploy', description: 'Preview, install, and test agents across channels.', icon: 'Code2', articleCount: 3, sortOrder: 80 },
  { id: 'help-cat-trouble', slug: 'troubleshooting', title: 'Troubleshooting', description: 'Recover from common configuration and access issues.', icon: 'LifeBuoy', articleCount: 6, sortOrder: 110 },
];

const summaries: HelpArticleSummary[] = [
  { id: 'help-welcome', slug: 'welcome-to-northstar', categorySlug: 'getting-started', categoryTitle: 'Getting Started', title: 'Welcome to Northstar AI', summary: 'Learn how the authenticated Northstar workspace is organized.', keywords: ['overview', 'workspace'], readingMinutes: 2, updatedAt: now, featured: true, audienceRoles: [...allRoles] },
  { id: 'help-create-agent', slug: 'create-agent', categorySlug: 'agents', categoryTitle: 'Agents', title: 'Create an agent', summary: 'Create a Northstar AI agent with the existing guided flow.', keywords: ['agent', 'create', 'template', 'channel'], readingMinutes: 2, updatedAt: now, featured: true, audienceRoles: [...adminRoles] },
  { id: 'help-add-knowledge', slug: 'add-knowledge-source', categorySlug: 'knowledge', categoryTitle: 'Knowledge', title: 'Add a knowledge source', summary: 'Add a supported file, text, URL, or sitemap source to an agent.', keywords: ['knowledge', 'pdf', 'url', 'sitemap'], readingMinutes: 2, updatedAt: now, featured: true, audienceRoles: [...adminRoles] },
  { id: 'help-processing', slug: 'knowledge-statuses', categorySlug: 'knowledge', categoryTitle: 'Knowledge', title: 'Understand Processing, Ready, and Failed states', summary: 'Know what knowledge processing states mean.', keywords: ['processing', 'ready', 'failed'], readingMinutes: 2, updatedAt: now, featured: true, audienceRoles: [...allRoles] },
  { id: 'help-deploy', slug: 'deploy-website', categorySlug: 'deploy', categoryTitle: 'Deploy', title: 'Deploy an agent to a website', summary: 'Preview the widget and use the current installation information.', keywords: ['website', 'embed', 'widget'], readingMinutes: 2, updatedAt: now, featured: true, audienceRoles: [...adminRoles] },
  { id: 'help-permission', slug: 'permission-error', categorySlug: 'troubleshooting', categoryTitle: 'Troubleshooting', title: 'I received a permission error', summary: 'Understand why an action may be blocked for your role.', keywords: ['permission', 'role', '403'], readingMinutes: 2, updatedAt: now, featured: true, audienceRoles: [...allRoles] },
];

const bodies: Record<string, string> = {
  'welcome-to-northstar': '# Welcome to Northstar AI\n\nNorthstar brings your agents, knowledge, conversations, leads, analytics, integrations, deployment, workspace settings, and Help into one authenticated workspace.\n\n## Main navigation\n\n1. Open **Overview** for a summary.\n2. Open **Agents** for AI agents.\n3. Use **Conversations** and **Leads** for operational work.\n4. Use **Analytics** for performance.\n5. Use **Integrations** and **Deploy** for channels.\n6. Use **Workspace** for team and settings.\n7. Use **Help** for official guidance.',
  'create-agent': '# Create an agent\n\n## Before you start\n\nYou need an **Owner** or **Admin** role.\n\n1. Open **Agents**.\n2. Select **Create agent**.\n3. Complete the guided setup.\n4. Choose the deployment channel.\n5. Review the new agent before publishing.',
  'add-knowledge-source': '# Add a knowledge source\n\n1. Open an agent.\n2. Open **Knowledge**.\n3. Select **Add source**.\n4. Choose file, text, URL, or sitemap where offered.\n5. Submit and wait for processing.\n\nDo not upload credentials or secrets.',
  'knowledge-statuses': '# Understand knowledge processing states\n\n- **Processing** means ingestion is running.\n- **Ready** means the source can be retrieved.\n- **Failed** means ingestion could not finish.\n\nIf many sources are stuck, verify the background ingestion services.',
  'deploy-website': '# Deploy an agent to a website\n\n1. Open **Deploy**.\n2. Select the website agent.\n3. Review the preview.\n4. Copy the current embed snippet.\n5. Confirm **Allowed domains** contains the real hostname.\n6. Test on the deployed site.',
  'permission-error': '# I received a permission error\n\nNorthstar enforces workspace roles in the backend. Owner/Admin manage agents, knowledge, integrations, and workspace settings. Member supports permitted operations. Analyst is mainly read-oriented.\n\nIf an action should be available, sign in again and confirm your workspace role.',
};

export function demoHelpArticle(slug: string): HelpArticle | undefined {
  const summary = summaries.find((item) => item.slug === slug);
  if (!summary) return undefined;
  const inCategory = summaries.filter((item) => item.categorySlug === summary.categorySlug);
  const currentIndex = inCategory.findIndex((item) => item.slug === slug);
  return {
    ...summary,
    bodyMarkdown: bodies[slug] ?? `# ${summary.title}\n\n${summary.summary}`,
    related: summaries.filter((item) => item.slug !== slug && item.categorySlug === summary.categorySlug).slice(0, 3),
    previous: currentIndex > 0 ? inCategory[currentIndex - 1] ?? null : null,
    next: currentIndex >= 0 && currentIndex + 1 < inCategory.length ? inCategory[currentIndex + 1] ?? null : null,
  };
}

export function demoHelpHome(): HelpHome {
  return { categories: demoHelpCategories, popular: summaries.slice(0, 5), recommended: summaries.slice(0, 4), support: { email: 'support@northstar.ai', externalUrl: '' } };
}

export function demoHelpCategory(slug: string): HelpCategoryDetail | undefined {
  const category = demoHelpCategories.find((item) => item.slug === slug);
  if (!category) return undefined;
  return { category, articles: summaries.filter((item) => item.categorySlug === slug) };
}

export function demoHelpSearch(query: string): HelpSearchPage {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  const items = summaries.filter((item) => {
    const haystack = `${item.title} ${item.summary} ${item.keywords.join(' ')}`.toLowerCase();
    return terms.every((term) => haystack.includes(term));
  }).map((item, index) => ({ ...item, score: Math.max(.5, 1 - index * .08), snippet: item.summary }));
  return { items, total: items.length, page: 1, pageSize: 20, query, suggestedCategory: items[0]?.categorySlug ?? null };
}

export const demoHelpSummaries = summaries;

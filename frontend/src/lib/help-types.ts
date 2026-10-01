export type HelpAudienceRole = 'owner' | 'admin' | 'member' | 'analyst';
export type HelpFeedbackReason = 'incorrect' | 'outdated' | 'missing_steps' | 'hard_to_understand' | 'did_not_solve_problem' | 'other';
export type HelpSupportCategory = 'account' | 'agents' | 'knowledge' | 'conversations' | 'integrations' | 'deploy' | 'workspace' | 'billing' | 'security' | 'other';
export type HelpSupportStatus = 'submitted' | 'acknowledged' | 'closed';
export type HelpEventType = 'search_click' | 'ai_citation_click';

export interface HelpCategory { id: string; slug: string; title: string; description: string; icon: string; articleCount: number; sortOrder: number; }
export interface HelpArticleSummary { id: string; slug: string; categorySlug: string; categoryTitle: string; title: string; summary: string; keywords: string[]; readingMinutes: number; updatedAt: string; featured: boolean; audienceRoles: HelpAudienceRole[]; }
export interface HelpArticle extends HelpArticleSummary { bodyMarkdown: string; related: HelpArticleSummary[]; previous: HelpArticleSummary | null; next: HelpArticleSummary | null; }
export interface HelpSearchResult extends HelpArticleSummary { score: number; snippet: string; }
export interface HelpSearchPage { items: HelpSearchResult[]; total: number; page: number; pageSize: number; query: string; suggestedCategory?: string | null; }
export interface HelpSupportDestination { email: string; externalUrl: string; }
export interface HelpHome { categories: HelpCategory[]; popular: HelpArticleSummary[]; recommended: HelpArticleSummary[]; support: HelpSupportDestination; }
export interface HelpCategoryDetail { category: HelpCategory; articles: HelpArticleSummary[]; }
export interface HelpAiAnswer { answer: string; citations: HelpArticleSummary[]; suggestedArticles: HelpArticleSummary[]; available: boolean; }
export interface HelpSupportRequest { id: string; category: HelpSupportCategory; subject: string; message: string; status: HelpSupportStatus; contextPath?: string | null; requesterEmail: string; supportDestination: string; diagnostics: Record<string, unknown>; createdAt: string; updatedAt: string; }
export interface CreateHelpSupportRequestInput { category: HelpSupportCategory; subject: string; message: string; contextPath?: string; includeDiagnostics?: boolean; diagnostics?: Record<string, string>; }

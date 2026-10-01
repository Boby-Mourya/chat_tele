import { Clock3 } from 'lucide-react';
import { useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { HelpArticleFeedback } from '@/components/help/HelpArticleFeedback';
import { HelpArticleNavigation } from '@/components/help/HelpArticleNavigation';
import { HelpArticleToc, markdownHeadings } from '@/components/help/HelpArticleToc';
import { HelpBreadcrumbs } from '@/components/help/HelpBreadcrumbs';
import { HelpMarkdown } from '@/components/help/HelpMarkdown';
import { HelpRelatedArticles } from '@/components/help/HelpRelatedArticles';
import { HelpRoleBadge } from '@/components/help/HelpRoleBadge';
import { HelpSkeleton } from '@/components/help/HelpSkeleton';
import { HelpSupportCard } from '@/components/help/HelpSupportCard';
import { Card } from '@/components/ui';
import { helpApi } from '@/lib/help-api';
import { readStorage, writeStorage } from '@/lib/storage';
import { useApi } from '@/lib/use-api';

const RECENT_KEY = 'northstar.help.recent';

export function HelpArticlePage() {
  const { slug = '' } = useParams(); const result = useApi(() => helpApi.article(slug), [slug]); const home = useApi(() => helpApi.home(), []);
  useEffect(() => { if (!result.data) return; const current = readStorage<string[]>(RECENT_KEY, []); writeStorage(RECENT_KEY, [result.data.slug, ...current.filter((item) => item !== result.data!.slug)].slice(0, 8)); }, [result.data]);
  if (result.loading) return <HelpSkeleton />;
  if (!result.data) return <div className="page help-page"><Card className="help-error"><h2>{result.error?.includes('role') ? 'Guide not available for your role' : 'Help article not found'}</h2><p>{result.error ?? 'This guide may have moved or is no longer published.'}</p></Card></div>;
  const article = result.data; const toc = markdownHeadings(article.bodyMarkdown);
  return <div className="page help-page help-article-page"><HelpBreadcrumbs items={[{ label: 'Help', to: '/help' }, { label: article.categoryTitle, to: `/help/categories/${article.categorySlug}` }, { label: article.title }]} /><header className="help-article__header"><span className="page-kicker">{article.categoryTitle}</span><h2>{article.title}</h2><p>{article.summary}</p><div className="help-article__meta"><span><Clock3 /> {article.readingMinutes} min read</span><span>Updated {new Date(article.updatedAt).toLocaleDateString()}</span><HelpRoleBadge roles={article.audienceRoles} /></div></header><div className="help-article__layout"><article><HelpMarkdown markdown={article.bodyMarkdown} /><HelpArticleFeedback articleId={article.id} /></article><HelpArticleToc items={toc} /></div><HelpArticleNavigation previous={article.previous} next={article.next} /><HelpRelatedArticles articles={article.related} />{home.data ? <HelpSupportCard support={home.data.support} /> : null}</div>;
}

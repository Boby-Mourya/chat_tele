import { ArrowRight, Clock3 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { helpApi } from '@/lib/help-api';
import type { HelpArticleSummary, HelpSearchResult } from '@/lib/help-types';

export function HelpArticleCard({ article, compact = false, searchQuery }: { article: HelpArticleSummary | HelpSearchResult; compact?: boolean; searchQuery?: string }) {
  const snippet = 'snippet' in article ? article.snippet : article.summary;
  return <Link
    to={`/help/articles/${article.slug}`}
    className={`help-article-card ${compact ? 'help-article-card--compact' : ''}`}
    onClick={() => { if (searchQuery) void helpApi.event('search_click', article.id, searchQuery); }}
  >
    <span className="help-article-card__category">{article.categoryTitle}</span>
    <strong>{article.title}</strong>
    {!compact ? <p>{snippet || article.summary}</p> : null}
    <span className="help-article-card__meta"><Clock3 /> {article.readingMinutes} min read <ArrowRight /></span>
  </Link>;
}

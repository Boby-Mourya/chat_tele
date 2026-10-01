import { ArrowLeft, ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { HelpArticleSummary } from '@/lib/help-types';

export function HelpArticleNavigation({ previous, next }: { previous: HelpArticleSummary | null; next: HelpArticleSummary | null }) {
  if (!previous && !next) return null;
  return <nav className="help-article-nav" aria-label="Article navigation">
    {previous ? <Link className="help-article-nav__item" to={`/help/articles/${previous.slug}`}><ArrowLeft /><span><small>Previous</small><strong>{previous.title}</strong></span></Link> : <span />}
    {next ? <Link className="help-article-nav__item help-article-nav__item--next" to={`/help/articles/${next.slug}`}><span><small>Next</small><strong>{next.title}</strong></span><ArrowRight /></Link> : <span />}
  </nav>;
}

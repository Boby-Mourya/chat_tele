import type { HelpArticleSummary } from '@/lib/help-types';
import { HelpArticleCard } from '@/components/help/HelpArticleCard';

export function HelpRelatedArticles({ articles }: { articles: HelpArticleSummary[] }) {
  if (!articles.length) return null;
  return <section className="help-related"><div className="help-section-heading"><h2>Related guides</h2><p>Continue with official guidance on the same task.</p></div><div className="help-related__grid">{articles.map((article) => <HelpArticleCard key={article.id} article={article} compact />)}</div></section>;
}

import { Clock3, Sparkles } from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import { HelpArticleCard } from '@/components/help/HelpArticleCard';
import { HelpCategoryCard } from '@/components/help/HelpCategoryCard';
import { HelpSearchBox } from '@/components/help/HelpSearchBox';
import { HelpSkeleton } from '@/components/help/HelpSkeleton';
import { HelpSupportCard } from '@/components/help/HelpSupportCard';
import { Button, Card } from '@/components/ui';
import { helpApi } from '@/lib/help-api';
import { readStorage, writeStorage } from '@/lib/storage';
import { useApi } from '@/lib/use-api';
import type { HelpArticleSummary } from '@/lib/help-types';

const RECENT_KEY = 'northstar.help.recent';

export function HelpCenterPage() {
  const [params] = useSearchParams(); const context = params.get('from') ?? undefined;
  const result = useApi(() => helpApi.home(context), [context]);
  const recentSlugs = readStorage<string[]>(RECENT_KEY, []);
  const recentResult = useApi(async () => {
    const items: HelpArticleSummary[] = [];
    for (const slug of recentSlugs.slice(0, 6)) {
      try { const article = await helpApi.article(slug); items.push(article); } catch { /* remove inaccessible entries below */ }
    }
    if (items.length !== recentSlugs.slice(0, 6).length) writeStorage(RECENT_KEY, items.map((item) => item.slug));
    return items;
  }, [recentSlugs.join('|')]);

  if (result.loading) return <HelpSkeleton />;
  if (result.error || !result.data) return <div className="page help-page"><Card className="help-error"><h2>Help Center is unavailable</h2><p>{result.error ?? 'Help content could not be loaded.'}</p><Button onClick={result.reload}>Try again</Button></Card></div>;

  const home = result.data;
  return <div className="page help-page">
    <section className="help-hero"><span className="page-kicker">Northstar support</span><h2>How can we help?</h2><p>Search official setup guides, product instructions, and troubleshooting for your workspace role.</p><HelpSearchBox /></section>

    {home.recommended.length ? <section className="help-section"><div className="help-section-heading"><div><h2>Popular for you</h2><p>Useful guides based on your role{context ? ' and current area' : ''}.</p></div><Link className="button button--secondary button--md" to="/help/ask"><Sparkles /> Ask Help AI</Link></div><div className="help-popular">{home.recommended.slice(0, 4).map((article) => <HelpArticleCard key={article.id} article={article} />)}</div></section> : null}

    <section className="help-section"><div className="help-section-heading"><div><h2>Browse by category</h2><p>Help follows the same structure as the product you already use.</p></div></div><div className="help-category-grid">{home.categories.map((category) => <HelpCategoryCard key={category.id} category={category} />)}</div></section>

    {recentResult.data?.length ? <section className="help-section"><div className="help-section-heading"><div><h2>Recently viewed</h2><p>Continue where you left off.</p></div><span className="help-section-heading__meta"><Clock3 /> Stored only in this browser</span></div><div className="help-recent">{recentResult.data.map((article) => <HelpArticleCard key={article.id} article={article} compact />)}</div></section> : null}

    <HelpSupportCard support={home.support} />
  </div>;
}

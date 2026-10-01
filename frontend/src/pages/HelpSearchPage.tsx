import { Link, useSearchParams } from 'react-router-dom';
import { HelpArticleCard } from '@/components/help/HelpArticleCard';
import { HelpBreadcrumbs } from '@/components/help/HelpBreadcrumbs';
import { HelpEmptyState } from '@/components/help/HelpEmptyState';
import { HelpSearchBox } from '@/components/help/HelpSearchBox';
import { HelpSkeleton } from '@/components/help/HelpSkeleton';
import { Button, Card } from '@/components/ui';
import { helpApi } from '@/lib/help-api';
import { useApi } from '@/lib/use-api';

export function HelpSearchPage() {
  const [params, setParams] = useSearchParams(); const query = params.get('q')?.trim() ?? ''; const category = params.get('category') ?? undefined; const page = Math.max(1, Number(params.get('page') ?? 1) || 1);
  const result = useApi(() => query.length >= 2 ? helpApi.search(query, category, page, 20) : Promise.resolve({ items: [], total: 0, page: 1, pageSize: 20, query, suggestedCategory: null }), [query, category, page]);
  return <div className="page help-page"><HelpBreadcrumbs items={[{ label: 'Help', to: '/help' }, { label: 'Search' }]} /><section className="help-search-page__hero"><h2>Search Help</h2><HelpSearchBox initialQuery={query} autoFocus={!query} /></section>{result.loading ? <HelpSkeleton /> : result.error ? <Card className="help-error"><h2>Search is temporarily unavailable</h2><p>{result.error}</p><Button onClick={result.reload}>Try again</Button></Card> : result.data ? <section className="help-search-results"><div className="help-section-heading"><div><h2>{query ? `Results for “${query}”` : 'Search official Help'}</h2><p>{result.data.total} {result.data.total === 1 ? 'guide' : 'guides'} found</p></div>{result.data.suggestedCategory && !category ? <Link to={`/help/categories/${result.data.suggestedCategory}`}>Browse suggested category</Link> : null}</div>{result.data.items.length ? <div className="help-article-list">{result.data.items.map((item) => <HelpArticleCard key={item.id} article={item} searchQuery={query} />)}</div> : <HelpEmptyState query={query} />}{result.data.total > result.data.pageSize ? <div className="help-pagination"><Button variant="secondary" disabled={page <= 1} onClick={() => setParams({ q: query, ...(category ? { category } : {}), page: String(page - 1) })}>Previous</Button><span>Page {page}</span><Button variant="secondary" disabled={page * result.data.pageSize >= result.data.total} onClick={() => setParams({ q: query, ...(category ? { category } : {}), page: String(page + 1) })}>Next</Button></div> : null}</section> : null}</div>;
}

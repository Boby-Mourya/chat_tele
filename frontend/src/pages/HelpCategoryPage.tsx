import { useParams } from 'react-router-dom';
import { HelpArticleCard } from '@/components/help/HelpArticleCard';
import { HelpBreadcrumbs } from '@/components/help/HelpBreadcrumbs';
import { HelpEmptyState } from '@/components/help/HelpEmptyState';
import { HelpIcon } from '@/components/help/HelpIcon';
import { HelpSkeleton } from '@/components/help/HelpSkeleton';
import { Button, Card } from '@/components/ui';
import { helpApi } from '@/lib/help-api';
import { useApi } from '@/lib/use-api';

export function HelpCategoryPage() {
  const { slug = '' } = useParams(); const result = useApi(() => helpApi.category(slug), [slug]);
  if (result.loading) return <HelpSkeleton />;
  if (!result.data) return <div className="page help-page"><HelpBreadcrumbs items={[{ label: 'Help', to: '/help' }, { label: 'Category' }]} />{result.error ? <Card className="help-error"><h2>Help category is unavailable</h2><p>{result.error}</p><Button onClick={result.reload}>Try again</Button></Card> : <HelpEmptyState />}</div>;
  return <div className="page help-page"><HelpBreadcrumbs items={[{ label: 'Help', to: '/help' }, { label: result.data.category.title }]} /><section className="help-category-header"><span><HelpIcon name={result.data.category.icon} /></span><div><h2>{result.data.category.title}</h2><p>{result.data.category.description}</p></div></section><div className="help-article-list">{result.data.articles.map((article) => <HelpArticleCard key={article.id} article={article} />)}</div></div>;
}

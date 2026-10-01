import { ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { HelpIcon } from '@/components/help/HelpIcon';
import type { HelpCategory } from '@/lib/help-types';

export function HelpCategoryCard({ category }: { category: HelpCategory }) {
  return <Link className="help-category-card" to={`/help/categories/${category.slug}`}>
    <span className="help-category-card__icon"><HelpIcon name={category.icon} /></span>
    <span className="help-category-card__copy"><strong>{category.title}</strong><p>{category.description}</p><small>{category.articleCount} {category.articleCount === 1 ? 'guide' : 'guides'}</small></span>
    <ArrowRight aria-hidden="true" />
  </Link>;
}

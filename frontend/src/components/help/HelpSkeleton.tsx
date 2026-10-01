import { Card, Skeleton } from '@/components/ui';

export function HelpSkeleton() {
  return <div className="help-skeleton" role="status" aria-label="Loading Help Center"><Card><Skeleton height={26} width="42%" /><Skeleton height={14} width="80%" /><Skeleton height={14} width="66%" /></Card><div className="help-category-grid">{Array.from({ length: 6 }, (_, index) => <Card key={index}><Skeleton height={42} width="42px" /><Skeleton height={18} width="55%" /><Skeleton height={12} width="90%" /></Card>)}</div></div>;
}

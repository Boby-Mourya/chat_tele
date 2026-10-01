import type { CSSProperties } from 'react';
import { formatCompact } from '@/lib/format';

interface ChannelBreakdownProps {
  channels: Array<{ channel: string; value: number }>;
  total: number;
}

export function ChannelBreakdown({ channels, total }: ChannelBreakdownProps) {
  const values = channels.filter((item) => Number.isFinite(item.value) && item.value > 0);
  const sum = values.reduce((value, item) => value + item.value, 0);
  if (!sum) return <p className="analytics-empty">No channel activity in this period.</p>;

  const segments = values.map((item, index) => {
    const start = values.slice(0, index).reduce((value, entry) => value + entry.value, 0) / sum * 100;
    const end = index === values.length - 1 ? 100 : start + item.value / sum * 100;
    const color = `var(--chart-${index % 6 + 1})`;
    return { ...item, color, stop: `${color} ${start}% ${end}%` };
  });
  const style = { '--channel-gradient': `conic-gradient(${segments.map((item) => item.stop).join(', ')})` } as CSSProperties;

  return <div className="donut-wrap">
    <div className="donut" style={style} role="img" aria-label={`Channel distribution: ${values.map((item) => `${item.channel} ${item.value}%`).join(', ')}`}>
      <span aria-hidden="true"><strong>{formatCompact(total)}</strong><small>Total</small></span>
    </div>
    <div className="channel-legend">{segments.map((item) => <span key={item.channel}>
      <i className="channel-color" style={{ '--channel-color': item.color } as CSSProperties} aria-hidden="true" />
      <strong>{item.channel}</strong><em>{item.value}%</em>
    </span>)}</div>
  </div>;
}

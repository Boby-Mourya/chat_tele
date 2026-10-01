import { Link } from 'react-router-dom';
import type { ReactNode } from 'react';
import { WelcomeCharacter } from './welcome-character';

export function DashboardWelcome({ name, children }: { name: string; children: ReactNode }) {
  return <section className="academy-welcome">
    <div><h2>Hello {name}!</h2><p>{children}</p></div>
    <WelcomeCharacter />
  </section>;
}

export function LearningTip({ title = 'Learn even more!', description, to, action }: { title?: string; description: string; to: string; action: string }) {
  return <aside className="academy-tip">
    <div><h3>{title}</h3><p>{description}</p><Link className="button button--primary" to={to}>{action}</Link></div>
    <img src="/design/online-courses/learning-illustration.png" width="137" height="131" alt="" />
  </aside>;
}

/** Real observations only; gaps are not interpolated into invented activity. */
export function DashboardTrend({ data, label }: { data: Array<{ label: string; value: number }>; label: string }) {
  const max = Math.max(1, Math.ceil(Math.max(0, ...data.map((item) => item.value)) / 4)) * 4;
  const width = 440, height = 245, left = 32, right = 16, top = 32, bottom = 28;
  const points = data.map((item, index) => ({
    ...item,
    x: left + index * (width - left - right) / Math.max(data.length - 1, 1),
    y: height - bottom - item.value / max * (height - top - bottom),
  }));
  return <div className="academy-trend">
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
      {[0, 1, 2, 3, 4].map((step) => {
        const y = height - bottom - step / 4 * (height - top - bottom);
        return <g key={step}><line x1={left} x2={width - right} y1={y} y2={y} className="academy-trend__grid" /><text x="0" y={y + 4} className="academy-trend__axis">{Number((max * step / 4).toFixed(1))}</text></g>;
      })}
      <polyline points={points.map((point) => `${point.x},${point.y}`).join(' ')} fill="none" className="academy-trend__line" strokeWidth="2" strokeLinejoin="round" />
      {points.map((point, index) => <g key={index}>
        <circle cx={point.x} cy={point.y} r="4" className="academy-trend__point"><title>{point.label}: {point.value}</title></circle>
        {(points.length <= 8 || index % Math.ceil(points.length / 7) === 0 || index === points.length - 1) && <>
          <rect x={point.x - 15} y={point.y - 29} width="30" height="20" rx="4" className="academy-trend__tooltip" />
          <text x={point.x} y={point.y - 15} textAnchor="middle" className="academy-trend__value">{point.value}</text>
          <text x={point.x} y={height - 3} textAnchor="middle" className="academy-trend__axis">{point.label}</text>
        </>}
      </g>)}
    </svg>
    <details className="academy-chart-data"><summary>View chart data</summary><table><caption>{label}</caption><thead><tr><th>Period</th><th>Count</th></tr></thead><tbody>{data.map((item, index) => <tr key={index}><td>{item.label}</td><td>{item.value}</td></tr>)}</tbody></table></details>
  </div>;
}

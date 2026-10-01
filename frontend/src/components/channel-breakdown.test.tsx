import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { ChannelBreakdown } from './channel-breakdown';

afterEach(cleanup);

describe('channel breakdown', () => {
  it('draws the supplied proportions with the same colors as the legend', () => {
    render(<ChannelBreakdown total={100} channels={[{ channel: 'Widget', value: 70 }, { channel: 'WhatsApp', value: 30 }]} />);
    const chart = screen.getByRole('img', { name: 'Channel distribution: Widget 70%, WhatsApp 30%' });
    expect(chart.style.getPropertyValue('--channel-gradient')).toBe('conic-gradient(var(--chart-1) 0% 70%, var(--chart-2) 70% 100%)');
    expect(screen.getByText('WhatsApp').previousElementSibling).toHaveStyle('--channel-color: var(--chart-2)');
  });

  it('does not invent a chart when no usable activity is available', () => {
    render(<ChannelBreakdown total={0} channels={[{ channel: 'Widget', value: 0 }, { channel: 'Unknown', value: NaN }, { channel: 'Invalid', value: -2 }]} />);
    expect(screen.getByText('No channel activity in this period.')).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });

  it('fills the circle when percentages have been rounded by the API', () => {
    render(<ChannelBreakdown total={3} channels={[{ channel: 'A', value: 33 }, { channel: 'B', value: 33 }, { channel: 'C', value: 33 }]} />);
    expect(screen.getByRole('img').style.getPropertyValue('--channel-gradient')).toContain('100%');
  });
});

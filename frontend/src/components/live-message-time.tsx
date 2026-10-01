import { useEffect, useState } from 'react';
import { relativeTime } from '@/lib/format';

/** Keep elapsed time current even when the API is temporarily unavailable. */
export function LiveMessageTime({ value }: { value: string }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return <span>Not available</span>;
  const seconds = Math.max(0, Math.floor((now - date.getTime()) / 1000));
  return <time dateTime={value} title={date.toLocaleString()}>
    {seconds < 60 ? (seconds === 0 ? 'just now' : `${seconds}s ago`) : relativeTime(value)}
  </time>;
}

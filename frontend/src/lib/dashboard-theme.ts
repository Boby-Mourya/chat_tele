import type { CSSProperties } from 'react';

/** Match the dashboard to an explicitly enabled workspace brand while keeping
 * primary button labels readable, including for white and yellow brands. */
export function dashboardTheme(primary: string | undefined): CSSProperties | undefined {
  if (!primary || !/^#[0-9a-f]{6}$/i.test(primary)) return undefined;
  const rgb = [1, 3, 5].map((offset) => parseInt(primary.slice(offset, offset + 2), 16) / 255);
  const linear = rgb.map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  const luminance = linear[0]! * 0.2126 + linear[1]! * 0.7152 + linear[2]! * 0.0722;
  const foreground = luminance > 0.179 ? '#000000' : '#ffffff';
  return {
    '--mm-accent': primary,
    '--blue': primary,
    '--blue-hover': `color-mix(in srgb, ${primary} 90%, ${foreground === '#000000' ? 'white' : 'black'})`,
    '--blue-soft': `color-mix(in srgb, ${primary} 8%, white)`,
    '--on-primary': foreground,
  } as CSSProperties;
}

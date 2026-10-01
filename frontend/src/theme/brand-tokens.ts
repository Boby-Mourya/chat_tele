export const BRAND_VARIABLES = [
  '--brand-primary', '--brand-primary-hover', '--brand-secondary', '--brand-accent',
  '--brand-background', '--brand-surface', '--brand-border', '--brand-text', '--brand-muted',
  '--brand-sidebar', '--brand-sidebar-text', '--brand-header', '--brand-success', '--brand-warning',
  '--brand-error', '--brand-link', '--brand-radius', '--brand-font', '--brand-heading-font', '--brand-font-size',
] as const;

export type BrandTokenSource = {
  primaryColor: string;
  secondaryColor: string;
  colors?: Record<string, string>;
  typography?: Record<string, string | number>;
  borderRadius?: number;
};

export function resolveBrandTokens(source: BrandTokenSource): Record<(typeof BRAND_VARIABLES)[number], string> {
  const colors = source.colors ?? {};
  const typography = source.typography ?? {};
  return {
    '--brand-primary': source.primaryColor || '#0c0b0b',
    '--brand-primary-hover': colors.primaryHover ?? source.primaryColor ?? '#27272a',
    '--brand-secondary': source.secondaryColor || '#6b6b70',
    '--brand-accent': colors.accent ?? source.primaryColor ?? '#2563eb',
    '--brand-background': colors.background ?? '#ffffff',
    '--brand-surface': colors.surface ?? '#ffffff',
    '--brand-border': colors.border ?? '#e5e7eb',
    '--brand-text': colors.textPrimary ?? '#111827',
    '--brand-muted': colors.textSecondary ?? '#6b7280',
    '--brand-sidebar': colors.sidebarBackground ?? '#0c0b0b',
    '--brand-sidebar-text': colors.sidebarText ?? '#ffffff',
    '--brand-header': colors.header ?? '#ffffff',
    '--brand-success': colors.success ?? '#16a34a',
    '--brand-warning': colors.warning ?? '#d97706',
    '--brand-error': colors.error ?? '#dc2626',
    '--brand-link': colors.link ?? source.primaryColor ?? '#2563eb',
    '--brand-radius': `${source.borderRadius ?? 12}px`,
    '--brand-font': String(typography.bodyFont ?? 'Inter'),
    '--brand-heading-font': String(typography.headingFont ?? typography.bodyFont ?? 'Inter'),
    '--brand-font-size': `${Number(typography.baseFontSize ?? 16)}px`,
  };
}

export function applyBrandTokens(source: BrandTokenSource, root: HTMLElement = document.documentElement): () => void {
  const tokens = resolveBrandTokens(source);
  const previous = new Map<string, string>();
  for (const [name, value] of Object.entries(tokens)) {
    previous.set(name, root.style.getPropertyValue(name));
    root.style.setProperty(name, value);
  }
  return () => {
    for (const name of BRAND_VARIABLES) {
      const oldValue = previous.get(name) ?? '';
      if (oldValue) root.style.setProperty(name, oldValue);
      else root.style.removeProperty(name);
    }
  };
}

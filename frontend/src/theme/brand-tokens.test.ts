import { describe, expect, it } from 'vitest';
import { applyBrandTokens, resolveBrandTokens } from './brand-tokens';

describe('brand token resolver', () => {
  it('maps published design tokens onto the shared CSS variable contract', () => {
    const tokens = resolveBrandTokens({
      primaryColor: '#123456',
      secondaryColor: '#abcdef',
      colors: {
        primaryHover: '#112233',
        accent: '#ff00ff',
        background: '#fefefe',
        surface: '#ffffff',
        border: '#dddddd',
        textPrimary: '#111111',
        textSecondary: '#666666',
        sidebarBackground: '#000000',
        sidebarText: '#ffffff',
      },
      typography: { bodyFont: 'Inter', headingFont: 'Manrope', baseFontSize: 15 },
      borderRadius: 18,
    });

    expect(tokens['--brand-primary']).toBe('#123456');
    expect(tokens['--brand-secondary']).toBe('#abcdef');
    expect(tokens['--brand-primary-hover']).toBe('#112233');
    expect(tokens['--brand-sidebar']).toBe('#000000');
    expect(tokens['--brand-heading-font']).toBe('Manrope');
    expect(tokens['--brand-font-size']).toBe('15px');
    expect(tokens['--brand-radius']).toBe('18px');
  });

  it('restores the previous token layer when a more specific brand is removed', () => {
    const root = document.createElement('div');
    root.style.setProperty('--brand-primary', '#platform');

    const cleanup = applyBrandTokens(
      { primaryColor: '#workspace', secondaryColor: '#secondary' },
      root,
    );

    expect(root.style.getPropertyValue('--brand-primary')).toBe('#workspace');
    cleanup();
    expect(root.style.getPropertyValue('--brand-primary')).toBe('#platform');
    expect(root.style.getPropertyValue('--brand-secondary')).toBe('');
  });
});

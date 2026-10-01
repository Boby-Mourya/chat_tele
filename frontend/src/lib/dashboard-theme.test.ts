import { describe, expect, it } from 'vitest';
import { dashboardTheme } from './dashboard-theme';

describe('workspace dashboard contrast', () => {
  it.each(['#ffffff', '#ffff00', '#aaffcc'])('uses dark text for a light brand: %s', (color) => {
    expect(dashboardTheme(color)).toHaveProperty('--on-primary', '#000000');
  });
  it.each(['#000000', '#0c0b0b', '#143080'])('uses white text for a dark brand: %s', (color) => {
    expect(dashboardTheme(color)).toHaveProperty('--on-primary', '#ffffff');
  });
  it.each([undefined, '', 'red', '#fff', 'url(https://example.com)'])('ignores unsupported brand values: %s', (color) => {
    expect(dashboardTheme(color)).toBeUndefined();
  });
});

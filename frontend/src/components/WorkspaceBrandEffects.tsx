import { useEffect } from 'react';
import { useWorkspace } from '@/components/providers';

/** One mounted instance owns document-level branding; individual logo instances have no side effects. */
export function WorkspaceBrandEffects() {
  const { activeWorkspace } = useWorkspace();
  const brand = activeWorkspace?.brandingPublished && activeWorkspace.whiteLabel.brandedDashboard ? activeWorkspace.whiteLabel : null;
  useEffect(() => {
    if (!brand) return;
    const originalTitle = document.title;
    const root = document.documentElement;
    const originalState = root.getAttribute('data-workspace-brand');
    const originalSecondary = root.style.getPropertyValue('--workspace-secondary');
    const originalOnSecondary = root.style.getPropertyValue('--workspace-on-secondary');
    const oldIcon = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    const originalIcon = oldIcon?.getAttribute('href');
    let icon = oldIcon;
    document.title = brand.browserTitle;
    root.setAttribute('data-workspace-brand', 'enabled');
    const rgb = [1, 3, 5].map((offset) => parseInt(brand.secondaryColor.slice(offset, offset + 2), 16) / 255);
    const linear = rgb.map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
    const luminance = linear[0]! * 0.2126 + linear[1]! * 0.7152 + linear[2]! * 0.0722;
    root.style.setProperty('--workspace-secondary', brand.secondaryColor);
    root.style.setProperty('--workspace-on-secondary', luminance > 0.179 ? '#000000' : '#ffffff');
    if (brand.faviconDataUrl) {
      if (!icon) { icon = document.createElement('link'); icon.rel = 'icon'; document.head.appendChild(icon); }
      icon.setAttribute('href', brand.faviconDataUrl);
    }
    return () => {
      document.title = originalTitle;
      if (originalState === null) root.removeAttribute('data-workspace-brand'); else root.setAttribute('data-workspace-brand', originalState);
      if (originalSecondary) root.style.setProperty('--workspace-secondary', originalSecondary); else root.style.removeProperty('--workspace-secondary');
      if (originalOnSecondary) root.style.setProperty('--workspace-on-secondary', originalOnSecondary); else root.style.removeProperty('--workspace-on-secondary');
      if (!oldIcon) icon?.remove(); else if (originalIcon !== null && originalIcon !== undefined) oldIcon.setAttribute('href', originalIcon); else oldIcon.removeAttribute('href');
    };
  }, [brand]);
  return null;
}

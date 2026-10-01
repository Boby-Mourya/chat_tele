import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { applyBrandTokens } from '@/theme/brand-tokens';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';

export type PublicBranding = {
  workspaceId: string;
  companyName: string;
  browserTitle: string;
  logoDataUrl: string;
  faviconDataUrl: string;
  primaryColor: string;
  secondaryColor: string;
  colors: Record<string, string>;
  typography: Record<string, string | number>;
  authentication: {
    loginLogo?: string;
    loginBackground?: string;
    loginTitle?: string;
    loginDescription?: string;
    signupTitle?: string;
    forgotPasswordTitle?: string;
    resetPasswordTitle?: string;
    mfaTitle?: string;
    invitationTitle?: string;
    termsUrl?: string;
    privacyUrl?: string;
    supportUrl?: string;
    footer?: string;
  };
  supportUrl: string;
};

const PublicBrandingContext = createContext<PublicBranding | null>(null);

function setFavicon(dataUrl: string) {
  if (!dataUrl) return;
  let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (!link) {
    link = document.createElement('link');
    link.rel = 'icon';
    document.head.appendChild(link);
  }
  link.href = dataUrl;
}

export function PublicBrandingProvider({ children }: { children: ReactNode }) {
  const [brand, setBrand] = useState<PublicBranding | null>(null);
  const hostname = useMemo(() => window.location.hostname.toLowerCase(), []);

  useEffect(() => {
    let current = true;
    let cleanupTokens: (() => void) | undefined;
    const controller = new AbortController();
    fetch(`${API_URL}/branding/public?hostname=${encodeURIComponent(hostname)}`, {
      headers: { Accept: 'application/json' },
      credentials: 'omit',
      cache: 'no-store',
      signal: controller.signal,
    })
      .then(async (response) => response.ok ? await response.json() as PublicBranding : null)
      .then((value) => {
        if (!current || !value) return;
        setBrand(value);
        if (value.browserTitle) document.title = value.browserTitle;
        setFavicon(value.faviconDataUrl);
        cleanupTokens = applyBrandTokens({
          primaryColor: value.primaryColor,
          secondaryColor: value.secondaryColor,
          colors: value.colors,
          typography: value.typography,
        });
      })
      .catch(() => undefined);
    return () => {
      current = false;
      controller.abort();
      cleanupTokens?.();
    };
  }, [hostname]);

  return <PublicBrandingContext.Provider value={brand}>{children}</PublicBrandingContext.Provider>;
}

export function usePublicBranding() {
  return useContext(PublicBrandingContext);
}

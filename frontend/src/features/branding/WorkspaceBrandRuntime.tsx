import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useWorkspace } from '@/components/providers';
import { workspaceSettingsApi, type ExtendedBranding } from '@/features/workspace/settings/workspaceSettings.api';
import { applyBrandTokens } from '@/theme/brand-tokens';

const RuntimeBrandContext = createContext<ExtendedBranding | null>(null);

type WorkspaceBrandSnapshot = {
  workspaceId: string;
  branding: ExtendedBranding | null;
};

export function WorkspaceBrandRuntime({ children }: { children: ReactNode }) {
  const { activeWorkspace } = useWorkspace();
  const [brandSnapshot, setBrandSnapshot] = useState<WorkspaceBrandSnapshot | null>(null);
  // A previous workspace's published brand must not remain visible while the
  // next workspace's asynchronous branding request is still in flight.
  const branding = (() => {
    if (!brandSnapshot || brandSnapshot.workspaceId !== activeWorkspace?.id) return null;
    return brandSnapshot.branding;
  })();

  useEffect(() => {
    let current = true;
    if (!activeWorkspace) {
      return () => { current = false; };
    }
    const workspaceId = activeWorkspace.id;
    workspaceSettingsApi.runtimeBranding().then((value) => {
      if (current) setBrandSnapshot({ workspaceId, branding: value });
    }).catch(() => {
      if (current) setBrandSnapshot({ workspaceId, branding: null });
    });
    return () => { current = false; };
  }, [activeWorkspace]);

  useEffect(() => {
    const activeBranding = branding;
    if (!activeBranding?.identity.brandedDashboard) return;
    const previousTitle = document.title;
    const cleanupTokens = applyBrandTokens({
      primaryColor: activeBranding.identity.primaryColor,
      secondaryColor: activeBranding.identity.secondaryColor,
      colors: activeBranding.colors,
      typography: activeBranding.typography,
      borderRadius: activeBranding.appearance.borderRadius,
    });
    if (activeBranding.identity.browserTitle) document.title = activeBranding.identity.browserTitle;
    return () => {
      cleanupTokens();
      if (activeBranding.identity.browserTitle && document.title === activeBranding.identity.browserTitle) document.title = previousTitle;
    };
  }, [branding]);

  const value = useMemo(() => branding, [branding]);
  return <RuntimeBrandContext.Provider value={value}>{children}</RuntimeBrandContext.Provider>;
}

export function useWorkspaceBrandRuntime(): ExtendedBranding | null {
  return useContext(RuntimeBrandContext);
}

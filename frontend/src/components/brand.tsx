import { useOptionalWorkspace } from '@/components/providers';
import { usePublicBranding } from '@/components/public-branding';

export function BrandMark({ size = 38 }: { size?: number }) {
  return <span className="brand-mark" style={{ width: size, height: size }} aria-hidden="true"><svg viewBox="0 0 64 64"><path d="M32 6.5l5.6 19.9L57.5 32l-19.9 5.6L32 57.5l-5.6-19.9L6.5 32l19.9-5.6L32 6.5z" /><circle cx="32" cy="32" r="4.6" /></svg></span>;
}
export function Brand({ compact = false, light = false }: { compact?: boolean; light?: boolean }) {
  const publicBrand = usePublicBranding();
  const workspace = useOptionalWorkspace()?.activeWorkspace;
  const workspaceBrand = workspace?.brandingPublished && workspace.whiteLabel.brandedDashboard ? workspace.whiteLabel : null;
  const brand = workspaceBrand ?? (publicBrand ? { companyName: publicBrand.companyName, logoDataUrl: publicBrand.logoDataUrl } : null);
  if (!brand) return <div className={`brand ${light ? 'brand--light' : ''}`}><BrandMark />{compact ? null : <span>northstar<span>ai</span></span>}</div>;
  return <div className={`brand ${light ? 'brand--light' : ''}`}>
    {brand.logoDataUrl ? <img src={brand.logoDataUrl} alt="" style={{ maxWidth: compact ? 38 : 80, height: 38, objectFit: 'contain' }} /> : <BrandMark />}
    {compact ? <span className="sr-only">{brand.companyName}</span> : <span>{brand.companyName}</span>}
  </div>;
}

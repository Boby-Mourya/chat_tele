import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App } from '@/App';
import { AuthProvider, ToastProvider, WorkspaceProvider } from '@/components/providers';
import { PublicBrandingProvider } from '@/components/public-branding';
import { WorkspaceBrandRuntime } from '@/features/branding/WorkspaceBrandRuntime';
import '@/theme/tokens.css';
import '@/theme/typography.css';
import '@/styles.css';
import '@/help.css';
import '@/help-detail.css';
import '@/theme/materialm.tokens.css';
import '@/theme/materialm.css';
import '@/theme/materialm.components.css';
import '@/theme/academy.tokens.css';
import '@/theme/academy.css';
import '@/theme/academy.components.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <PublicBrandingProvider>
        <ToastProvider>
          <AuthProvider>
            <WorkspaceProvider>
              <WorkspaceBrandRuntime><App /></WorkspaceBrandRuntime>
            </WorkspaceProvider>
          </AuthProvider>
        </ToastProvider>
      </PublicBrandingProvider>
    </BrowserRouter>
  </React.StrictMode>,
);

import { Component, type ReactNode } from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui';

/** Remount with the route/workspace key to allow navigation after a page fails. */
export class PageErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return <section className="route-error" role="alert" aria-labelledby="route-error-title">
      <AlertCircle aria-hidden="true" />
      <h2 id="route-error-title">This page couldn’t load</h2>
      <p>Refresh the page to try again. If the problem continues, return to your workspace and open another page.</p>
      <div className="route-error__actions">
        <Button icon={RefreshCw} onClick={() => window.location.reload()}>Refresh page</Button>
        <a className="button button--secondary" href="/">Back to workspace</a>
      </div>
    </section>;
  }
}

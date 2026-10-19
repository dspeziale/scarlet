import { Component, type ErrorInfo, type ReactNode } from 'react';
import { ErrorPanel } from './ErrorPanel';

/** Keeps a rendering error confined to the page instead of blanking the whole console. */
export class RouteErrorBoundary extends Component<{ children: ReactNode }, { error: unknown }> {
  state = { error: null as unknown };

  static getDerivedStateFromError(error: unknown) {
    return { error };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error('page error', error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return <ErrorPanel error={this.state.error} onRetry={() => this.setState({ error: null })} />;
    }
    return this.props.children;
  }
}

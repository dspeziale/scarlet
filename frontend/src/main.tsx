import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ApiError } from '@/api/client';
import '@/i18n';
import '@/styles/app.css';
import App from './App';
import { AuthProvider } from '@/auth/AuthContext';
import { ToastProvider } from '@/components/Toasts';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Moderate polling: fresh enough for operations, gentle on the Kubernetes API.
      staleTime: 10_000,
      refetchInterval: 30_000,
      refetchIntervalInBackground: false,
      refetchOnWindowFocus: true,
      // Bounded retries, never on client errors (4xx).
      retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
      retryDelay: (n) => Math.min(8000, 1000 * 2 ** n),
    },
  },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ToastProvider>
          <AuthProvider>
            <App />
          </AuthProvider>
        </ToastProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);

import { lazy, Suspense, type ComponentType, type LazyExoticComponent, type ReactNode } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useAuth } from '@/auth/AuthContext';
import { useApi } from '@/hooks/api';
import type { SystemInfo } from '@/api/types';
import { Layout } from '@/components/layout/Layout';
import { Loading } from '@/components/ui';
import { ErrorPanel } from '@/components/ErrorPanel';
import { RouteErrorBoundary } from '@/components/ErrorBoundary';
import Login from '@/pages/Login';

function page(C: LazyExoticComponent<ComponentType>) {
  return (
    <RouteErrorBoundary>
      <Suspense fallback={<Loading />}>
        <C />
      </Suspense>
    </RouteErrorBoundary>
  );
}

// Lazy page components are created ONCE at module scope: creating them during render would
// suspend again on every render (and never complete a startTransition navigation).
const P = {
  dashboard: lazy(() => import('@/pages/Dashboard')),
  center: lazy(() => import('@/pages/OperationsCenter')),
  clusterOverview: lazy(() => import('@/pages/cluster/ClusterOverview')),
  list: lazy(() => import('@/pages/k8s/ResourceListPage')),
  detail: lazy(() => import('@/pages/k8s/ResourceDetailPage')),
  guide: lazy(() => import('@/pages/guide/GuidePage')),
  profile: lazy(() => import('@/pages/Profile')),
  notFound: lazy(() => import('@/pages/NotFound')),
  podContainers: lazy(() => import('@/pages/podman/Containers')),
  podContainer: lazy(() => import('@/pages/podman/ContainerDetail')),
  podImages: lazy(() => import('@/pages/podman/Images')),
  podRegistries: lazy(() => import('@/pages/podman/Registries')),
  monCpu: lazy(() => import('@/pages/monitoring/Cpu')),
  monMemory: lazy(() => import('@/pages/monitoring/Memory')),
  monStorage: lazy(() => import('@/pages/monitoring/Storage')),
  monHealth: lazy(() => import('@/pages/monitoring/Health')),
  monHa: lazy(() => import('@/pages/monitoring/HighAvailability')),
  monEvents: lazy(() => import('@/pages/monitoring/Events')),
  monLogs: lazy(() => import('@/pages/monitoring/Logs')),
  opOnboarding: lazy(() => import('@/pages/operations/ImageOnboarding')),
  opDeploy: lazy(() => import('@/pages/operations/DeployWizard')),
  opScale: lazy(() => import('@/pages/operations/Scale')),
  opRestart: lazy(() => import('@/pages/operations/Restart')),
  opRollout: lazy(() => import('@/pages/operations/Rollout')),
  opYaml: lazy(() => import('@/pages/operations/ApplyYaml')),
  opBackup: lazy(() => import('@/pages/operations/Backup')),
  opMaintenance: lazy(() => import('@/pages/operations/Maintenance')),
  secUsers: lazy(() => import('@/pages/security/Users')),
  secRoles: lazy(() => import('@/pages/security/Roles')),
  secPermissions: lazy(() => import('@/pages/security/Permissions')),
  secAudit: lazy(() => import('@/pages/security/Audit')),
  settings: lazy(() => import('@/pages/settings/SettingsPage')),
  setup: lazy(() => import('@/pages/setup/SetupWizard')),
};

function RequireAuth({ children }: { children: ReactNode }) {
  const { session, loading } = useAuth();
  const location = useLocation();
  if (loading) return <Loading />;
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  if (session.user.must_change_password && location.pathname !== '/profile') return <Navigate to="/profile?mustChange=1" replace />;
  return <>{children}</>;
}

export default function App() {
  const info = useApi<SystemInfo>('/system/info', undefined, { staleTime: 30_000, retry: 2 });
  const location = useLocation();
  if (info.isLoading) return <Loading />;
  if (info.error) {
    return (
      <div className="login-page">
        <div style={{ maxWidth: 640 }}>
          <ErrorPanel error={info.error} onRetry={() => void info.refetch()} />
        </div>
      </div>
    );
  }
  // First run: everything goes to the installation wizard.
  if (info.data?.setupRequired && location.pathname !== '/setup') return <Navigate to="/setup" replace />;

  return (
    <Routes>
      <Route path="/setup" element={page(P.setup)} />
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={page(P.dashboard)} />
        <Route path="operations-center" element={page(P.center)} />
        <Route path="cluster" element={page(P.clusterOverview)} />
        <Route path="cluster/nodes" element={<Navigate to="/k8s/nodes" replace />} />
        <Route path="cluster/namespaces" element={<Navigate to="/k8s/namespaces" replace />} />
        <Route path="cluster/events" element={<Navigate to="/k8s/events" replace />} />
        <Route path="k8s/:kind" element={page(P.list)} />
        <Route path="k8s/:kind/:namespace/:name" element={page(P.detail)} />
        <Route path="podman/containers" element={page(P.podContainers)} />
        <Route path="podman/containers/:id" element={page(P.podContainer)} />
        <Route path="podman/images" element={page(P.podImages)} />
        <Route path="podman/registries" element={page(P.podRegistries)} />
        <Route path="monitoring/cpu" element={page(P.monCpu)} />
        <Route path="monitoring/memory" element={page(P.monMemory)} />
        <Route path="monitoring/storage" element={page(P.monStorage)} />
        <Route path="monitoring/health" element={page(P.monHealth)} />
        <Route path="monitoring/ha" element={page(P.monHa)} />
        <Route path="monitoring/events" element={page(P.monEvents)} />
        <Route path="monitoring/logs" element={page(P.monLogs)} />
        <Route path="operations/onboarding" element={page(P.opOnboarding)} />
        <Route path="operations/deploy" element={page(P.opDeploy)} />
        <Route path="operations/scale" element={page(P.opScale)} />
        <Route path="operations/restart" element={page(P.opRestart)} />
        <Route path="operations/rollout" element={page(P.opRollout)} />
        <Route path="operations/yaml" element={page(P.opYaml)} />
        <Route path="operations/backup" element={page(P.opBackup)} />
        <Route path="operations/maintenance" element={page(P.opMaintenance)} />
        <Route path="security/users" element={page(P.secUsers)} />
        <Route path="security/roles" element={page(P.secRoles)} />
        <Route path="security/permissions" element={page(P.secPermissions)} />
        <Route path="security/audit" element={page(P.secAudit)} />
        <Route path="guide" element={page(P.guide)} />
        <Route path="guide/:slug" element={page(P.guide)} />
        <Route path="settings" element={<Navigate to="/settings/system" replace />} />
        <Route path="settings/:section" element={page(P.settings)} />
        <Route path="profile" element={page(P.profile)} />
        <Route path="*" element={page(P.notFound)} />
      </Route>
    </Routes>
  );
}

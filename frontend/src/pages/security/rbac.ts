import { useApi } from '@/hooks/api';

export interface RbacData {
  roles: { id: string; permissions: string[] }[];
  permissions: string[];
}

export function useRbac() {
  return useApi<RbacData>('/rbac/roles', undefined, { staleTime: 300_000 });
}

/** Permission groups for a readable matrix. */
export function permGroup(p: string): string {
  return p.split('.')[0];
}

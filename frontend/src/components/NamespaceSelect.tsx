import { useTranslation } from 'react-i18next';
import { useApi } from '@/hooks/api';
import type { ResourceList } from '@/api/types';

export function NamespaceSelect({
  value,
  onChange,
  allowAll = true,
  id,
}: {
  value: string;
  onChange: (ns: string) => void;
  allowAll?: boolean;
  id?: string;
}) {
  const { t } = useTranslation();
  const ns = useApi<ResourceList>('/k8s/namespaces', undefined, { staleTime: 60_000 });
  const names = (ns.data?.items ?? []).map((n) => n.name).sort();
  return (
    <select id={id} className="input sm" value={value} onChange={(e) => onChange(e.target.value)} aria-label={t('namespace')}>
      {allowAll && <option value="">{t('allNamespaces')}</option>}
      {!allowAll && !value && <option value="">—</option>}
      {names.map((n) => (
        <option key={n} value={n}>
          {n}
        </option>
      ))}
      {value && !names.includes(value) && <option value={value}>{value}</option>}
    </select>
  );
}

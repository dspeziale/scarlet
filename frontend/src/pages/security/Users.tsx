import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { KeyRound, Lock, Pencil, Plus, Trash2, Unlock } from 'lucide-react';
import { ApiError, del, patch, post } from '@/api/client';
import type { Role, User } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { useAction, useApi } from '@/hooks/api';
import { DataTable } from '@/components/DataTable';
import { ConfirmDialog, Dialog } from '@/components/Dialog';
import { ErrorPanel } from '@/components/ErrorPanel';
import { Alert, Badge, Card, Field, Loading, PageHeader } from '@/components/ui';
import { formatDate } from '@/utils/format';

const USERNAME_RE = /^[A-Za-z0-9][A-Za-z0-9._@-]{1,62}$/;
const ROLES: Role[] = ['admin', 'operator', 'viewer'];

/** Turns backend validation errors (password policy, conflicts, admin rules) into readable text. */
export function useUserErrorText() {
  const { t } = useTranslation('security');
  return (e: unknown): string => {
    if (!(e instanceof ApiError)) return String(e);
    const problems = e.params.problems as string[] | undefined;
    if (problems?.length) return problems.map((p) => t(`auth:policy.${p}`, { min: e.params.min_length })).join(' ');
    if (e.code === 'conflict') return t('users.errors.exists');
    if (e.params.rule) return t(`users.errors.${e.params.rule}`, { defaultValue: e.message });
    if (e.params.field === 'username') return t('users.errors.username');
    return e.message;
  };
}

function UserForm({ user, onClose }: { user?: User; onClose: () => void }) {
  const { t } = useTranslation('security');
  const errText = useUserErrorText();
  const editing = !!user;
  const [username, setUsername] = useState(user?.username ?? '');
  const [displayName, setDisplayName] = useState(user?.display_name ?? '');
  const [email, setEmail] = useState(user?.email ?? '');
  const [role, setRole] = useState<Role>(user?.role ?? 'viewer');
  const [language, setLanguage] = useState<'it' | 'en'>(user?.language ?? 'it');
  const [active, setActive] = useState(user?.active ?? true);
  const [password, setPassword] = useState('');
  const [repeat, setRepeat] = useState('');
  const [mustChange, setMustChange] = useState(true);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const save = useAction(
    () =>
      editing
        ? patch(`/users/${user!.id}`, { role, display_name: displayName, email, active, language })
        : post('/users', { username, password, role, display_name: displayName, email, language, must_change_password: mustChange }),
    { success: editing ? t('users.updated') : t('users.created'), onSuccess: onClose },
  );

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!editing) {
      if (!USERNAME_RE.test(username)) errs.username = t('users.errors.username');
      if (password.length < 12) errs.password = t('users.errors.passwordShort');
      if (password !== repeat) errs.repeat = t('users.errors.mismatch');
    }
    if (email && !/^[^@\s]+@[^@\s]+$/.test(email)) errs.email = t('users.errors.email');
    setErrors(errs);
    setServerError(null);
    if (Object.keys(errs).length) return;
    save.run().catch((err) => setServerError(errText(err)));
  };

  return (
    <Dialog
      title={editing ? t('users.editTitle', { name: user!.username }) : t('users.createTitle')}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            {t('common:cancel')}
          </button>
          <button type="submit" form="user-form" className="btn primary" disabled={save.busy}>
            {save.busy && <span className="spinner" aria-hidden="true" />} {t('common:save')}
          </button>
        </>
      }
    >
      <form id="user-form" onSubmit={submit} noValidate>
        {serverError && <Alert tone="err">{serverError}</Alert>}
        <div className="form-grid">
          <Field label={t('users.username')} htmlFor="u-name" error={errors.username} hint={editing ? undefined : t('users.usernameHint')}>
            <input id="u-name" className="input" value={username} disabled={editing} onChange={(e) => setUsername(e.target.value)} aria-invalid={!!errors.username} autoComplete="off" data-autofocus />
          </Field>
          <Field label={t('users.role')} htmlFor="u-role">
            <select id="u-role" className="input" value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {t(`common:roles.${r}`)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('users.displayName')} htmlFor="u-dn">
            <input id="u-dn" className="input" value={displayName} maxLength={120} onChange={(e) => setDisplayName(e.target.value)} />
          </Field>
          <Field label={t('users.email')} htmlFor="u-email" error={errors.email}>
            <input id="u-email" className="input" type="email" value={email} maxLength={200} onChange={(e) => setEmail(e.target.value)} aria-invalid={!!errors.email} />
          </Field>
          <Field label={t('common:language')} htmlFor="u-lang">
            <select id="u-lang" className="input" value={language} onChange={(e) => setLanguage(e.target.value as 'it' | 'en')}>
              <option value="it">Italiano</option>
              <option value="en">English</option>
            </select>
          </Field>
        </div>
        <p className="small muted">{t(`users.roleHelp.${role}`)}</p>
        {editing ? (
          <label className="checkbox">
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
            {t('users.active')}
          </label>
        ) : (
          <>
            <div className="form-grid">
              <Field label={t('users.password')} htmlFor="u-pw" error={errors.password} hint={t('auth:policyHint')}>
                <input id="u-pw" className="input" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} aria-invalid={!!errors.password} />
              </Field>
              <Field label={t('users.repeat')} htmlFor="u-pw2" error={errors.repeat}>
                <input id="u-pw2" className="input" type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} aria-invalid={!!errors.repeat} />
              </Field>
            </div>
            <label className="checkbox">
              <input type="checkbox" checked={mustChange} onChange={(e) => setMustChange(e.target.checked)} />
              {t('users.mustChange')}
            </label>
          </>
        )}
      </form>
    </Dialog>
  );
}

function PasswordDialog({ user, onClose }: { user: User; onClose: () => void }) {
  const { t } = useTranslation('security');
  const errText = useUserErrorText();
  const [pw, setPw] = useState('');
  const [mustChange, setMustChange] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const reset = useAction(() => post(`/users/${user.id}/password`, { password: pw, must_change_password: mustChange }), {
    success: t('users.passwordReset', { name: user.username }),
    onSuccess: onClose,
  });
  return (
    <Dialog
      title={t('users.resetTitle', { name: user.username })}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            {t('common:cancel')}
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={!pw || reset.busy}
            onClick={() => {
              setError(null);
              reset.run().catch((e) => setError(errText(e)));
            }}
          >
            {t('users.resetPassword')}
          </button>
        </>
      }
    >
      <p className="small">{t('users.resetExplain')}</p>
      {error && <Alert tone="err">{error}</Alert>}
      <Field label={t('users.newPassword')} htmlFor="r-pw" hint={t('auth:policyHint')}>
        <input id="r-pw" className="input" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} data-autofocus />
      </Field>
      <label className="checkbox">
        <input type="checkbox" checked={mustChange} onChange={(e) => setMustChange(e.target.checked)} />
        {t('users.mustChange')}
      </label>
    </Dialog>
  );
}

export default function Users() {
  const { t } = useTranslation('security');
  const { user: me, can } = useAuth();
  const errText = useUserErrorText();
  const q = useApi<{ items: User[] }>(can('users.manage') ? '/users' : null);
  const [form, setForm] = useState<User | 'new' | null>(null);
  const [pwFor, setPwFor] = useState<User | null>(null);
  const [deleting, setDeleting] = useState<User | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const unlock = useAction((u: User) => post(`/users/${u.id}/unlock`), { success: t('users.unlocked') });
  const remove = useAction(({ u, typed }: { u: User; typed: string }) => del(`/users/${u.id}`, { confirm: typed }), {
    success: t('users.deleted'),
    onSuccess: () => setDeleting(null),
  });

  if (!can('users.manage')) {
    return (
      <>
        <PageHeader title={t('users.title')} />
        <Alert tone="warn">{t('common:permissionDenied')}</Alert>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={t('users.title')}
        subtitle={t('users.subtitle')}
        actions={
          <button type="button" className="btn primary" onClick={() => setForm('new')}>
            <Plus size={14} /> {t('users.new')}
          </button>
        }
      />
      <Card flush>
        {q.isLoading && <Loading />}
        {q.error && <div style={{ padding: 12 }}><ErrorPanel error={q.error} onRetry={() => void q.refetch()} /></div>}
        {q.data && (
          <DataTable
            rows={q.data.items}
            rowKey={(u) => String(u.id)}
            initialSort={{ id: 'username', dir: 'asc' }}
            caption={t('users.title')}
            columns={[
              {
                id: 'username',
                header: t('users.username'),
                value: (u) => u.username,
                cell: (u) => (
                  <div>
                    <strong>{u.username}</strong> {u.id === me?.id && <Badge tone="info">{t('users.you')}</Badge>}
                    {u.display_name && <div className="small muted">{u.display_name}</div>}
                  </div>
                ),
              },
              { id: 'role', header: t('users.role'), value: (u) => u.role, cell: (u) => <Badge tone={u.role === 'admin' ? 'purple' : u.role === 'operator' ? 'info' : 'muted'}>{t(`common:roles.${u.role}`)}</Badge> },
              {
                id: 'status',
                header: t('common:status'),
                value: (u) => (u.active ? (u.locked ? 1 : 2) : 0),
                cell: (u) => (
                  <span className="row" style={{ gap: 4 }}>
                    {u.active ? <Badge tone="ok">{t('users.activeState')}</Badge> : <Badge tone="muted">{t('users.disabled')}</Badge>}
                    {u.locked && <Badge tone="err"><Lock size={11} /> {t('users.locked')}</Badge>}
                    {u.must_change_password && <Badge tone="warn">{t('users.pwPending')}</Badge>}
                  </span>
                ),
              },
              { id: 'email', header: t('users.email'), value: (u) => u.email, cell: (u) => u.email || '—' },
              { id: 'last', header: t('users.lastLogin'), value: (u) => u.last_login_at ?? '', cell: (u) => formatDate(u.last_login_at) },
              {
                id: 'actions',
                header: <span className="sr-only">{t('common:actions')}</span>,
                cell: (u) => (
                  <div className="row" style={{ flexWrap: 'nowrap' }}>
                    <button type="button" className="btn sm icon" aria-label={`${t('common:edit')} ${u.username}`} title={t('common:edit')} onClick={() => setForm(u)}>
                      <Pencil size={14} />
                    </button>
                    <button type="button" className="btn sm icon" aria-label={`${t('users.resetPassword')} ${u.username}`} title={t('users.resetPassword')} onClick={() => setPwFor(u)}>
                      <KeyRound size={14} />
                    </button>
                    {u.locked && (
                      <button type="button" className="btn sm icon" aria-label={`${t('users.unlock')} ${u.username}`} title={t('users.unlock')} onClick={() => void unlock.run(u)}>
                        <Unlock size={14} />
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn sm icon"
                      aria-label={`${t('common:delete')} ${u.username}`}
                      title={u.id === me?.id ? t('users.errors.self') : t('common:delete')}
                      disabled={u.id === me?.id}
                      onClick={() => {
                        setDeleteError(null);
                        setDeleting(u);
                      }}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ),
              },
            ]}
          />
        )}
      </Card>
      {form && <UserForm user={form === 'new' ? undefined : form} onClose={() => setForm(null)} />}
      {pwFor && <PasswordDialog user={pwFor} onClose={() => setPwFor(null)} />}
      {deleting && (
        <ConfirmDialog
          spec={{
            title: t('users.deleteTitle', { name: deleting.username }),
            operation: t('common:delete'),
            resource: `User/${deleting.username}`,
            consequences: t('users.deleteConsequences', { returnObjects: true }) as string[],
            risk: 'high',
            typeToConfirm: deleting.username,
            confirmLabel: t('common:delete'),
            danger: true,
          }}
          busy={remove.busy}
          onClose={() => setDeleting(null)}
          error={deleteError ? <Alert tone="err">{deleteError}</Alert> : null}
          onConfirm={(typed) => {
            setDeleteError(null);
            remove.run({ u: deleting, typed }).catch((e) => setDeleteError(errText(e)));
          }}
        />
      )}
    </>
  );
}

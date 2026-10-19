import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Bell, ChevronRight, ChevronsLeft, ChevronsRight, LogOut, Menu, Moon, Search, Sun, User as UserIcon } from 'lucide-react';
import { useAuth } from '@/auth/AuthContext';
import { useApi, useLiveEvents, useLocalState, useSystemStatus } from '@/hooks/api';
import type { NotificationCounts } from '@/api/types';
import { setLanguage } from '@/i18n';
import { NAV } from './nav';
import { NotificationDrawer } from './NotificationDrawer';
import { GlobalSearch } from './GlobalSearch';
import { classNames } from '@/utils/format';

function Logo() {
  return (
    <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="6" fill="#2b5fa3" />
      <path d="M16 5l9.5 5.5v11L16 27l-9.5-5.5v-11z" fill="none" stroke="#fff" strokeWidth="2" />
      <circle cx="16" cy="16" r="3.2" fill="#fff" />
    </svg>
  );
}

function useTheme(): ['light' | 'dark' | 'system', (v: 'light' | 'dark' | 'system') => void] {
  const [theme, setTheme] = useLocalState<'light' | 'dark' | 'system'>('pkm.theme', 'system');
  useEffect(() => {
    if (theme === 'system') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);
  return [theme, setTheme];
}

export function Layout() {
  const { t, i18n } = useTranslation('nav');
  const { user, can, logout } = useAuth();
  const location = useLocation();
  const status = useSystemStatus();
  const counts = useApi<{ counts: NotificationCounts }>('/notifications', { status: 'active', limit: 1 }, { refetchInterval: 60_000 });
  const [compact, setCompact] = useLocalState('pkm.sidebar.compact', false);
  const [open, setOpen] = useLocalState<Record<string, boolean>>('pkm.sidebar.groups', { applications: true });
  const [mobileOpen, setMobileOpen] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [search, setSearch] = useState(false);
  const [theme, setTheme] = useTheme();
  useLiveEvents(!!user);

  useEffect(() => setMobileOpen(false), [location.pathname]);
  useEffect(() => {
    // Open the group containing the current page.
    const g = NAV.find((grp) => grp.items?.some((it) => location.pathname === it.to || location.pathname.startsWith(it.to + '/')));
    if (g && !open[g.id]) setOpen({ ...open, [g.id]: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setSearch(true);
      } else if (e.key === '/' && !(e.target as HTMLElement).closest('input,textarea,select,[contenteditable],.cm-editor')) {
        e.preventDefault();
        setSearch(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const mode = status.data?.mode;
  const k8s = status.data?.kubernetes;
  const openCount = counts.data?.counts.open ?? 0;

  return (
    <div className={classNames('app', compact && 'compact', mobileOpen && 'mobile-open')}>
      <a href="#main" className="skip-link">
        {t('common:skipToContent')}
      </a>
      <div className="mode-banner">
        {mode === 'demo' && (
          <div className="demo-banner" role="status">
            {t('common:demoBanner')}
          </div>
        )}
      </div>
      <aside className="sidebar" aria-label={t('common:mainNavigation')}>
        <div className="brand">
          <Logo />
          <span className="brand-name ellipsis" title={t('common:appExpansion')}>{status.data?.appName ?? 'Scarlet'}</span>
        </div>
        <nav>
          <ul className="nav">
            {NAV.filter((g) => !g.perm || can(g.perm)).map((g) => {
              const Icon = g.icon;
              if (g.to) {
                return (
                  <li key={g.id}>
                    <NavLink to={g.to} end={g.to === '/'} className={({ isActive }) => classNames('nav-link', isActive && 'active')} title={compact ? t(g.id) : undefined}>
                      <Icon size={18} aria-hidden="true" />
                      <span className="nav-label">{t(g.id)}</span>
                    </NavLink>
                  </li>
                );
              }
              const expanded = !!open[g.id];
              const items = (g.items ?? []).filter((it) => !it.perm || can(it.perm));
              if (!items.length) return null;
              return (
                <li key={g.id}>
                  <button
                    type="button"
                    className="nav-group-btn"
                    aria-expanded={expanded}
                    aria-controls={`nav-${g.id}`}
                    title={compact ? t(g.id) : undefined}
                    onClick={() => {
                      if (compact) {
                        setCompact(false);
                        setOpen({ ...open, [g.id]: true });
                      } else setOpen({ ...open, [g.id]: !expanded });
                    }}
                  >
                    <Icon size={18} aria-hidden="true" />
                    <span className="nav-label">{t(g.id)}</span>
                    <ChevronRight size={14} className="chev" aria-hidden="true" />
                  </button>
                  {expanded && (
                    <ul className="nav-sub" id={`nav-${g.id}`}>
                      {items.map((it) => (
                        <li key={it.id}>
                          <NavLink to={it.to} className={({ isActive }) => classNames('nav-link', isActive && 'active')}>
                            <span className="nav-label">{t(it.id)}</span>
                          </NavLink>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="sidebar-footer">
          <button type="button" className="btn ghost sm" onClick={() => setCompact(!compact)} aria-label={compact ? t('common:expandMenu') : t('common:collapseMenu')}>
            {compact ? <ChevronsRight size={16} /> : <ChevronsLeft size={16} />}
            <span className="nav-label">{compact ? '' : t('common:collapseMenu')}</span>
          </button>
        </div>
      </aside>
      <header className="topbar">
        <button type="button" className="btn ghost icon mobile-only" onClick={() => setMobileOpen(!mobileOpen)} aria-label={t('common:openMenu')} aria-expanded={mobileOpen}>
          <Menu size={18} />
        </button>
        <button type="button" className="topbar-search" onClick={() => setSearch(true)} aria-label={t('common:searchOpen')}>
          <Search size={16} aria-hidden="true" />
          <span>{t('common:searchPlaceholder')}</span>
          <kbd>Ctrl K</kbd>
        </button>
        <div className="spacer" />
        {mode === 'demo' ? (
          <span className="env-chip demo" title={t('common:demoHelp')}>
            DEMO
          </span>
        ) : k8s?.connected ? (
          <span className="env-chip live" title={`${k8s.server ?? ''}`}>
            ● LIVE · {k8s.context}
          </span>
        ) : status.data ? (
          <span className="env-chip off" title={k8s?.error?.message}>
            {t('common:k8sDisconnected')}
          </span>
        ) : null}
        {status.data && (
          <span className="version-info" title={t('common:versionsTitle')}>
            K8s {k8s?.version ?? '—'} · Podman {status.data.podman.version ?? '—'} · Scarlet {status.data.version} · API {status.data.apiVersion}
          </span>
        )}
        <button type="button" className="btn ghost icon icon-btn-badge" onClick={() => setDrawer(true)} aria-label={t('common:notificationsOpen', { count: openCount })}>
          <Bell size={18} />
          {openCount > 0 && <span className="count">{openCount > 99 ? '99+' : openCount}</span>}
        </button>
        <button
          type="button"
          className="btn ghost icon"
          onClick={() => setTheme(theme === 'dark' ? 'light' : theme === 'light' ? 'system' : 'dark')}
          aria-label={t('common:themeToggle', { theme: t(`common:theme.${theme}`) })}
          title={t(`common:theme.${theme}`)}
        >
          {theme === 'dark' ? <Moon size={18} /> : <Sun size={18} />}
        </button>
        <select
          className="input sm"
          style={{ width: 64 }}
          value={i18n.language}
          aria-label={t('common:language')}
          onChange={(e) => setLanguage(e.target.value as 'it' | 'en')}
        >
          <option value="it">IT</option>
          <option value="en">EN</option>
        </select>
        <NavLink to="/profile" className="btn ghost sm" title={t('common:profile')}>
          <UserIcon size={16} />
          <span className="nowrap">{user?.username}</span>
          <span className="badge tone-info">{t(`common:roles.${user?.role}`)}</span>
        </NavLink>
        <button type="button" className="btn ghost icon" onClick={() => void logout()} aria-label={t('common:logout')} title={t('common:logout')}>
          <LogOut size={18} />
        </button>
      </header>
      <main className="main" id="main" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="app-footer">
        <span>{t('common:copyright', { year: new Date().getFullYear() })}</span>
        <span title={status.data ? `API ${status.data.apiVersion}` : undefined}>
          {status.data?.appName ?? 'Scarlet'} v{status.data?.version ?? '…'}
        </span>
      </footer>
      {drawer && <NotificationDrawer onClose={() => setDrawer(false)} />}
      {search && <GlobalSearch onClose={() => setSearch(false)} />}
      {mobileOpen && <div className="mobile-scrim" onClick={() => setMobileOpen(false)} aria-hidden="true" />}
    </div>
  );
}

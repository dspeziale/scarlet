// i18n: Italian (primary) and English. Every JSON file in locales/<lang>/ is a namespace
// (e.g. locales/it/k8s.json -> t('k8s:...')), loaded at build time.
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

export const LANGUAGES = ['it', 'en'] as const;
export type Language = (typeof LANGUAGES)[number];
const STORAGE_KEY = 'pkm.lang';

const files = import.meta.glob('./locales/*/*.json', { eager: true }) as Record<string, { default: Record<string, unknown> }>;
const resources: Record<string, Record<string, Record<string, unknown>>> = {};
for (const [path, mod] of Object.entries(files)) {
  const m = path.match(/\.\/locales\/(\w+)\/(\w+)\.json$/);
  if (!m) continue;
  const [, lang, ns] = m;
  resources[lang] ??= {};
  resources[lang][ns] = mod.default;
}

function initialLanguage(): Language {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'it' || saved === 'en') return saved;
  } catch {
    /* storage unavailable */
  }
  return navigator.language?.toLowerCase().startsWith('en') ? 'en' : 'it';
}

void i18n.use(initReactI18next).init({
  resources,
  lng: initialLanguage(),
  fallbackLng: 'it',
  defaultNS: 'common',
  ns: Object.keys(resources.it ?? { common: {} }),
  interpolation: { escapeValue: false },
  returnNull: false,
});

export function setLanguage(lang: Language): void {
  void i18n.changeLanguage(lang);
  document.documentElement.lang = lang;
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    /* ignore */
  }
}

document.documentElement.lang = i18n.language;
export default i18n;

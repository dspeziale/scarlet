# ADR-001: Frontend

- Data: 2026-10-19
- Stato: Accepted

## Contesto

La console deve essere una SPA enterprise, accessibile, bilingue, con editor YAML, diff, wizard e aggiornamenti live, mantenibile da un piccolo team.

## Decisione

React 18 + TypeScript (strict) + Vite. Routing con React Router 6, stato server con TanStack Query (cache, polling moderato, retry limitati), i18n con i18next (un file JSON per namespace, caricati a build time), editor YAML e diff con CodeMirror 6 (`@codemirror/lang-yaml`, `@codemirror/merge`), validazione YAML locale con js-yaml, Markdown della guida con marked + DOMPurify, icone lucide-react. Design system proprio in CSS con token e temi chiaro/scuro, senza librerie di componenti.

## Alternative considerate

Angular (più verboso); Vue (equivalente, meno diffuso nel team); librerie UI complete come MUI/Ant (peso, personalizzazione dei temi, stili dinamici in conflitto con una CSP restrittiva); Monaco editor (molto più pesante di CodeMirror).

## Conseguenze

Build statica servita dal backend, nessun server Node in produzione. Il bundle principale include la guida (ricerca istantanea, circa 275 KB gzip). Le pagine sono caricate in lazy loading.

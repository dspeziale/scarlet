# ADR-004: Autenticazione e sessioni

- Data: 2026-10-19
- Stato: Accepted

## Contesto

Servono autenticazione, RBAC e sessioni sicure senza dipendere da servizi esterni non garantiti negli ambienti di destinazione.

## Decisione

Utenti locali con hash Argon2id, policy delle password, blocco dopo tentativi falliti, rate limit. Sessioni lato server (nel DB solo lo SHA-256 del token) con scadenza per inattività e assoluta; cookie HttpOnly, SameSite=Strict, Secure e prefisso `__Host-` con TLS. CSRF con token per sessione nell'header `X-CSRF-Token` + controllo `Origin`. Tre ruoli fissi (Administrator, Operator, Viewer) verificati in ogni endpoint. Primo amministratore creato dal wizard protetto da token monouso o con `pkm-admin create-admin`.

## Alternative considerate

JWT stateless (revoca difficile); LDAP/OIDC (non configurati in modo uniforme negli ambienti target: evoluzione futura); ruoli personalizzabili (complessità non richiesta ora).

## Conseguenze

Nessuna dipendenza esterna. Integrazione LDAP/OIDC da aggiungere in futuro come provider alternativo.

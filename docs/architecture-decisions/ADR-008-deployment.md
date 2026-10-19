# ADR-008: Distribuzione e installazione

- Data: 2026-10-19
- Stato: Accepted

## Contesto

PKM va installato su Oracle Linux 9.7 con systemd, anche su server senza accesso a Internet, in modo semplice (`./install.sh`) e aggiornabile in sicurezza.

## Decisione

Tarball di release con i wheel di tutte le dipendenze (CPython 3.12 manylinux x86_64), script `install/upgrade/uninstall/backup/restore`, unit systemd con hardening e timer di backup. Installazione in `/opt/pkm/releases/<versione>` con symlink `current` (switch e rollback atomici), configurazione in `/etc/pkm`, dati in `/var/lib/pkm`. Modalità alternativa: immagine container e unit Quadlet per Podman. Docker non è richiesto.

## Alternative considerate

RPM (richiede infrastruttura di build/firma e repository); solo container (meno integrato con systemd e con il socket Podman dell'host); pip da Internet sul server (non sempre disponibile).

## Conseguenze

Upgrade con backup preventivo e rollback automatico (migrazioni del DB solo in avanti); test di installazione automatizzato su Oracle Linux 9 con systemd in un container privilegiato.

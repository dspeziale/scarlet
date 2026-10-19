# ADR-007: Diagnostica automatica

- Data: 2026-10-19
- Stato: Accepted

## Contesto

Il prodotto deve spiegare i problemi (CrashLoopBackOff, ImagePullBackOff, OOMKilled, Pending, NotReady...) e indicare cause e azioni, senza inventare informazioni.

## Decisione

Motore di regole in funzioni pure (`diagnostics.analyze`) su uno snapshot (Pod, nodi, workload, eventi, PVC, StorageClass, ConfigMap, Secret, metriche). Ogni problema ha gravità, motivo, risorsa, applicazione proprietaria, controlli con esito `ok|fail|warn|unknown` derivati dai dati (stati dei container, codici di uscita, messaggi degli eventi, capacità dei nodi, esistenza dei riferimenti) e causa più probabile. Se un controllo non è verificabile l'esito è `unknown`. I testi spiegativi sono tradotti nel frontend a partire dai codici.

## Alternative considerate

Regole configurabili dall'utente (complessità); euristiche opache o LLM (non verificabili); solo eventi Kubernetes (insufficienti per molte cause).

## Conseguenze

Facile da testare (test unitari per ogni motivo); riusato da Centro Operativo, notifiche e scheda Diagnostica.

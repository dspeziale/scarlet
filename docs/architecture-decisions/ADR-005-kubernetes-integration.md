# ADR-005: Integrazione Kubernetes

- Data: 2026-10-19
- Stato: Accepted

## Contesto

PKM deve leggere e modificare un insieme noto di risorse su versioni diverse di Kubernetes, con timeout espliciti ed errori comprensibili.

## Decisione

Il client ufficiale `kubernetes` è usato solo per caricare le credenziali (kubeconfig, in-cluster, certificati, plugin exec/OIDC, refresh dei token). Le richieste vanno direttamente ai percorsi REST noti definiti in `kinds.py` tramite urllib3, senza API discovery: JSON grezzo, timeout di connessione e lettura, un solo retry di connessione. Scritture con server-side apply (`fieldManager=pkm`), dry-run per la validazione, Eviction API per il drain. Errori mappati su codici stabili. Provider intercambiabile (`LiveKubernetes` / `DemoKubernetes`).

## Alternative considerate

API generate del client (conversioni costose; il livello di richiesta generato cambia tra le release); DynamicClient (discovery a ogni avvio, cache su disco); kubectl in subprocess (fragile, lento).

## Conseguenze

Indipendenza dal livello generato del client. I test di integrazione su kind hanno mostrato che con kubernetes-client 37 il token è memorizzato sotto la chiave `BearerToken`: l'header Authorization non veniva inviato. Il codice ora legge sia la chiave nuova sia quella precedente. Le apiVersion non servite dal cluster sono segnalate come `k8s_unsupported`.

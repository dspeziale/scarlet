---
title: Pubblicare una nuova applicazione
summary: Usa il wizard di Deploy per creare un Deployment con Service, risorse e health check, controllando il YAML prima di applicarlo.
category: procedures
order: 50
keywords: deploy, wizard, pubblicare, applicazione, deployment, service, immagine, health check
related: deployment, service, ingress, resource-request, readiness-probe, proc-rollback
---

## Quando serve

Quando devi mettere in esecuzione nel cluster un'applicazione nuova, a partire da un'immagine container già pubblicata su un registry. Per aggiornare un'applicazione esistente a una nuova versione usa invece la pagina [Rollout](app:/operations/rollout) o modifica il YAML del Deployment.

## Prerequisiti

- Ruolo **Operator** o **Administrator**.
- L'immagine esiste nel registry e il cluster può scaricarla (se il registry è privato serve un `imagePullSecret` nel namespace).
- Il namespace di destinazione esiste ([Namespace](app:/cluster/namespaces)).
- Conosci dall'applicazione: porta in ascolto, fabbisogno indicativo di CPU e RAM, un endpoint di salute (es. `/healthz`) e se ha bisogno di dati persistenti.

## Procedura

Consigliato: parti da [Operazioni → Onboarding immagine](app:/operations/onboarding). Il wizard verifica l'immagine sul registry (esistenza del tag, credenziali, architettura linux/amd64), mostra cosa contiene (porte esposte, utente, variabili, volumi) e i rischi (tag `latest`, esecuzione come root…), propone nome, repliche, porta, storage e health check e con **Continua nel wizard di deploy** apre il deploy già compilato.

In alternativa apri direttamente [Operazioni → Deploy](app:/operations/deploy) e compila i passi del wizard:

1. **Nome**: minuscole, numeri e trattini (es. `ordini-api`); scegli anche il namespace.
2. **Immagine**: es. `registry.example.com/team/ordini-api`.
3. **Tag**: usa una versione precisa (`1.4.2`), **non** `latest`: con `latest` non sai cosa gira e il rollback non è affidabile.
4. **Repliche**: almeno `2` per un servizio che deve restare disponibile durante aggiornamenti e manutenzioni.
5. **Porta**: la porta su cui ascolta il container (es. `8080`).
6. **CPU**: request (es. `100m`) ed eventuale limit. La request serve allo scheduler per scegliere il nodo.
7. **RAM**: request e limit (es. `256Mi` / `512Mi`). Se il processo supera il limit viene terminato (OOMKilled).
8. **Storage**: solo se servono dati persistenti; crea un PVC con la StorageClass scelta.
9. **Networking**: crea il Service (tipicamente `ClusterIP`) ed eventualmente un Ingress con host e percorso.
10. **Health check**: configura readiness probe (quando il Pod può ricevere traffico) e liveness probe (quando va riavviato). Sulla liveness lascia un ritardo iniziale adeguato ai tempi di avvio.
11. **Riepilogo**: leggi il **YAML generato**, l'esito della **validazione sul cluster** (dry-run) e i **rischi** segnalati (es. una sola replica, nessun limit di memoria, tag `latest`, nessuna probe). Correggi tornando indietro se necessario.
12. **Deploy**: conferma. L'operazione viene registrata nell'Audit Log.

Equivalente da shell per un amministratore (salvando prima il YAML del riepilogo in un file):

```bash
kubectl apply --dry-run=server -f ordini-api.yaml   # validazione lato server
kubectl apply -f ordini-api.yaml
kubectl -n produzione rollout status deployment/ordini-api
```

## Verifica

- In [Deployments](app:/k8s/deployments) il nuovo Deployment mostra repliche pronte uguali a quelle desiderate (es. `2/2`).
- Nella scheda **Eventi** del Deployment non ci sono Warning.
- I Pod sono **Running** e **Ready**; nella scheda **Log** l'applicazione si è avviata correttamente.
- In [Endpoints](app:/k8s/endpoints) il Service ha indirizzi: significa che la readiness probe passa e il selettore trova i Pod.
- Se hai creato un Ingress, l'URL risponde.

## Se qualcosa va storto

- **ImagePullBackOff / ErrImagePull**: nome, tag o credenziali del registry errati. Vedi [ImagePullBackOff](guide:imagepullbackoff).
- **Pending**: risorse richieste troppo alte o PVC non legato. Vedi [Pending](guide:pending).
- **CrashLoopBackOff**: l'applicazione esce subito; leggi i log del container precedente. Vedi [CrashLoopBackOff](guide:crashloopbackoff).
- **CreateContainerConfigError**: manca un ConfigMap o un Secret referenziato. Vedi [CreateContainerConfigError](guide:createcontainerconfigerror).
- **Running ma mai Ready**: la readiness probe fallisce (percorso o porta sbagliati).
- **Il Service non ha endpoint**: il selettore del Service non corrisponde alle label dei Pod.
- Se il deploy era un aggiornamento e peggiora la situazione, valuta subito un [rollback](guide:proc-rollback).

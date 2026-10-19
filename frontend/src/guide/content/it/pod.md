---
title: Pod
summary: L'unità minima che Kubernetes esegue, composta da uno o più container che condividono rete e volumi.
category: concepts
order: 40
keywords: pod, fasi, pending, running, succeeded, failed, unknown, restart, ready, init container
related: container, deployment, node, scheduling, troubleshooting, proc-diagnosticare-pod, pod-failed-unknown
---

## In parole semplici

Un pod è la "scatola" in cui Kubernetes fa girare la tua applicazione. Di solito contiene un solo container; a volte un container principale più qualche container di supporto (ad esempio un proxy o un raccoglitore di log).

I pod sono **usa e getta**: se un pod muore o il suo nodo si guasta, Kubernetes non lo ripara, ne crea uno nuovo (con un nome e un IP diversi). Per questo non si creano quasi mai pod a mano: li crea un [Deployment](guide:deployment), uno [StatefulSet](guide:statefulset), un [DaemonSet](guide:daemonset) o un [Job](guide:job).

## Dettagli tecnici

I container di un pod condividono lo stesso network namespace (stesso IP, si parlano su `localhost`) e possono montare gli stessi [volumi](guide:volume). Un pod gira sempre interamente su un solo [nodo](guide:node).

**Fasi del pod** (`status.phase`):

| Fase | Significato |
|---|---|
| Pending | Accettato ma non ancora avviato: in attesa di scheduling, pull dell'immagine o volumi |
| Running | Assegnato a un nodo, almeno un container in esecuzione |
| Succeeded | Tutti i container terminati con successo (tipico dei Job) |
| Failed | Tutti i container terminati, almeno uno con errore |
| Unknown | Lo stato non è ottenibile, di solito perché il nodo non risponde |

Stati come `CrashLoopBackOff`, `ImagePullBackOff`, `CreateContainerConfigError` **non sono fasi**: sono `reason` dello stato `waiting` di un container, visibili nella colonna STATUS di `kubectl get pods`.

**Condizioni**: `PodScheduled`, `Initialized`, `ContainersReady`, `Ready`. Solo i pod `Ready` ricevono traffico dai [Service](guide:service), e Ready dipende dalla [readiness probe](guide:readiness-probe).

**restartPolicy**: `Always` (default, obbligatoria nei Deployment), `OnFailure`, `Never` (usate nei Job). I riavvii usano un backoff esponenziale fino a 5 minuti.

Gli **init container** girano in sequenza prima dei container principali e devono terminare con successo.

## Esempio

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: debug-tools
  namespace: collaudo
spec:
  restartPolicy: Never
  containers:
    - name: tools
      image: registry.access.redhat.com/ubi9/ubi-minimal:latest
      command: ["sleep", "3600"]
      resources:
        requests: { cpu: 50m, memory: 64Mi }
        limits: { memory: 128Mi }
```

```bash
# Alternativa da shell
kubectl get pods -n collaudo -o wide
kubectl describe pod debug-tools -n collaudo
kubectl logs debug-tools -n collaudo --previous
```

## Cosa può andare storto

- Resta [Pending](guide:pending): nessun nodo adatto, PVC non legato, quota superata.
- [ImagePullBackOff / ErrImagePull](guide:imagepullbackoff): immagine o credenziali errate.
- [CrashLoopBackOff](guide:crashloopbackoff): il processo esce subito dopo l'avvio.
- [OOMKilled](guide:oomkilled): supera il limite di memoria.
- [CreateContainerConfigError](guide:createcontainerconfigerror): ConfigMap o Secret mancanti.
- Running ma non Ready: readiness probe che fallisce.
- [Failed o Unknown](guide:pod-failed-unknown).

## Come verificare

- [Applicazioni → Pod](app:/k8s/pods): stato, ready, riavvii, nodo, età.
- Dettaglio del pod: **Panoramica** (stato dei container e ultimo motivo di terminazione), **Eventi**, **Log** (anche del container precedente), **Diagnostica**.
- Procedura: [Diagnosticare un pod](guide:proc-diagnosticare-pod).

## Come risolvere

- Leggi prima gli **Eventi**, poi i **Log** (del container precedente, se si è riavviato). Il motivo è quasi sempre lì.
- Correggi la causa nel controller (Deployment, StatefulSet...) e non nel pod: le modifiche fatte al pod si perdono alla sua ricreazione.
- Un restart da [Operazioni → Restart](app:/operations/restart) ricrea i pod, ma **non risolve** problemi di configurazione: usalo solo quando la causa è stata eliminata.
- Se il problema è iniziato con un rilascio, valuta un [rollback](guide:rollback).

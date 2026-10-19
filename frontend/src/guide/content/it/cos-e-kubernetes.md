---
title: Cos'è Kubernetes
summary: La piattaforma che esegue i container su più macchine e mantiene le applicazioni nello stato desiderato.
category: intro
order: 20
keywords: kubernetes, k8s, orchestratore, control plane, api server, kubectl, stato desiderato
related: cluster, node, pod, deployment, cos-e-podman, namespace
---

## In parole semplici

Kubernetes è un **orchestratore di container**: prende le tue applicazioni impacchettate in container e le fa girare su un gruppo di macchine (il [cluster](guide:cluster)), decidendo dove metterle, riavviandole se si bloccano e sostituendole se una macchina si guasta.

L'idea chiave è lo **stato desiderato**. Tu non dici "avvia questo container su quella macchina"; dici "voglio 3 copie di questa applicazione, con questa immagine, raggiungibili su questa porta". Kubernetes confronta continuamente ciò che hai chiesto con ciò che sta succedendo davvero e corregge le differenze da solo.

## Dettagli tecnici

Un cluster Kubernetes è composto da:

- **Control plane**: `kube-apiserver` (l'unico punto di ingresso, espone le API REST), `etcd` (il database chiave-valore che contiene tutto lo stato del cluster), `kube-scheduler` (assegna i pod ai nodi), `kube-controller-manager` (esegue i controller che riconciliano lo stato: Deployment, ReplicaSet, Node, Job...).
- **Nodi worker**: ogni [nodo](guide:node) esegue `kubelet` (avvia e controlla i container tramite il runtime, di solito containerd o CRI-O), `kube-proxy` (regole di rete per i Service) e un plugin di rete CNI.

Tutto in Kubernetes è un **oggetto API** descritto in YAML o JSON con quattro parti: `apiVersion`, `kind`, `metadata` (nome, namespace, label, annotation) e `spec` (lo stato desiderato). Kubernetes aggiunge `status` (lo stato osservato). I controller lavorano in un ciclo di **riconciliazione**: leggono `spec`, osservano la realtà, agiscono per avvicinarle.

Gli oggetti principali che userai: [Pod](guide:pod), [Deployment](guide:deployment), [StatefulSet](guide:statefulset), [DaemonSet](guide:daemonset), [Job](guide:job), [Service](guide:service), [Ingress](guide:ingress), [ConfigMap](guide:configmap), [Secret](guide:secret), [PersistentVolumeClaim](guide:persistent-volume-claim). Gli oggetti sono raggruppati in [namespace](guide:namespace).

L'accesso è controllato da **RBAC**: Role/ClusterRole definiscono cosa si può fare, RoleBinding/ClusterRoleBinding a chi è concesso. Scarlet si collega con un kubeconfig, idealmente di un ServiceAccount dedicato, e può fare solo ciò che quel ServiceAccount è autorizzato a fare.

## Esempio

Un Deployment minimo che chiede tre copie di un server web:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  namespace: demo
spec:
  replicas: 3
  selector:
    matchLabels:
      app: web
  template:
    metadata:
      labels:
        app: web
    spec:
      containers:
        - name: nginx
          image: nginx:1.27
          ports:
            - containerPort: 80
```

Alternativa da shell (per amministratori):

```bash
kubectl apply -f web.yaml
kubectl get deployment web -n demo
kubectl get pods -n demo -l app=web -o wide
```

## Cosa può andare storto

- **API server irraggiungibile**: Scarlet e `kubectl` non possono leggere né modificare nulla. Le applicazioni già in esecuzione di solito continuano a girare, ma niente viene riconciliato.
- **Permessi RBAC insufficienti**: operazioni rifiutate con errore `Forbidden`.
- **Stato desiderato impossibile**: ad esempio richieste di risorse superiori alla capacità dei nodi; i pod restano [Pending](guide:pending).
- **Nodi non pronti**: vedi [Node NotReady](guide:node-notready).

## Come verificare

- In Scarlet apri [Cluster → Panoramica](app:/cluster): versione, numero di nodi, stato dei componenti.
- Controlla la pagina [Health](app:/monitoring/health): la voce Kubernetes deve essere Healthy.
- Da shell:

```bash
kubectl cluster-info
kubectl get nodes
kubectl get --raw='/readyz?verbose'
```

## Come risolvere

- Se la connessione fallisce, verifica il kubeconfig in [Impostazioni → Kubernetes](app:/settings/kubernetes) e segui [Collegare Kubernetes](guide:proc-collegare-kubernetes).
- Se ricevi `Forbidden`, il ServiceAccount usato da Scarlet non ha i permessi: un amministratore del cluster deve aggiornare il ClusterRole.
- Per problemi su singole risorse, parti dal [Centro Operativo](app:/operations-center) e segui il metodo descritto in [Troubleshooting](guide:troubleshooting).

---
title: Cluster
summary: L'insieme di control plane e nodi che Kubernetes gestisce come un'unica piattaforma.
category: concepts
order: 10
keywords: cluster, control plane, etcd, api server, contesto, kubeconfig
related: node, namespace, cos-e-kubernetes, proc-verificare-cluster, alta-disponibilita, backup
---

## In parole semplici

Un cluster è il "computer unico" che Kubernetes costruisce mettendo insieme più macchine. Tu consegni le applicazioni al cluster, non a una macchina specifica: è il cluster a decidere dove eseguirle e a tenerle in vita.

In Scarlet, la pagina [Cluster → Panoramica](app:/cluster) ti dà la fotografia del cluster a cui sei collegato: il nome del contesto (lo stesso del badge LIVE), la versione di Kubernetes, quanti nodi ci sono e se sono pronti, quanti pod girano e quali problemi sono aperti.

## Dettagli tecnici

Un cluster ha due parti:

- **Control plane**: `kube-apiserver`, `etcd`, `kube-scheduler`, `kube-controller-manager` (e, nei cloud, `cloud-controller-manager`). In un cluster di produzione il control plane ha **almeno tre nodi**, perché `etcd` usa un quorum (maggioranza): con 3 membri tollera la perdita di 1, con 5 la perdita di 2.
- **Nodi worker**: eseguono i pod. Vedi [Node](guide:node).

Il client (Scarlet, `kubectl`) si collega all'API server usando un **kubeconfig**, che contiene l'indirizzo del server, il certificato della CA e le credenziali. Un kubeconfig può contenere più **contesti** (cluster + utente + namespace di default); Scarlet usa quello configurato in [Impostazioni → Kubernetes](app:/settings/kubernetes).

Tutto lo stato del cluster vive in `etcd`. Per questo un vero backup del cluster è uno **snapshot di etcd** (o uno strumento come Velero), cosa diversa dall'esportazione di manifest che offre Scarlet: vedi [Backup](guide:backup).

Le risorse si dividono in **namespaced** (Pod, Deployment, Service, ConfigMap, Secret, PVC...) e **cluster-scoped** (Node, PersistentVolume, StorageClass, Namespace, ClusterRole...).

## Esempio

```bash
# Alternativa da shell
kubectl config current-context
kubectl version
kubectl get nodes -o wide
kubectl get pods -A --field-selector=status.phase!=Running
kubectl get --raw='/readyz?verbose'
```

Estratto di un kubeconfig:

```yaml
apiVersion: v1
kind: Config
clusters:
  - name: prod
    cluster:
      server: https://k8s-api.example.local:6443
      certificate-authority-data: LS0tLS1CRUdJTi...
contexts:
  - name: pkm@prod
    context:
      cluster: prod
      user: pkm
current-context: pkm@prod
```

## Cosa può andare storto

- **API server non raggiungibile**: rete, firewall, certificati scaduti, control plane fermo. Scarlet mostra Kubernetes come Unhealthy.
- **Perdita del quorum etcd**: l'API server diventa in sola lettura o non risponde; nessuna modifica è possibile.
- **Certificati del cluster scaduti** (tipico dei cluster kubeadm non aggiornati da un anno).
- **Contesto sbagliato**: stai guardando (o modificando) il cluster sbagliato.
- **Nodi NotReady**: capacità ridotta, pod da ripianificare.

## Come verificare

- [Cluster → Panoramica](app:/cluster) e [Health](app:/monitoring/health).
- [Eventi del cluster](app:/cluster/events): filtra per tipo Warning.
- Controlla il nome del contesto nel badge LIVE prima di ogni azione.
- Procedura completa: [Verificare il cluster](guide:proc-verificare-cluster).

## Come risolvere

- Connessione assente: verifica rete e firewall verso la porta dell'API server (di solito 6443), poi il kubeconfig in [Impostazioni → Kubernetes](app:/settings/kubernetes).
- Certificati scaduti o problemi del control plane: sono interventi dell'amministratore del cluster (es. `kubeadm certs check-expiration`), non risolvibili da Scarlet.
- Nodi NotReady: segui [Node NotReady](guide:node-notready).
- Contesto sbagliato: correggi il kubeconfig configurato e verifica di nuovo il badge.

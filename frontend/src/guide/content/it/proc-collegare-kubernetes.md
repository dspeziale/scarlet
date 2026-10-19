---
title: Collegare PKM a Kubernetes
summary: Crea un ServiceAccount dedicato, genera il suo kubeconfig e configuralo in PKM con i permessi corretti.
category: procedures
order: 20
keywords: kubeconfig, serviceaccount, rbac, clusterrole, connessione, in-cluster, token
related: cos-e-kubernetes, cluster, proc-installare, proc-verificare-cluster, faq
---

## Quando serve

Durante il primo setup (passo **Kubernetes** del wizard) oppure quando cambi cluster, ruoti le credenziali o vedi in [Health](app:/monitoring/health) lo stato di Kubernetes **Unhealthy**.

## Prerequisiti

- PKM installato (vedi [Installare PKM](guide:proc-installare)).
- Un accesso amministrativo al cluster (`kubectl` con permessi di cluster-admin) da cui creare le risorse RBAC.
- Il manifest `deploy/kubernetes/pkm-rbac.yaml` contenuto nel pacchetto di rilascio.

Usare il kubeconfig personale di un amministratore funziona, ma è sconsigliato: PKM avrebbe tutti i tuoi poteri e le azioni nei log del cluster risulterebbero tue. Un **ServiceAccount dedicato** limita i permessi a quelli previsti dalla ClusterRole e rende tracciabile ciò che fa PKM.

## Procedura

1. Applica il manifest RBAC incluso nel pacchetto (sul cluster, con privilegi di amministratore). Crea il namespace `pkm-system`, il ServiceAccount `pkm`, il Secret `pkm-token` con un token a lunga durata e due ClusterRole: `pkm-operator` (collegato di default: lettura + le operazioni offerte da PKM) e `pkm-readonly` (sola lettura; per usarlo cambia `roleRef.name` nel ClusterRoleBinding `pkm`):

   ```bash
   kubectl apply -f /opt/pkm/current/deploy/kubernetes/pkm-rbac.yaml
   kubectl -n pkm-system get serviceaccount pkm
   ```

2. Genera il kubeconfig del ServiceAccount con lo script incluso, su una macchina dove `kubectl` funziona con privilegi di amministratore (ad esempio un nodo del control plane, con lo script copiato da `/opt/pkm/current/scripts/make-kubeconfig.sh`):

   ```bash
   ./make-kubeconfig.sh -o /tmp/pkm-kubeconfig            # opzione --context <nome> per scegliere il cluster
   kubectl --kubeconfig /tmp/pkm-kubeconfig get nodes      # prova
   ```

   Lo script legge il token dal Secret `pkm-system/pkm-token`, il server e la CA dal contesto corrente e scrive un kubeconfig con contesto `pkm@<cluster>`. Se lo esegui direttamente sul server PKM come root, usa `-o /etc/pkm/kubeconfig` e salta il passo 4.

3. Il file contiene un token a lunga durata: non copiarlo in posti condivisi e non inserirlo in repository.

4. Copia il file sul server PKM con i permessi corretti (leggibile dall'utente `pkm`, non dagli altri):

   ```bash
   sudo install -o root -g pkm -m 0640 /tmp/pkm-kubeconfig /etc/pkm/kubeconfig
   rm -f /tmp/pkm-kubeconfig /tmp/ca.crt
   ```

5. In PKM apri [Impostazioni → Kubernetes](app:/settings/kubernetes) (o il passo Kubernetes del wizard), indica il percorso `/etc/pkm/kubeconfig`, salva ed esegui il test di connessione.

6. Alternativa **in-cluster**: se PKM gira come Pod nel cluster, seleziona la modalità in-cluster; userà il token del ServiceAccount montato nel Pod, che deve essere `pkm` con la ClusterRole applicata.

## Verifica

- Dal server PKM, con l'identità di PKM:

  ```bash
  sudo -u pkm kubectl --kubeconfig /etc/pkm/kubeconfig get nodes
  sudo -u pkm kubectl --kubeconfig /etc/pkm/kubeconfig auth can-i list pods -A
  ```

- In [Health](app:/monitoring/health) la voce Kubernetes è **Healthy**.
- Il badge **LIVE** mostra il contesto `pkm`.
- [Cluster → Panoramica](app:/cluster) elenca nodi e namespace reali.

## Se qualcosa va storto

- **`x509: certificate signed by unknown authority`**: la CA nel kubeconfig non è quella del server API; ripeti il passo 3 dal contesto corretto.
- **`Unauthorized` (401)**: token scaduto o errato; generane uno nuovo (passo 2) e aggiorna il file.
- **`Forbidden` (403) su alcune risorse**: la ClusterRole non comprende quel verbo o quella risorsa. Controlla con `kubectl auth can-i --list --as=system:serviceaccount:pkm-system:pkm`. Non allargare i permessi a cluster-admin per comodità.
- **`permission denied` sul file**: verifica `ls -l /etc/pkm/kubeconfig` (deve essere `root:pkm 0640`).
- **Timeout**: il server PKM non raggiunge l'API server (porta tipica 6443); verifica rete e firewall.

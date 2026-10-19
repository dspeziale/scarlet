---
title: DaemonSet
summary: Esegue una copia di un Pod su ogni nodo (o su un gruppo di nodi), tipicamente per agenti di sistema.
category: workloads
order: 40
keywords: daemonset, agente, nodo, log collector, cni, taint, toleration
related: node, scheduling, pod, proc-manutenzione-nodo, monitoring
---

## In parole semplici

Un **DaemonSet** fa in modo che **ogni nodo** del cluster esegua una copia di un certo Pod. Quando aggiungi un nodo, il Pod compare automaticamente anche lì; quando rimuovi il nodo, il Pod sparisce.

Si usa per i "servizi di sistema" che devono stare su tutte le macchine: raccolta log (Fluent Bit), monitoraggio del nodo (node-exporter), rete del cluster (Calico, Cilium, Flannel), driver di storage (CSI node plugin), kube-proxy.

## Dettagli tecnici

- Non ha `replicas`: il numero di Pod dipende dai nodi idonei. `status.desiredNumberScheduled`, `currentNumberScheduled`, `numberReady` e `numberUnavailable` descrivono lo stato.
- I nodi idonei si limitano con `spec.template.spec.nodeSelector` o `affinity`.
- I nodi con **taint** (es. i control plane con `node-role.kubernetes.io/control-plane:NoSchedule`) sono esclusi a meno che il Pod abbia una `toleration` corrispondente. Il controller aggiunge automaticamente alcune tolerations (ad esempio per `node.kubernetes.io/not-ready` e `unreachable` con effetto NoExecute, e `unschedulable`).
- I Pod del DaemonSet vengono schedulati dallo scheduler standard tramite node affinity verso il nodo specifico.
- `updateStrategy`: `RollingUpdate` (default, `maxUnavailable: 1`) oppure `OnDelete`.
- Durante il **drain** di un nodo i Pod dei DaemonSet vengono **saltati**: tanto verrebbero ricreati subito sullo stesso nodo. Il drain di PKM in [Operazioni → Manutenzione](app:/operations/maintenance) fa esattamente questo.

In PKM: [Applicazioni → DaemonSets](app:/k8s/daemonsets).

## Esempio

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-exporter
  namespace: monitoring
spec:
  selector:
    matchLabels: { app: node-exporter }
  template:
    metadata:
      labels: { app: node-exporter }
    spec:
      tolerations:
        - key: node-role.kubernetes.io/control-plane
          operator: Exists
          effect: NoSchedule
      containers:
        - name: node-exporter
          image: quay.io/prometheus/node-exporter:v1.8.2
          ports: [{ containerPort: 9100, hostPort: 9100 }]
          resources:
            requests: { cpu: 50m, memory: 32Mi }
            limits: { memory: 64Mi }
```

## Cosa può andare storto

- **Desired ≠ Ready**: su alcuni nodi il Pod non parte (immagine non scaricabile, porta `hostPort` già occupata, permessi insufficienti).
- **Nodo escluso inaspettatamente**: manca la toleration per un taint o il nodeSelector non corrisponde alle etichette del nodo.
- **Risorse del nodo esaurite**: un agente senza limiti di memoria può portare il nodo in pressione e causare evizioni di altri Pod.
- **DaemonSet di rete o storage guasto**: tutti i Pod di quel nodo possono avere problemi di rete o di montaggio volumi; spesso il nodo diventa [NotReady](guide:node-notready).

## Come verificare

In PKM apri il DaemonSet e confronta pianificati/pronti; nella scheda Relazioni vedi su quali nodi gira ogni Pod.

```bash
kubectl -n monitoring get daemonset node-exporter
kubectl -n monitoring get pods -l app=node-exporter -o wide
kubectl describe node <nodo> | grep -i taints
```

## Come risolvere

1. Identifica il nodo dove il Pod manca o fallisce e leggi gli eventi del Pod.
2. Se il nodo è escluso, aggiungi la toleration o correggi il nodeSelector nella scheda YAML (valida con dry-run prima di applicare).
3. Per conflitti di `hostPort`, individua il processo o il Pod che usa la porta sul nodo.
4. Imposta sempre requests e limits sugli agenti: vedi [Resource limit](guide:resource-limit).
5. Se un aggiornamento rompe gli agenti, effettua un [rollback](guide:rollback) (`kubectl rollout undo daemonset/node-exporter`).

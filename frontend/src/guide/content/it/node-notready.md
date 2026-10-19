---
title: Nodo NotReady
summary: Il nodo non comunica correttamente con il control plane e non può eseguire nuovi pod in modo affidabile.
category: troubleshooting
order: 60
keywords: notready, nodo, kubelet, node conditions, memorypressure, diskpressure, pidpressure, network unavailable
related: node, proc-verificare-nodo, proc-manutenzione-nodo, alta-disponibilita, troubleshooting, pod-failed-unknown
---

## In parole semplici

Ogni nodo esegue un agente, il **kubelet**, che segnala periodicamente al control plane "sono vivo e sto bene". Se queste segnalazioni si interrompono o riportano un problema, il nodo diventa **NotReady**. Lo scheduler smette di mettere nuovi pod su quel nodo e, dopo alcuni minuti, Kubernetes sposta altrove i pod gestiti dai controller.

Le cause tipiche sono: il nodo è spento o irraggiungibile in rete, il kubelet o il container runtime si è fermato, il disco è pieno, la memoria è esaurita, oppure il plugin di rete (CNI) non funziona.

## Dettagli tecnici

- Il kubelet aggiorna un oggetto `Lease` nel namespace `kube-node-lease` (di default ogni 10 secondi) e lo stato del nodo. Se il node controller non riceve aggiornamenti per `node-monitor-grace-period` (40-50 secondi a seconda della versione), la condizione `Ready` passa a `Unknown`.
- Valori della condizione `Ready`: `True` (sano), `False` (il kubelet risponde ma segnala un problema, ad esempio il runtime non funziona), `Unknown` (nessuna notizia dal kubelet).
- Altre condizioni: `MemoryPressure`, `DiskPressure`, `PIDPressure`, `NetworkUnavailable`. Quando sono `True`, il kubelet può sfrattare pod.
- Il nodo riceve automaticamente i taint `node.kubernetes.io/not-ready` o `node.kubernetes.io/unreachable` con effetto `NoExecute`. I pod hanno per default una toleration di 300 secondi: dopo 5 minuti vengono sfrattati e ricreati dai controller su altri nodi.
- I pod di uno StatefulSet sul nodo irraggiungibile non vengono sostituiti automaticamente finché Kubernetes non è sicuro che il vecchio pod sia fermo: questo evita due istanze con la stessa identità.
- I pod che erano sul nodo possono apparire in stato `Unknown` o `Terminating` (vedi [Pod Failed e Unknown](guide:pod-failed-unknown)).

## Esempio

```bash
kubectl get nodes
# NAME       STATUS     ROLES           AGE   VERSION
# worker-2   NotReady   <none>          41d   v1.30.4

kubectl describe node worker-2 | sed -n '/Conditions/,/Addresses/p'

# Sul nodo (alternativa per amministratori)
sudo systemctl status kubelet
sudo journalctl -u kubelet --since "15 min ago"
sudo systemctl status crio    # oppure containerd
df -h /var
```

## Cosa può andare storto

- `/var` pieno (log, immagini): `DiskPressure` e kubelet che non riesce a lavorare.
- Il kubelet si ferma dopo un aggiornamento del sistema operativo o per un certificato client scaduto.
- Swap attivo dopo un riavvio, se il kubelet è configurato per rifiutarlo.
- Problemi di rete o firewall tra nodo e API server (porta 6443).
- Orologio di sistema non sincronizzato: errori di certificati TLS.
- Riavviare il nodo senza drain: i pod vengono interrotti bruscamente.

## Come verificare

1. Il [Centro Operativo](app:/operations-center) segnala i nodi NotReady come problema critico.
2. Apri il nodo in [Cluster → Nodi](app:/cluster/nodes): nella **Panoramica** vedi le condizioni, l'ultimo heartbeat e i taint.
3. Negli **Eventi** del nodo cerca `NodeNotReady`, `KubeletNotReady`, `EvictionThresholdMet`.
4. In [Monitoraggio → Alta affidabilità](app:/monitoring/ha) verifica quali carichi hanno perso repliche.
5. Segui la procedura [Verificare un nodo](guide:proc-verificare-nodo).

## Come risolvere

1. Valuta l'impatto: quali applicazioni avevano pod sul nodo e se hanno ancora repliche sane altrove.
2. Se il nodo è raggiungibile, l'amministratore di sistema controlla kubelet, runtime, disco e rete, con i comandi dell'esempio.
3. Se serve un intervento lungo, esegui **cordon** e, se il nodo risponde, **drain** da [Operazioni → Manutenzione](app:/operations/maintenance) (vedi [Manutenzione di un nodo](guide:proc-manutenzione-nodo)).
4. Dopo il ripristino, verifica che il nodo torni `Ready` ed esegui l'**uncordon**.
5. Se il nodo è definitivamente perso, l'amministratore lo rimuove dal cluster (`kubectl delete node`) solo dopo aver verificato che i pod con storage locale siano stati gestiti.

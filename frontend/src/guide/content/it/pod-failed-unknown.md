---
title: Pod Failed e Unknown
summary: Cosa significano le fasi Failed e Unknown di un pod e come comportarsi in ciascun caso.
category: troubleshooting
order: 70
keywords: failed, unknown, evicted, fase pod, job fallito, nodo irraggiungibile, terminating
related: pod, node-notready, job, oomkilled, troubleshooting, proc-diagnosticare-pod
---

## In parole semplici

Ogni pod ha una **fase** che riassume a che punto è della sua vita: `Pending`, `Running`, `Succeeded`, `Failed` o `Unknown`.

- **Failed** significa che tutti i container del pod sono terminati e almeno uno è uscito con errore, senza che Kubernetes lo riavvii. Succede tipicamente ai pod di un [Job](guide:job), ai pod sfrattati (Evicted) per mancanza di risorse sul nodo, o a pod con `restartPolicy: Never`.
- **Unknown** significa che Kubernetes non sa in che stato sia il pod, quasi sempre perché ha perso il contatto con il nodo che lo ospita.

Sono due situazioni molto diverse: Failed è un esito definitivo e noto; Unknown è un'incertezza, legata alla salute del nodo.

## Dettagli tecnici

- `status.phase: Failed` si verifica quando tutti i container sono terminati e almeno uno con exit code diverso da 0 (o è stato terminato dal sistema), e la `restartPolicy` non prevede il riavvio (`Never`, oppure `OnFailure` dopo che il Job ha esaurito `backoffLimit`).
- Un pod **Evicted** ha `phase: Failed` e `status.reason: Evicted`, con un messaggio come `The node was low on resource: memory`. I pod sfrattati restano visibili finché non vengono eliminati (o rimossi dal garbage collector dei pod terminati, soglia `terminated-pod-gc-threshold`).
- Con `restartPolicy: Always` (Deployment, StatefulSet) un pod non arriva normalmente a Failed: il container viene riavviato e si vede piuttosto [CrashLoopBackOff](guide:crashloopbackoff). Fanno eccezione gli sfratti e i pod rifiutati dal kubelet all'ammissione (ad esempio `OutOfcpu`, `NodeAffinity`).
- `status.phase: Unknown` è impostata quando lo stato non può essere ottenuto, tipicamente con il nodo in `NotReady`/`Unknown`. Il pod resta così fino a quando il nodo torna o il pod viene sfrattato dopo la toleration di 300 secondi; a quel punto può rimanere in `Terminating` perché il kubelet non può confermare l'arresto.
- Il controller di un Deployment crea comunque un nuovo pod sostitutivo; uno StatefulSet invece aspetta, per non avere due pod con la stessa identità.

## Esempio

```bash
kubectl get pods -n batch --field-selector=status.phase=Failed
# NAME                         READY   STATUS      RESTARTS   AGE
# import-28571230-7xk2p        0/1     Error       0          3h
# web-6d8f7c9b5-zt4lw          0/1     Evicted     0          1h

kubectl describe pod web-6d8f7c9b5-zt4lw -n batch | grep -E "Status|Reason|Message"
kubectl get pods -A -o wide | grep -E "Unknown|Terminating"
```

## Cosa può andare storto

- Si accumulano centinaia di pod Evicted dopo un episodio di pressione sul nodo, rendendo confuse le liste.
- Un Job fallisce ripetutamente e i suoi pod Failed contengono l'unico log utile: eliminarli troppo presto fa perdere la diagnosi.
- Si forza l'eliminazione (`--force --grace-period=0`) di un pod StatefulSet in Unknown mentre il nodo è ancora vivo ma isolato: due istanze possono scrivere sugli stessi dati.
- Si interpreta Unknown come errore dell'applicazione, mentre il problema è il nodo.

## Come verificare

1. Il [Centro Operativo](app:/operations-center) segnala i pod Failed e Unknown con la risorsa e il nodo coinvolti.
2. Apri il pod: in **Panoramica** guarda fase, motivo (`Evicted`, `Error`, `DeadlineExceeded`) e nodo.
3. Per i Failed, leggi la scheda **Log** (i log dei container terminati restano disponibili finché il pod esiste).
4. Per gli Unknown, apri il nodo in [Cluster → Nodi](app:/cluster/nodes) e verifica la condizione `Ready`.
5. Per i Job, controlla [Applicazioni → Jobs](app:/k8s/jobs): tentativi, `backoffLimit` e completamenti.

## Come risolvere

1. **Job fallito**: leggi i log, correggi la causa (dati, configurazione, credenziali) e rilancia il Job; vedi [Job](guide:job).
2. **Evicted**: individua la risorsa esaurita sul nodo (memoria, disco), imposta request e limit corretti (vedi [Resource request](guide:resource-request)), poi elimina i pod Evicted rimasti.
3. **Unknown**: tratta il problema come un nodo guasto, seguendo [Nodo NotReady](guide:node-notready). Non forzare l'eliminazione dei pod di StatefulSet finché non sei certo che il nodo sia spento o isolato definitivamente.
4. Dopo l'intervento verifica che i controller abbiano ricreato le repliche desiderate e che il Centro Operativo non mostri più il problema.

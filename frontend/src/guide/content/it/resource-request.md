---
title: Resource request
summary: Le risorse minime (CPU e RAM) che un container dichiara di aver bisogno, usate per lo scheduling.
category: reliability
order: 60
keywords: requests, resource request, cpu, memoria, ram, millicore, scheduling, qos
related: resource-limit, scheduling, pending, node, oomkilled, monitoring
---

## In parole semplici

La **request** è una prenotazione: il container dichiara "per funzionare mi servono almeno mezza CPU e 256 MiB di RAM". Kubernetes usa questa informazione per scegliere un nodo che abbia abbastanza spazio libero **prenotabile**, e garantisce al container quella quota.

Se nessun nodo ha spazio sufficiente per la prenotazione, il Pod non parte e resta in [Pending](guide:pending).

## Dettagli tecnici

- Si imposta in `resources.requests` di ogni container. Le unità:
  - CPU in core o millicore: `500m` = mezzo core, `2` = due core.
  - Memoria in byte con suffissi binari: `256Mi`, `1Gi` (attenzione: `M` e `Mi` sono diversi).
- Lo **scheduler** somma le request dei container (più l'eventuale overhead) e confronta il totale con l'**allocatable** del nodo meno le request dei Pod già presenti. Conta la prenotazione, **non** il consumo reale.
- A runtime la request CPU diventa un peso (`cpu.weight` su cgroup v2): in caso di contesa, ogni container riceve CPU in proporzione alla propria request.
- La request di memoria non limita nulla da sola, ma influenza l'ordine di espulsione quando il nodo va sotto pressione di memoria: i Pod che consumano più della request vengono espulsi per primi.
- Se imposti solo il limit, la request viene impostata uguale al limit.
- **Classi QoS**: `Guaranteed` (request = limit per CPU e memoria in tutti i container), `Burstable` (almeno una request o limit), `BestEffort` (nessuna). I BestEffort sono i primi a essere espulsi.
- Un **LimitRange** nel namespace può impostare valori di default; una **ResourceQuota** può limitare la somma delle request.
- L'HPA calcola l'utilizzo percentuale rispetto alla request: senza request l'autoscaling su CPU non funziona.

## Esempio

```yaml
containers:
  - name: api
    image: registry.example.com/shop/api:2.3.1
    resources:
      requests:
        cpu: 250m
        memory: 256Mi
      limits:
        memory: 512Mi
```

Nel wizard [Deploy](app:/operations/deploy) i passi **CPU** e **RAM** impostano questi valori.

Alternativa da shell per vedere quanto è prenotato su un nodo:

```bash
kubectl describe node worker-01 | grep -A 8 "Allocated resources"
kubectl top pod -n shop
```

## Cosa può andare storto

- **Request troppo alte**: Pod in `Pending` con evento `0/3 nodes are available: 3 Insufficient cpu`, cluster che sembra "pieno" anche con CPU reale libera.
- **Request troppo basse o assenti**: troppi Pod sullo stesso nodo, contesa di CPU, lentezza, espulsioni per pressione di memoria.
- **Quota del namespace superata**: la creazione del Pod viene rifiutata (`exceeded quota`).
- **Unità sbagliate**: `cpu: 500` significa 500 core, non 500 millicore.

## Come verificare

- In [Monitoraggio → CPU](app:/monitoring/cpu) e [Memoria](app:/monitoring/memory) confronta il consumo reale con le request (richiede metrics-server; senza, l'app mostra "Metriche avanzate non configurate").
- Nella pagina [Nodi](app:/cluster/nodes) controlla capacità, allocatable e risorse prenotate.
- La scheda **Eventi** di un Pod Pending riporta `FailedScheduling` con il motivo.

## Come risolvere

1. Misura il consumo reale per alcuni giorni e imposta la request vicino al consumo tipico.
2. Se i Pod restano Pending, riduci le request, libera risorse o aggiungi nodi.
3. Per servizi critici usa request uguali al limit di memoria per ottenere una QoS più stabile.
4. Applica le modifiche dalla scheda **YAML** del workload: cambiare le risorse avvia un [rolling update](guide:rolling-update).

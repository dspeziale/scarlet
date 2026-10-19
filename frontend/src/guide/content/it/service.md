---
title: Service
summary: Fornisce un indirizzo stabile e un bilanciamento verso un gruppo di Pod.
category: networking
order: 10
keywords: service, clusterip, nodeport, loadbalancer, headless, selector, endpoints, porta
related: networking, ingress, pod, deployment, readiness-probe, statefulset
---

## In parole semplici

I Pod nascono e muoiono, e ogni volta cambiano indirizzo IP. Un **Service** risolve il problema: offre un **nome e un indirizzo fissi** (per esempio `web.shop.svc.cluster.local`) e distribuisce il traffico tra tutti i Pod che hanno certe etichette e sono pronti a riceverlo.

Le altre applicazioni del cluster parlano con il Service, non con i singoli Pod. Così puoi scalare, aggiornare o riavviare i Pod senza che i client se ne accorgano.

## Dettagli tecnici

- `spec.selector`: le etichette dei Pod di destinazione. Il control plane mantiene gli **EndpointSlice** con gli IP dei Pod corrispondenti **e Ready**: un Pod che non supera la [readiness probe](guide:readiness-probe) viene tolto dal bilanciamento.
- `spec.ports`: `port` (porta del Service), `targetPort` (porta del container, numero o nome), `protocol` (TCP di default).
- Tipi (`spec.type`):
  - `ClusterIP` (default): IP virtuale raggiungibile solo dall'interno del cluster.
  - `NodePort`: in più apre una porta (default 30000-32767) su ogni nodo.
  - `LoadBalancer`: in più chiede un bilanciatore esterno al provider (cloud o MetalLB on-premise). Senza un provider l'`EXTERNAL-IP` resta `<pending>`.
  - `ExternalName`: alias DNS (CNAME) verso un nome esterno, senza proxy.
- **Headless** (`clusterIP: None`): niente IP virtuale; il DNS restituisce direttamente gli IP dei Pod. Usato dagli [StatefulSet](guide:statefulset).
- Il traffico verso il ClusterIP è gestito da kube-proxy (iptables/IPVS) o dal plugin di rete (es. Cilium eBPF).
- `sessionAffinity: ClientIP` mantiene lo stesso client sullo stesso Pod.

In Scarlet: [Networking → Services](app:/k8s/services) e [Networking → Endpoints](app:/k8s/endpoints) per vedere i Pod effettivamente collegati.

## Esempio

```yaml
apiVersion: v1
kind: Service
metadata:
  name: web
  namespace: shop
spec:
  type: ClusterIP
  selector:
    app: web
  ports:
    - name: http
      port: 80
      targetPort: 8080
      protocol: TCP
```

## Cosa può andare storto

- **Nessun endpoint**: il selector non corrisponde alle etichette dei Pod (errore di battitura, namespace diverso) oppure nessun Pod è Ready. È la causa più comune di "il servizio non risponde".
- **`targetPort` sbagliata**: il Service inoltra a una porta su cui il container non ascolta; il client riceve "connection refused".
- **Applicazione in ascolto solo su `127.0.0.1`** dentro il container: non è raggiungibile dal Service. Deve ascoltare su `0.0.0.0`.
- **LoadBalancer in `<pending>`**: nel cluster non c'è un'implementazione di LoadBalancer.
- **NetworkPolicy** che bloccano il traffico tra namespace.

## Come verificare

In Scarlet apri il Service e guarda la scheda Relazioni (Pod selezionati) e la pagina [Endpoints](app:/k8s/endpoints): se la lista degli indirizzi è vuota, il problema è il selector o la readiness.

```bash
kubectl -n shop get svc web -o wide
kubectl -n shop get endpointslices -l kubernetes.io/service-name=web
kubectl -n shop get pods -l app=web --show-labels
# test dall'interno del cluster
kubectl -n shop run tmp --rm -it --image=docker.io/curlimages/curl:8.10.1 --restart=Never -- curl -sv http://web/
```

## Come risolvere

1. Allinea `spec.selector` alle etichette dei Pod (scheda YAML, dry-run, applica).
2. Se i Pod non sono Ready, diagnostica la readiness: [Readiness probe](guide:readiness-probe).
3. Verifica che `targetPort` corrisponda alla porta su cui l'applicazione ascolta davvero.
4. Per l'accesso HTTP dall'esterno preferisci un [Ingress](guide:ingress) a molti NodePort.
5. Per problemi più ampi di rete o DNS vedi [Networking](guide:networking).

---
title: Ingress
summary: Pubblica servizi HTTP e HTTPS verso l'esterno tramite nomi host e percorsi.
category: networking
order: 20
keywords: ingress, ingress controller, ingressclass, tls, host, path, http, https, nginx
related: service, networking, secret, proc-pubblicare-applicazione
---

## In parole semplici

Un **Ingress** è la "porta d'ingresso" HTTP del cluster. Contiene regole del tipo: "le richieste per `shop.example.com` vanno al Service `web`, quelle per `shop.example.com/api` al Service `api`". Gestisce anche il certificato HTTPS.

Attenzione: l'Ingress è solo una **configurazione**. Per funzionare serve un **Ingress Controller** installato nel cluster (ad esempio ingress-nginx, Traefik, HAProxy) che legge queste regole e fa davvero da proxy.

## Dettagli tecnici

- `spec.ingressClassName`: quale controller deve gestire l'Ingress (corrisponde a un oggetto `IngressClass`). Se omesso, si usa l'IngressClass marcata come default, se esiste.
- `spec.rules[]`: per ogni `host`, una lista di `http.paths` con `path`, `pathType` (`Prefix`, `Exact` o `ImplementationSpecific`) e `backend.service.name` / `backend.service.port`.
- `spec.tls[]`: elenco di host e `secretName` di un [Secret](guide:secret) di tipo `kubernetes.io/tls` con `tls.crt` e `tls.key`, nello **stesso namespace** dell'Ingress.
- `spec.defaultBackend`: dove mandare le richieste che non corrispondono a nessuna regola.
- `status.loadBalancer.ingress`: l'indirizzo assegnato dal controller; se è vuoto, il controller non ha preso in carico l'oggetto.
- Funzioni avanzate (redirect, timeout, dimensione massima del body, rewrite) si configurano con **annotazioni specifiche del controller**, ad esempio `nginx.ingress.kubernetes.io/proxy-body-size`.
- L'Ingress gestisce solo HTTP/HTTPS. Per TCP/UDP generico usa un [Service](guide:service) di tipo LoadBalancer o NodePort.

In Scarlet: [Networking → Ingress](app:/k8s/ingresses).

## Esempio

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: shop
  namespace: shop
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: 10m
spec:
  ingressClassName: nginx
  tls:
    - hosts: [shop.example.com]
      secretName: shop-tls
  rules:
    - host: shop.example.com
      http:
        paths:
          - path: /api
            pathType: Prefix
            backend:
              service: { name: api, port: { number: 80 } }
          - path: /
            pathType: Prefix
            backend:
              service: { name: web, port: { number: 80 } }
```

## Cosa può andare storto

- **Nessun controller** o `ingressClassName` errato: l'Ingress esiste ma nessuno lo applica, l'indirizzo resta vuoto.
- **404 dal controller**: host o path non corrispondono (es. manca l'header Host, `pathType` sbagliato).
- **502/503 Bad Gateway**: il Service di backend non ha endpoint pronti o la porta è errata.
- **Certificato sbagliato** (il browser mostra il certificato "fake" del controller): il Secret TLS non esiste, è in un altro namespace o non contiene l'host.
- **DNS** del nome host non punta all'indirizzo del controller.

## Come verificare

In Scarlet apri l'Ingress: la scheda Relazioni mostra Service e Secret collegati, la scheda Eventi gli eventuali errori segnalati dal controller.

```bash
kubectl -n shop get ingress shop
kubectl -n shop describe ingress shop
kubectl get ingressclass
curl -vk --resolve shop.example.com:443:<IP-controller> https://shop.example.com/
```

## Come risolvere

1. Verifica che esista un IngressClass e che `ingressClassName` lo indichi.
2. Per 502/503 controlla il Service di backend e i suoi [endpoint](guide:service).
3. Per problemi TLS verifica che il Secret sia di tipo `kubernetes.io/tls`, nello stesso namespace, e che il certificato copra l'host.
4. Controlla con il DNS che l'host risolva all'IP del controller.
5. Per pubblicare un'applicazione da zero segui la procedura [Pubblicare un'applicazione](guide:proc-pubblicare-applicazione).

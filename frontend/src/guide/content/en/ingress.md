---
title: Ingress
summary: Exposes HTTP and HTTPS services to the outside through host names and paths.
category: networking
order: 20
keywords: ingress, ingress controller, ingressclass, tls, host, path, http, https, nginx
related: service, networking, secret, proc-pubblicare-applicazione
---

## In simple terms

An **Ingress** is the cluster's HTTP "front door". It holds rules such as: "requests for `shop.example.com` go to the `web` Service, those for `shop.example.com/api` go to the `api` Service". It also handles the HTTPS certificate.

Note: an Ingress is only a **configuration**. To work, it needs an **Ingress Controller** installed in the cluster (for example ingress-nginx, Traefik, HAProxy) that reads these rules and actually acts as the proxy.

## Technical details

- `spec.ingressClassName`: which controller must handle the Ingress (matches an `IngressClass` object). If omitted, the IngressClass marked as default is used, if one exists.
- `spec.rules[]`: for each `host`, a list of `http.paths` with `path`, `pathType` (`Prefix`, `Exact` or `ImplementationSpecific`) and `backend.service.name` / `backend.service.port`.
- `spec.tls[]`: list of hosts and the `secretName` of a [Secret](guide:secret) of type `kubernetes.io/tls` with `tls.crt` and `tls.key`, in the **same namespace** as the Ingress.
- `spec.defaultBackend`: where to send requests that match no rule.
- `status.loadBalancer.ingress`: the address assigned by the controller; if empty, the controller has not picked up the object.
- Advanced features (redirects, timeouts, max body size, rewrites) are configured with **controller-specific annotations**, for example `nginx.ingress.kubernetes.io/proxy-body-size`.
- Ingress handles only HTTP/HTTPS. For generic TCP/UDP use a [Service](guide:service) of type LoadBalancer or NodePort.

In Scarlet: [Networking → Ingress](app:/k8s/ingresses).

## Example

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

## What can go wrong

- **No controller** or wrong `ingressClassName`: the Ingress exists but nobody applies it, and the address stays empty.
- **404 from the controller**: host or path do not match (e.g. missing Host header, wrong `pathType`).
- **502/503 Bad Gateway**: the backend Service has no ready endpoints or the port is wrong.
- **Wrong certificate** (the browser shows the controller's "fake" certificate): the TLS Secret does not exist, is in another namespace or does not cover the host.
- **DNS** for the host name does not point to the controller's address.

## How to verify

In Scarlet open the Ingress: the Relazioni tab shows linked Services and Secrets, the Eventi tab any errors reported by the controller.

```bash
kubectl -n shop get ingress shop
kubectl -n shop describe ingress shop
kubectl get ingressclass
curl -vk --resolve shop.example.com:443:<controller-IP> https://shop.example.com/
```

## How to fix

1. Check that an IngressClass exists and that `ingressClassName` references it.
2. For 502/503 check the backend Service and its [endpoints](guide:service).
3. For TLS issues verify that the Secret is of type `kubernetes.io/tls`, in the same namespace, and that the certificate covers the host.
4. Check with DNS that the host resolves to the controller IP.
5. To publish an application from scratch follow [Publish an application](guide:proc-pubblicare-applicazione).

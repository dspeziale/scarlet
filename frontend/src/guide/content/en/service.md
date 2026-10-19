---
title: Service
summary: Provides a stable address and load balancing toward a group of Pods.
category: networking
order: 10
keywords: service, clusterip, nodeport, loadbalancer, headless, selector, endpoints, port
related: networking, ingress, pod, deployment, readiness-probe, statefulset
---

## In simple terms

Pods are born and die, and each time their IP address changes. A **Service** solves this: it offers a **fixed name and address** (for example `web.shop.svc.cluster.local`) and distributes traffic across all the Pods that have certain labels and are ready to receive it.

Other applications in the cluster talk to the Service, not to individual Pods. This way you can scale, update or restart Pods without clients noticing.

## Technical details

- `spec.selector`: the labels of the target Pods. The control plane maintains **EndpointSlices** with the IPs of the matching **and Ready** Pods: a Pod that fails its [readiness probe](guide:readiness-probe) is removed from load balancing.
- `spec.ports`: `port` (Service port), `targetPort` (container port, number or name), `protocol` (TCP by default).
- Types (`spec.type`):
  - `ClusterIP` (default): virtual IP reachable only from inside the cluster.
  - `NodePort`: additionally opens a port (default 30000-32767) on every node.
  - `LoadBalancer`: additionally requests an external load balancer from the provider (cloud, or MetalLB on-premises). Without a provider the `EXTERNAL-IP` stays `<pending>`.
  - `ExternalName`: DNS alias (CNAME) to an external name, no proxying.
- **Headless** (`clusterIP: None`): no virtual IP; DNS returns the Pod IPs directly. Used by [StatefulSets](guide:statefulset).
- Traffic to the ClusterIP is handled by kube-proxy (iptables/IPVS) or by the network plugin (e.g. Cilium eBPF).
- `sessionAffinity: ClientIP` keeps the same client on the same Pod.

In Scarlet: [Networking → Services](app:/k8s/services) and [Networking → Endpoints](app:/k8s/endpoints) to see the Pods actually attached.

## Example

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

## What can go wrong

- **No endpoints**: the selector does not match the Pod labels (typo, different namespace) or no Pod is Ready. This is the most common cause of "the service does not respond".
- **Wrong `targetPort`**: the Service forwards to a port the container does not listen on; the client gets "connection refused".
- **Application listening only on `127.0.0.1`** inside the container: it is not reachable through the Service. It must listen on `0.0.0.0`.
- **LoadBalancer `<pending>`**: there is no LoadBalancer implementation in the cluster.
- **NetworkPolicies** blocking traffic between namespaces.

## How to verify

In Scarlet open the Service and look at the Relazioni tab (selected Pods) and the [Endpoints](app:/k8s/endpoints) page: if the address list is empty, the problem is the selector or readiness.

```bash
kubectl -n shop get svc web -o wide
kubectl -n shop get endpointslices -l kubernetes.io/service-name=web
kubectl -n shop get pods -l app=web --show-labels
# test from inside the cluster
kubectl -n shop run tmp --rm -it --image=docker.io/curlimages/curl:8.10.1 --restart=Never -- curl -sv http://web/
```

## How to fix

1. Align `spec.selector` with the Pod labels (YAML tab, dry-run, apply).
2. If Pods are not Ready, diagnose readiness: [Readiness probe](guide:readiness-probe).
3. Check that `targetPort` matches the port the application actually listens on.
4. For HTTP access from outside, prefer an [Ingress](guide:ingress) over many NodePorts.
5. For broader network or DNS issues see [Networking](guide:networking).

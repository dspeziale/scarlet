---
title: Networking
summary: How Pods, Services and the outside world communicate - Pod network, DNS and endpoints.
category: networking
order: 30
keywords: network, networking, cni, dns, coredns, endpoints, endpointslice, networkpolicy, kube-proxy
related: service, ingress, pod, node, troubleshooting, cluster
---

## In simple terms

In Kubernetes **every Pod has its own IP address** and can talk to any other Pod in the cluster, on any node, without NAT. [Services](guide:service) give stable names to groups of Pods, the **internal DNS** translates those names into addresses, and [Ingresses](guide:ingress) open access from outside.

When "one application cannot reach another", the problem is almost always in one of four layers: Pod network, DNS, Service/endpoints, security rules.

## Technical details

- **Pod network (CNI)**: a CNI plugin (Calico, Cilium, Flannel, OVN-Kubernetes...) assigns IPs from the *pod CIDR* and routes traffic between nodes. It usually runs as a [DaemonSet](guide:daemonset): if it breaks on a node, that node often becomes NotReady or its Pods are left without networking.
- **Service CIDR**: Service virtual IPs come from a separate range. kube-proxy (or the CNI in eBPF mode) translates these IPs to the real Pod IPs.
- **Endpoints**: for each Service with a selector, the control plane maintains **EndpointSlice** objects (and the legacy `Endpoints` object) with the IPs of ready Pods. A non-Ready Pod ends up in `notReadyAddresses`/condition `ready: false`.
- **DNS (CoreDNS)**: resolves `<service>.<namespace>.svc.cluster.local`. Within the same namespace `<service>` is enough; from another namespace you need at least `<service>.<namespace>`. The Pod's `/etc/resolv.conf` points to the `kube-dns` Service in `kube-system` and uses `ndots:5`, so short external names cause a few extra lookups.
- **NetworkPolicy**: if a policy in a namespace selects a Pod, that Pod accepts only explicitly allowed traffic. Policies work only if the CNI supports them.
- **Node firewall**: on Oracle Linux `firewalld` can block kubelet (10250), NodePorts or CNI traffic (VXLAN 4789/UDP, BGP 179/TCP depending on the plugin).

In Scarlet: [Networking → Endpoints](app:/k8s/endpoints) shows which Pods receive traffic for each Service.

## Example

Quick DNS and connectivity test from a temporary Pod (shell alternative):

```bash
kubectl -n shop run nettest --rm -it --restart=Never \
  --image=docker.io/library/busybox:1.36 -- sh
# inside the Pod:
nslookup web
nslookup web.shop.svc.cluster.local
wget -qO- http://web:80/healthz
```

## What can go wrong

- **DNS does not answer**: CoreDNS Pods not ready, or UDP/TCP 53 traffic to them is blocked.
- **Service with no endpoints**: wrong selector or non-Ready Pods.
- **Pods cannot talk across nodes**: broken CNI, wrong MTU (typical with VXLAN/VPN: small packets pass, large ones do not), node firewall.
- **Overly strict NetworkPolicy**, for example a `deny-all` that also blocks outbound DNS.
- **Address overlap**: pod CIDR or service CIDR equal to corporate networks, with traffic routed to the wrong place.

## How to verify

1. In Scarlet check the [Endpoints](app:/k8s/endpoints) of the Service involved.
2. Check the state of the CoreDNS and CNI Pods in `kube-system` from the [Pod](app:/k8s/pods) page.
3. Look for network events in [Cluster → Eventi](app:/cluster/events).

```bash
kubectl -n kube-system get pods -l k8s-app=kube-dns
kubectl -n kube-system get pods -o wide | grep -Ei 'calico|cilium|flannel|kube-proxy'
kubectl get networkpolicy -A
```

## How to fix

1. Start from the lowest layer: if two Pods cannot reach each other by IP, the problem is the CNI or the firewall, not DNS.
2. If IPs work but names do not, check CoreDNS (logs and Pod state).
3. If the name resolves but there are no endpoints, fix the [Service](guide:service) selector or readiness.
4. Review the namespace NetworkPolicies, always allowing outbound DNS.
5. For external access see [Ingress](guide:ingress); for a general method see [Troubleshooting](guide:troubleshooting).

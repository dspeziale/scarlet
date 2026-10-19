---
title: High availability
summary: Designing applications that keep working when a Pod or a node stops.
category: reliability
order: 80
keywords: high availability, ha, poddisruptionbudget, pdb, disruption, anti-affinity, topology spread
related: replica, scheduling, node, proc-manutenzione-nodo, readiness-probe, cluster
---

## In simple terms

**High availability** means the service stays up even when something breaks or is stopped: a crashing Pod, a node shutting down, planned maintenance. You get it with three ingredients:

1. **Several copies** of the application ([replicas](guide:replica)).
2. **Spread** across different nodes, so one failure does not hit all of them.
3. **Protected** during planned operations, thanks to the PodDisruptionBudget.

## Technical details

**Disruptions**. Kubernetes distinguishes:
- *involuntary*: hardware failure, kernel panic, unreachable node, eviction due to resource shortage;
- *voluntary*: draining a node for maintenance, deleting a Pod, upgrading the cluster.

**PodDisruptionBudget (PDB)**. It defines how many replicas of a group of Pods (selected by label) must stay available during **voluntary** disruptions that go through the Eviction API, such as `kubectl drain` or the drain function of [Manutenzione](app:/operations/maintenance). You use `minAvailable` or `maxUnavailable` (number or percentage). If an eviction would violate the budget, the API answers with error 429 and the drain retries. A PDB does **not** protect against involuntary failures or direct deletion of a Pod.

**Spreading**:
- `topologySpreadConstraints` spreads Pods across nodes (`kubernetes.io/hostname`) or zones (`topology.kubernetes.io/zone`).
- `podAntiAffinity` prevents (as a hard or soft rule) two replicas from landing on the same node.

**Cluster side**: a multi-node control plane (at least 3 for etcd quorum), enough workers to absorb the loss of one node, redundant storage and ingress. When a node becomes NotReady, its Pods are evicted after about 5 minutes (default `node.kubernetes.io/unreachable` toleration of 300 seconds).

The [Monitoraggio → Alta affidabilità](app:/monitoring/ha) page helps find workloads with a single replica, replicas concentrated on one node, or no PDB.

## Example

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: web-pdb
  namespace: shop
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: web
---
# In the template of the "web" Deployment (3 replicas)
spec:
  template:
    spec:
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app: web
```

Shell alternative:

```bash
kubectl -n shop get pdb
kubectl -n shop get pods -l app=web -o wide
```

## What can go wrong

- **Drain stuck**: a PDB with `minAvailable` equal to the replica count (or `maxUnavailable: 0`) allows no eviction at all.
- **PDB on a single-replica workload**: maintenance cannot proceed without downtime.
- **All replicas on the same node**: losing that node stops the service despite the replicas.
- **`DoNotSchedule` too strict**: with few nodes, new Pods stay `Pending`.
- **Single points of failure** outside the cluster: a single database, a single NFS storage, a single load balancer.

## How to verify

- [Monitoraggio → Alta affidabilità](app:/monitoring/ha) for the overall risk picture.
- In [Pod](app:/k8s/pods) check the node column to see the distribution.
- Before maintenance, the [Manutenzione](app:/operations/maintenance) page shows which Pods would be evicted.

## How to fix

1. Bring important services to at least 2-3 replicas.
2. Add `topologySpreadConstraints` or `podAntiAffinity` to spread them.
3. Create a PDB with `maxUnavailable: 1` (or `minAvailable` lower than the replica count).
4. Perform node maintenance following [Node maintenance](guide:proc-manutenzione-nodo).

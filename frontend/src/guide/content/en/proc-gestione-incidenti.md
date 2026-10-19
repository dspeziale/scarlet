---
title: Handle an incident
summary: Operational method to handle an outage, from the first alert to closure, using the Operations Center and notifications.
category: procedures
order: 140
keywords: incident, outage, operations center, notifications, severity, critical, escalation, post-mortem
related: troubleshooting, proc-diagnosticare-pod, proc-rollback, proc-verificare-nodo, monitoring, introduzione
---

## When you need it

When a service is degraded or unavailable: users reporting errors, a `CRITICAL` or `ERROR` problem in the Operations Center, a `NotReady` node, a Deployment with no available replicas. The procedure applies the method of this guide: **Understand → Diagnose → Decide → Act → Verify**.

## Prerequisites

- **Operator** role for diagnosis and corrective actions (restart, scale, rollback, cordon/drain); **Administrator** for actions on Secrets, users and settings.
- Scarlet in **LIVE** mode (green badge with the cluster context). If you see the striped "DEMO" banner you are looking at sample data: it is not the real cluster.
- Knowing whom to contact for escalation (application owner, cluster administrator).

## Procedure

1. **Understand: assess the impact.** Open the [Operations Center](app:/operations-center). Sort by severity:
   - `CRITICAL`: service down or at immediate risk (e.g. no available replica, node NotReady);
   - `ERROR`: component broken but service partially up;
   - `WARNING`: degradation or future risk;
   - `INFO`: informational.
   Note the start time, the affected resources and the stated risk. From the Notification Center bell **mark the problem as taken in charge**, so colleagues know someone is on it.
2. **Understand: define the scope.** A single Pod, a whole Deployment, all Pods on a node, or the whole cluster? Check [Cluster → Overview](app:/cluster), [Cluster → Events](app:/cluster/events) and [Monitoring → Health](app:/monitoring/health).
3. **Diagnose: look for what changed.** Many incidents follow a change. Check the [Audit Log](app:/security/audit) (recent deploys, scales, rollouts, YAML edits) and the history in [Operations → Rollout](app:/operations/rollout).
4. **Diagnose: analyze the resource.** Follow [Diagnose a Pod](guide:proc-diagnosticare-pod) or [Verify a node](guide:proc-verificare-nodo): events, logs, diagnostics, metrics.
5. **Decide: restore first, investigate later.** Choose the least risky action that brings the service back:
   - faulty recent update → [rollback](guide:proc-rollback);
   - process stuck with no evident cause → restart from [Operations → Restart](app:/operations/restart);
   - excessive load → more replicas from [Operations → Scale](app:/operations/scale);
   - broken node → cordon and drain from [Operations → Maintenance](app:/operations/maintenance).
   Read the risks shown by the app before confirming. Avoid multiple simultaneous changes: you would not know which one worked.
6. **Act.** Perform one action at a time and note time and outcome. Every action is recorded in the Audit Log.
7. **Verify.** Check that the problem disappears from the Operations Center, that Pods and replicas are `Ready` and that the service works from the user's point of view.
8. **Escalate** if the service is not restored within the agreed time (for example 30 minutes), or if the cause is outside Scarlet (network, storage, registry, external database).
9. **Close.** Mark the problem as handled in the Notification Center and write a short report: timeline, cause, resolving action, preventive actions (probes, memory limits, replicas, PodDisruptionBudgets).

## Verification

- No open `CRITICAL` or `ERROR` problem related to the incident in the [Operations Center](app:/operations-center).
- Available replicas match the desired ones.
- The [Health](app:/monitoring/health) page is Healthy.
- The service is confirmed working by its users.
- The report is written and shared.

## If something goes wrong

- **Scarlet itself does not respond**: on the server check `systemctl status pkm` and `journalctl -u pkm`. Meanwhile you can work with `kubectl` from a shell; the cluster keeps running without Scarlet.
- **Kubernetes Unhealthy on the Health page**: Scarlet cannot reach the API server. Check network and kubeconfig, then ask the cluster administrator about the control plane status.
- **The action makes things worse**: stop, undo the last action (for example roll back the rollback, return to the previous replica count) and escalate.
- **Metrics unavailable**: without metrics-server or Prometheus Scarlet shows "Metriche avanzate non configurate" and does not estimate usage; rely on events and logs.
- **Too many alerts at once**: start from the lowest infrastructure layer (nodes, storage, network). A broken node generates dozens of cascading Pod problems.

---
title: Pod Failed and Unknown
summary: What the Failed and Unknown pod phases mean and how to deal with each case.
category: troubleshooting
order: 70
keywords: failed, unknown, evicted, pod phase, failed job, unreachable node, terminating
related: pod, node-notready, job, oomkilled, troubleshooting, proc-diagnosticare-pod
---

## In simple terms

Every pod has a **phase** that summarizes where it is in its life: `Pending`, `Running`, `Succeeded`, `Failed` or `Unknown`.

- **Failed** means all containers of the pod have terminated and at least one exited with an error, and Kubernetes will not restart it. It typically happens to the pods of a [Job](guide:job), to pods evicted because the node ran out of resources, or to pods with `restartPolicy: Never`.
- **Unknown** means Kubernetes does not know the state of the pod, almost always because it lost contact with the node hosting it.

These are very different situations: Failed is a final, known outcome; Unknown is an uncertainty tied to node health.

## Technical details

- `status.phase: Failed` occurs when all containers have terminated, at least one with a non-zero exit code (or killed by the system), and the `restartPolicy` does not allow a restart (`Never`, or `OnFailure` after the Job has exhausted its `backoffLimit`).
- An **Evicted** pod has `phase: Failed` and `status.reason: Evicted`, with a message such as `The node was low on resource: memory`. Evicted pods stay visible until deleted (or removed by the terminated-pod garbage collector, threshold `terminated-pod-gc-threshold`).
- With `restartPolicy: Always` (Deployment, StatefulSet) a pod normally does not reach Failed: the container is restarted and you rather see [CrashLoopBackOff](guide:crashloopbackoff). Exceptions are evictions and pods rejected by the kubelet at admission (for example `OutOfcpu`, `NodeAffinity`).
- `status.phase: Unknown` is set when the state cannot be obtained, typically with the node `NotReady`/`Unknown`. The pod stays like that until the node comes back or the pod is evicted after the 300-second toleration; it may then remain in `Terminating` because the kubelet cannot confirm the stop.
- A Deployment controller creates a replacement pod anyway; a StatefulSet waits, so as not to have two pods with the same identity.

## Example

```bash
kubectl get pods -n batch --field-selector=status.phase=Failed
# NAME                         READY   STATUS      RESTARTS   AGE
# import-28571230-7xk2p        0/1     Error       0          3h
# web-6d8f7c9b5-zt4lw          0/1     Evicted     0          1h

kubectl describe pod web-6d8f7c9b5-zt4lw -n batch | grep -E "Status|Reason|Message"
kubectl get pods -A -o wide | grep -E "Unknown|Terminating"
```

## What can go wrong

- Hundreds of Evicted pods accumulate after a node pressure episode, cluttering the lists.
- A Job fails repeatedly and its Failed pods hold the only useful log: deleting them too early loses the diagnosis.
- Force-deleting (`--force --grace-period=0`) a StatefulSet pod in Unknown while the node is still alive but isolated: two instances may write to the same data.
- Treating Unknown as an application error, while the problem is the node.

## How to verify

1. The [Operations Center](app:/operations-center) reports Failed and Unknown pods with the affected resource and node.
2. Open the pod: in **Panoramica** check phase, reason (`Evicted`, `Error`, `DeadlineExceeded`) and node.
3. For Failed pods, read the **Log** tab (logs of terminated containers remain available as long as the pod exists).
4. For Unknown pods, open the node in [Cluster → Nodi](app:/cluster/nodes) and check the `Ready` condition.
5. For Jobs, check [Applicazioni → Jobs](app:/k8s/jobs): attempts, `backoffLimit` and completions.

## How to fix

1. **Failed Job**: read the logs, fix the cause (data, configuration, credentials) and rerun the Job; see [Job](guide:job).
2. **Evicted**: identify the exhausted resource on the node (memory, disk), set correct requests and limits (see [Resource request](guide:resource-request)), then delete the remaining Evicted pods.
3. **Unknown**: treat it as a failed node, following [Node NotReady](guide:node-notready). Do not force-delete StatefulSet pods until you are sure the node is powered off or permanently isolated.
4. After the intervention check that the controllers recreated the desired replicas and that the Operations Center no longer shows the problem.

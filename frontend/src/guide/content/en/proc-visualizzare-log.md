---
title: Viewing logs
summary: Read, filter, follow live and download container logs to understand what an application is doing.
category: procedures
order: 70
keywords: log, logs, streaming, tail, previous, container, diagnostics, download
related: pod, container, proc-diagnosticare-pod, crashloopbackoff, troubleshooting
---

## When you need it

- An application returns errors or behaves unexpectedly.
- A Pod is in **CrashLoopBackOff** and you need to understand why the process exits.
- You want to follow the startup of a new version live after a deploy.

## Prerequisites

- **Operator** or **Administrator** role (the Viewer role has no access to logs).
- Kubernetes logs only contain what the process writes to **stdout/stderr**. If the application writes to files inside the container, you will not see them here.
- Kubernetes keeps the logs of the current container and at most of the **previous** one (after a restart). Logs of deleted Pods are gone unless you have a centralized log collection system.

## Procedure

1. Open [Monitoraggio → Log](app:/monitoring/logs), or the **Log** tab on a Pod's detail page.
2. Choose **Pod** and **container**. If the Pod has several containers (sidecars, init containers), picking the right one is essential.
3. Set how many lines to read (**tail**, max 5000 per request) and optionally since when (**since**, e.g. last 15 minutes). Enable **timestamps** to correlate logs with events.
4. For a restarting container, read the logs of the **previous** instance: that is where you find the message the process exited with.
5. To follow live, start **streaming**. You can **pause** and resume it. Streaming stops automatically after 30 minutes or 20,000 lines, to avoid overloading the browser and the API server: restart it if needed.
6. Use **search/filter** to isolate the useful lines (`ERROR`, `Exception`, a request ID).
7. If you need to attach the logs to a ticket or pass them to a developer, use **download**. Check they contain no sensitive data before sharing.

Shell equivalent:

```bash
kubectl -n production logs orders-api-7d9f8b6c4-x2k1p -c app --tail=200 --timestamps
kubectl -n production logs orders-api-7d9f8b6c4-x2k1p -c app --previous
kubectl -n production logs -f deployment/orders-api --since=10m
```

For a Podman container (outside Kubernetes):

```bash
sudo podman logs --tail 200 -t container-name
```

## Verification

- You see lines with timestamps consistent with the time of the event you are investigating.
- You have found the error message and its first occurrence: write it down, you will need it for diagnosis and for any incident report.

## If something goes wrong

- **No logs**: the container may never have started (e.g. ImagePullBackOff or CreateContainerConfigError). In that case look at the **Eventi** tab, not the logs. See [Diagnosing a Pod](guide:proc-diagnosticare-pod).
- **`previous terminated container not found`**: the container never restarted, or the Pod was recreated with a new name.
- **Truncated logs**: you hit the line limit; narrow down with **since** or make several requests.
- **Streaming stops**: 30 minutes/20,000 lines limit, or the Pod was recreated; restart streaming on the new Pod.
- **Access denied**: your role does not include reading logs; ask an Administrator.

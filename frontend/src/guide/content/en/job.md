---
title: Job
summary: Runs a task to completion, retrying it on failure up to a limit.
category: workloads
order: 50
keywords: job, batch, completions, parallelism, backoffLimit, migration, ttl
related: cronjob, pod, pod-failed-unknown, resource-limit, troubleshooting
---

## In simple terms

A **Job** is for work that **has an end**: a database migration, a file import, a nightly report, a cleanup. Kubernetes starts one or more Pods, waits for them to finish successfully and then marks the Job as **complete**.

Unlike a [Deployment](guide:deployment), a Job Pod that finishes correctly is **not restarted**. If it fails, instead, the Job retries a certain number of times.

## Technical details

- `spec.completions`: how many successful completions are needed (default 1).
- `spec.parallelism`: how many Pods may run at the same time (default 1).
- `spec.backoffLimit`: number of failed attempts before the Job is declared failed (default 6). There is an exponential delay between attempts (10s, 20s, 40s... capped at 6 minutes).
- `spec.activeDeadlineSeconds`: maximum total time; when exceeded, Pods are terminated and the Job fails with reason `DeadlineExceeded`.
- `spec.ttlSecondsAfterFinished`: automatically deletes the Job (and its Pods) after it ends, useful to avoid piling up objects.
- `spec.template.spec.restartPolicy` must be `Never` or `OnFailure` (`Always` is not allowed). With `OnFailure` the container is restarted inside the same Pod; with `Never` a new Pod is created for each attempt, and failed Pods remain available to read their logs.
- `spec.completionMode: Indexed` gives each Pod an index (`JOB_COMPLETION_INDEX`) to split the work.
- A Job's template is immutable: to change it you create a new Job.

Status is in `status.succeeded`, `status.failed`, `status.active` and in the `Complete` or `Failed` conditions. In Scarlet: [Applicazioni → Jobs](app:/k8s/jobs).

## Example

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migrate-1-4-2
  namespace: shop
spec:
  backoffLimit: 3
  activeDeadlineSeconds: 900
  ttlSecondsAfterFinished: 86400
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: registry.example.com/shop/web:1.4.2
          command: ["python", "manage.py", "migrate"]
          envFrom:
            - secretRef: { name: db-credentials }
          resources:
            requests: { cpu: 100m, memory: 256Mi }
            limits: { memory: 512Mi }
```

## What can go wrong

- **BackoffLimitExceeded**: the program exits with a non-zero code on every attempt. The Job ends up `Failed`.
- **DeadlineExceeded**: the work takes longer than `activeDeadlineSeconds`.
- **OOMKilled**: the Pod exceeds its memory limit; see [OOMKilled](guide:oomkilled).
- **Pods in Pending** due to insufficient resources: the Job stays "active" without doing anything.
- **Work executed twice**: in rare cases (lost node, retries) a Job may start the work more than once. The code must be **idempotent**.
- **Old Jobs piling up** without `ttlSecondsAfterFinished`.

## How to verify

In Scarlet open the Job: you see successful/failed completions, the generated Pods (Relazioni tab) and the logs of the last attempt in the Pod's Log tab.

```bash
kubectl -n shop get job db-migrate-1-4-2
kubectl -n shop describe job db-migrate-1-4-2
kubectl -n shop logs job/db-migrate-1-4-2
kubectl -n shop get pods -l job-name=db-migrate-1-4-2
```

## How to fix

1. Read the logs of the failed Pod: the exit code and the last application error are the first useful information.
2. For `DeadlineExceeded` decide whether to increase the time or whether the work is stuck (database connection, locks).
3. For OOMKilled increase the memory limit in the manifest.
4. Fix the cause, delete the failed Job and create a new one (the template cannot be changed).
5. Set `ttlSecondsAfterFinished` for automatic cleanup.

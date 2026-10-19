---
title: CronJob
summary: Creates Jobs on a schedule, like Linux cron.
category: workloads
order: 60
keywords: cronjob, cron, schedule, scheduling, concurrencyPolicy, suspend, timezone
related: job, pod, backup, troubleshooting
---

## In simple terms

A **CronJob** is a scheduled [Job](guide:job): "run the cleanup every night at 2:00", "sync the data every 15 minutes". At the scheduled time Kubernetes creates a new Job, which in turn creates the Pod that does the work.

The schedule syntax is the classic Linux cron one, so anyone who knows `crontab` feels at home.

## Technical details

- `spec.schedule`: five-field cron expression (`minute hour day-of-month month day-of-week`), for example `0 2 * * *`. Macros such as `@daily` or `@hourly` are accepted too.
- `spec.timeZone`: IANA time zone (e.g. `Europe/Rome`). If absent, the kube-controller-manager's time zone is used, often UTC: beware of daylight saving time.
- `spec.concurrencyPolicy`: `Allow` (default, runs may overlap), `Forbid` (skips the run if the previous one is still running), `Replace` (terminates the previous one and starts the new one).
- `spec.startingDeadlineSeconds`: how long after the scheduled time a missed run may still start. If the controller counts more than 100 missed runs without this field, it stops scheduling and logs an error.
- `spec.suspend: true`: suspends future runs without deleting the CronJob.
- `spec.successfulJobsHistoryLimit` (default 3) and `spec.failedJobsHistoryLimit` (default 1): how many finished Jobs to keep.
- `spec.jobTemplate`: the Job template, with all the fields described in [Job](guide:job).

Status shows `lastScheduleTime`, `lastSuccessfulTime` and active Jobs. In PKM: [Applicazioni → CronJobs](app:/k8s/cronjobs).

## Example

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: cleanup-sessions
  namespace: shop
spec:
  schedule: "0 2 * * *"
  timeZone: Europe/Rome
  concurrencyPolicy: Forbid
  startingDeadlineSeconds: 600
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 2
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: cleanup
              image: registry.example.com/shop/tools:2.1.0
              args: ["cleanup", "--older-than", "7d"]
```

## What can go wrong

- **Never runs**: wrong cron expression, suspended CronJob, or a time zone different from what you think.
- **Overlapping runs** with `Allow`, which load the system or corrupt data.
- **Skipped runs** with `Forbid` if the work lasts longer than the interval.
- **Repeatedly failing Jobs**: the CronJob keeps creating new ones at every scheduled time; the problem is in the Job, not in the schedule.
- **"Too many missed start times"**: the controller missed too many runs (for example after a cluster outage) and stops scheduling until you set `startingDeadlineSeconds`.

## How to verify

In PKM open the CronJob: check schedule, time zone, suspension state, last run and recent Jobs in the Relazioni tab. The Eventi tab reports scheduling errors.

```bash
kubectl -n shop get cronjob cleanup-sessions
kubectl -n shop get jobs --sort-by=.metadata.creationTimestamp
kubectl -n shop describe cronjob cleanup-sessions
```

## How to fix

1. Check the cron expression and set `timeZone` explicitly.
2. To test the work immediately without waiting for the schedule, an administrator can create a manual Job from the CronJob: `kubectl -n shop create job --from=cronjob/cleanup-sessions manual-test`.
3. If the Job fails, follow the [Job](guide:job) article and read the Pod logs.
4. Choose `Forbid` for work that must not overlap.
5. To temporarily stop runs set `suspend: true` from the YAML tab.

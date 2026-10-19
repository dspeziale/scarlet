---
title: Publishing a new application
summary: Use the Deploy wizard to create a Deployment with Service, resources and health checks, reviewing the YAML before applying it.
category: procedures
order: 50
keywords: deploy, wizard, publish, application, deployment, service, image, health check
related: deployment, service, ingress, resource-request, readiness-probe, proc-rollback
---

## When you need it

When you need to run a new application in the cluster, starting from a container image already published to a registry. To update an existing application to a new version, use the [Rollout](app:/operations/rollout) page or edit the Deployment YAML instead.

## Prerequisites

- **Operator** or **Administrator** role.
- The image exists in the registry and the cluster can pull it (a private registry requires an `imagePullSecret` in the namespace).
- The target namespace exists ([Namespace](app:/cluster/namespaces)).
- You know from the application: listening port, approximate CPU and RAM needs, a health endpoint (e.g. `/healthz`) and whether it needs persistent data.

## Procedure

Recommended: start from [Operazioni → Onboarding immagine](app:/operations/onboarding) (Image onboarding). The wizard verifies the image on the registry (tag existence, credentials, linux/amd64 architecture), shows what it contains (exposed ports, user, variables, volumes) and its risks (`latest` tag, running as root…), suggests name, replicas, port, storage and health checks, and **Continua nel wizard di deploy** opens the deploy wizard already filled in.

Alternatively open [Operazioni → Deploy](app:/operations/deploy) directly and fill in the wizard steps:

1. **Nome**: lowercase letters, digits and hyphens (e.g. `orders-api`); also choose the namespace.
2. **Immagine**: e.g. `registry.example.com/team/orders-api`.
3. **Tag**: use a precise version (`1.4.2`), **not** `latest`: with `latest` you do not know what is running and rollback is unreliable.
4. **Repliche**: at least `2` for a service that must stay available during updates and maintenance.
5. **Porta**: the port the container listens on (e.g. `8080`).
6. **CPU**: request (e.g. `100m`) and optional limit. The request is used by the scheduler to pick a node.
7. **RAM**: request and limit (e.g. `256Mi` / `512Mi`). If the process exceeds the limit it is killed (OOMKilled).
8. **Storage**: only if persistent data is needed; it creates a PVC with the chosen StorageClass.
9. **Networking**: create the Service (typically `ClusterIP`) and optionally an Ingress with host and path.
10. **Health check**: configure the readiness probe (when the Pod may receive traffic) and the liveness probe (when it must be restarted). Give the liveness probe an initial delay suited to startup time.
11. **Riepilogo**: read the **generated YAML**, the result of the **cluster validation** (dry-run) and the **risks** reported (e.g. a single replica, no memory limit, `latest` tag, no probes). Go back and fix if needed.
12. **Deploy**: confirm. The operation is recorded in the Audit Log.

Shell equivalent for an administrator (after saving the summary YAML to a file):

```bash
kubectl apply --dry-run=server -f orders-api.yaml   # server-side validation
kubectl apply -f orders-api.yaml
kubectl -n production rollout status deployment/orders-api
```

## Verification

- In [Deployments](app:/k8s/deployments) the new Deployment shows ready replicas equal to desired (e.g. `2/2`).
- The Deployment's **Eventi** tab shows no Warnings.
- Pods are **Running** and **Ready**; in the **Log** tab the application started correctly.
- In [Endpoints](app:/k8s/endpoints) the Service has addresses: the readiness probe passes and the selector matches the Pods.
- If you created an Ingress, the URL responds.

## If something goes wrong

- **ImagePullBackOff / ErrImagePull**: wrong image name, tag or registry credentials. See [ImagePullBackOff](guide:imagepullbackoff).
- **Pending**: requested resources too high or PVC not bound. See [Pending](guide:pending).
- **CrashLoopBackOff**: the application exits immediately; read the previous container's logs. See [CrashLoopBackOff](guide:crashloopbackoff).
- **CreateContainerConfigError**: a referenced ConfigMap or Secret is missing. See [CreateContainerConfigError](guide:createcontainerconfigerror).
- **Running but never Ready**: the readiness probe fails (wrong path or port).
- **The Service has no endpoints**: the Service selector does not match the Pod labels.
- If the deploy was an update and makes things worse, consider a [rollback](guide:proc-rollback) right away.

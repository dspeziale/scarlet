# Runtime: Kubernetes

SCARLET treats a Kubernetes cluster as a target host record with `runtime_type=KUBERNETES`,
a `kubernetes_namespace` and an optional `kubernetes_context`. The SSH host is still used to keep
the release directory layout (`/opt/scarlet/applications/<app>/releases/<version>`) so version
history and rollback behave like the other runtimes.

## Access modes

| Mode | When | How |
|---|---|---|
| **kubectl over SSH** (default) | the target host has `kubectl` configured for the cluster (e.g. a bastion/management node) | `kubectl [--context …] apply -n <ns> -f <release>/kubernetes/`, `rollout status`, `scale`, `logs`, `delete -l scarlet.io/application=<app>` |
| **API mode** | a `KUBECONFIG` credential is attached to the host (Security → Credentials, type kubeconfig) | the official Python client applies the YAML documents read from the package (extracted locally in a temporary directory), reads Deployments, scales, patches restart annotations, reads pod logs |

The kubeconfig is stored encrypted like any other credential and decrypted only in the worker's
memory. Service-account tokens can be embedded in the kubeconfig (`users[].user.token`).

## RBAC needed by the SCARLET identity

Namespace-scoped Role with `get/list/watch/create/update/patch/delete` on `deployments`
(apps), `services`, `configmaps`, `secrets`, `pods` (get/list) and `pods/log` (get); `namespaces`
get/create if the package ships a Namespace object. No cluster-admin.

## Supported objects

`Namespace`, `Deployment`, `Service`, `ConfigMap`, `Secret` from `kubernetes.manifests`. Other
kinds are rejected in API mode (kubectl mode applies whatever the directory contains; keep it to the
same kinds). Helm charts are validated for presence only in v1.

## Labels and versioning

SCARLET labels the Deployment (and pod template) with `scarlet.io/application=<app>` and
`scarlet.io/version=<version>`; status/drift read them back. Images must be pinned per release.

## Operations mapping

| Operation | Behaviour |
|---|---|
| install | apply manifests to the namespace |
| start | scale to `deployment.replicas` (≥1), wait for rollout (`deployment.start_timeout`) |
| stop | scale to 0 |
| restart | rollout restart (annotation patch) and wait |
| scale | set replicas (UI/API `SCALE`) |
| status | readyReplicas vs replicas → RUNNING/STARTING/STOPPED/FAILED |
| logs | pod logs for `scarlet.io/application` pods (API) or `kubectl logs deployment/<name>` |
| health | `kubernetes_status`: readyReplicas ≥ replicas (or http/tcp probes from the host) |
| rollback | re-apply previous release manifests, scale, wait |
| remove | delete labelled Deployment/Service/ConfigMap/Secret |

## Secrets

Do not put clear-text Secret manifests in packages. Use SCARLET configuration entries for
environment values consumed by hooks, or an external secret manager (External Secrets, Vault CSI).
Kubernetes Secret objects in a package are applied as-is (base64 is not encryption).

## Example

`examples/kubernetes-app` — Deployment + Service + ConfigMap in namespace `inventory`.

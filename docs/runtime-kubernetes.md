# Runtime: Kubernetes

A Kubernetes target is a host record with `runtime_type=KUBERNETES`, a `kubernetes_namespace`
and an optional `kubernetes_context`. How SCARLET reaches it depends on one thing only: whether
the record carries a `KUBECONFIG` credential.

## Access modes

| | **API mode** (recommended) | **kubectl over SSH** |
|---|---|---|
| Trigger | a `KUBECONFIG` credential is attached to the target | no kubeconfig on the target |
| Reaches the cluster | directly from the SCARLET worker, with the official client | by running `kubectl` on a host over SSH |
| Needs SSH | **no** — no session, no SSH credential, no host key to approve | yes, like any other host |
| Needs a release directory | no | yes, the usual `/opt/scarlet/applications/<app>/…` layout |
| Ports to open | 6443/tcp (or the cluster API port) from SCARLET | 22/tcp from SCARLET to the host |
| Good for | a cluster with no management node, or when you do not want shells on one | an existing bastion that already has `kubectl` configured |

`host.access_mode` reports `API` or `SSH`, and `host.is_cluster_managed` is the predicate the
code uses. In API mode every service goes through `app.runtimes.access.open_target`, which
returns a `ClusterExecutor`: it satisfies the executor interface and refuses every command, so
a code path that still assumes a shell fails loudly instead of half-working.

The kubeconfig is stored encrypted like any other credential and decrypted only in the worker's
memory, for the duration of the operation. Service-account tokens can be embedded in it
(`users[].user.token`).

## Registering a cluster target

1. **Hosts → New host**: pick `KUBERNETES` as the runtime, set the namespace and, if the
   kubeconfig has several contexts, the context. The SSH fields stop being mandatory; the
   hostname is only a label for the API endpoint.
2. **Security → Credentials**: add a credential of type `kubeconfig` to that target.
3. **Test connection**: SCARLET calls the version endpoint and records the cluster version.
4. **Discover**: reports the cluster version, whether the namespace exists, and whether the
   credential may create Deployments and Secrets.

There is no host key to approve and no package to install on any machine.

## The plan for a cluster target

A cluster has no filesystem SCARLET owns, so the plan drops the steps that manipulate one:

```
validate › preflight › configure › install › start › health › finalize
```

`prepare`, `transfer`, `verify`, `extract`, `activate` and `cleanup` are not planned, and neither
are package hooks: there is no host to run a shell script on. The package is read from the
locally extracted artifact and the objects go straight to the cluster API. The deployment status
moves `VALIDATING › VALIDATED › PREFLIGHT › INSTALLING › INSTALLED › STARTING › STARTED ›
HEALTH_CHECKING › SUCCESS`.

## Pre-flight

The machine-level checks (disk, memory, ports, base path, SSH) do not apply. A cluster target is
checked on what actually matters:

| Check | Meaning |
|---|---|
| `access` | the target is reached through the API, not SSH |
| `cluster` | the API answers, and with which version |
| `namespace` | the namespace exists, or will be created at install time |
| `permissions` | `SelfSubjectAccessReview` for create/patch on deployments and create on secrets |
| `objects` | the package declares `kubernetes.manifests` |

## What SCARLET owns in the rendered objects

Whatever the package contains, three things are set by SCARLET before applying:

* **Labels**: every object gets `scarlet.io/application` and `app.kubernetes.io/managed-by=scarlet`;
  workloads and their pod template also get `scarlet.io/version`. Status, drift and removal all
  work from these labels.
* **Image**: when the release manifest declares `image.name`/`image.tag`, the container named in
  `kubernetes.container_name` (or the first one) gets that image. The released version is the one
  that runs, whatever the YAML says.
* **Configuration**: the environment and the secrets configured in SCARLET are published as a
  Secret named `<application>-scarlet-env` in the namespace, and wired into the container with
  `envFrom.secretRef`. Values are never logged; only key names are.

## Supported object kinds

`Namespace` plus, inside the namespace: `ConfigMap`, `CronJob`, `DaemonSet`, `Deployment`,
`HorizontalPodAutoscaler`, `Ingress`, `Job`, `NetworkPolicy`, `PersistentVolumeClaim`,
`PodDisruptionBudget`, `Role`, `RoleBinding`, `Secret`, `Service`, `ServiceAccount`,
`StatefulSet`.

Anything else is refused with a message naming the kind. Cluster-scoped RBAC
(`ClusterRole`, `ClusterRoleBinding`) and CRDs are deliberately outside what a release package
may install: granting them belongs to the platform team, not to an application release.

Objects are applied through the dynamic client, so a new supported kind needs no per-kind code.

## RBAC needed by the SCARLET identity

A namespace-scoped Role with `get/list/watch/create/update/patch/delete` on the kinds above,
`get/list` on `pods` and `get` on `pods/log`, plus `get/list` on `events` so failed rollouts can
be explained. Add `get/create` on `namespaces` (cluster-scoped) only if SCARLET should create the
namespace. No cluster-admin.

## Operations mapping

| Operation | Behaviour |
|---|---|
| install | apply every object of the release into the namespace, creating it when missing |
| start | scale to `deployment.replicas` (≥1) and wait for the rollout (`deployment.start_timeout`) |
| stop | scale to 0 |
| restart | patch the `restartedAt` annotation and wait for the rollout |
| scale | set replicas (UI and API `SCALE`) |
| status | `readyReplicas` against `replicas` → RUNNING / STARTING / STOPPED / FAILED, plus pods |
| logs | pod logs for the labelled pods (API) or `kubectl logs deployment/<name>` |
| health | `kubernetes_status`: ready replicas satisfied; the message carries the first cluster event when not |
| rollback | re-apply the previous release, scale, wait |
| remove | delete every labelled object, in dependency order |

When a rollout fails, the error carries the recent cluster events and the pod list: in practice
that is what tells you it was an image pull, a missing secret or a failing readiness probe.

## Drift

The reconciler reads the Deployment and compares it with the desired state, exactly as it does
for containers. Scaling a Deployment to zero by hand shows up as `STATE` or `UNEXPECTED_STOP`
drift on the application page; a different `scarlet.io/version` label shows up as `VERSION` drift.
Automatic remediation stays limited to non-production environments.

## Secrets

Do not ship clear-text Secret manifests in packages: base64 is not encryption. Put the values in
SCARLET configuration entries (type SECRET) and let SCARLET publish them as the
`<application>-scarlet-env` Secret, or use an external secret manager (External Secrets, Vault
CSI) referenced from the package.

## Testing without a cluster

`tests/fixtures/fake_k8s.py` implements the `KubernetesApi` port in memory. Registering it with
`install_fake_cluster(app)` makes the whole cluster path run in the test suite, including failed
rollouts (`cluster.break_image(...)`), denied permissions (`cluster.denied`) and an unreachable
API (`cluster.reachable = False`). See `tests/integration/test_kubernetes.py`.

## Example

`examples/kubernetes-app` — Deployment, Service and ConfigMap in namespace `inventory`.

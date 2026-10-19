---
title: CreateContainerConfigError
summary: Kubernetes cannot prepare the container configuration, almost always because of a missing ConfigMap or Secret.
category: troubleshooting
order: 80
keywords: createcontainerconfigerror, missing configmap, missing secret, missing key, env, envfrom, runasnonroot
related: configmap, secret, troubleshooting, proc-diagnosticare-pod, container, deployment
---

## In simple terms

Before starting a container, the kubelet prepares its configuration: environment variables, mounted files, the user that runs the process. If a piece of this configuration cannot be found, for example a [ConfigMap](guide:configmap) or [Secret](guide:secret) that does not exist, or a specific key that is missing, the container cannot be created and stays in **CreateContainerConfigError**.

The container never started, so **there are no logs**: the explanation is in the pod events. The good news is that as soon as the missing resource is created, Kubernetes retries on its own.

## Technical details

- The state is `state.waiting.reason: CreateContainerConfigError` and the message gives the cause. Typical examples:
  - `configmap "app-config" not found`
  - `secret "db-credentials" not found`
  - `couldn't find key DB_PASSWORD in Secret shop/db-credentials`
  - `container has runAsNonRoot and image will run as root`
- It concerns references used by `env[].valueFrom.configMapKeyRef`, `env[].valueFrom.secretKeyRef` and `envFrom`. If the reference has `optional: true`, its absence does not block the start.
- Volumes from missing ConfigMaps/Secrets produce a mount error instead (`FailedMount`, `MountVolume.SetUp failed`) and the pod stays in `ContainerCreating`: the symptom differs but the cause is similar.
- ConfigMaps and Secrets are **namespaced** resources: a pod can only reference those in its own namespace.
- A similar error, `CreateContainerError`, is produced by the runtime instead (for example a duplicate container name or a command problem) and requires reading the specific message.

## Example

```bash
kubectl get pod api-7f9c6d8b5-p4jkd -n shop
# NAME                    READY   STATUS                       RESTARTS   AGE
# api-7f9c6d8b5-p4jkd     0/1     CreateContainerConfigError   0          2m

kubectl describe pod api-7f9c6d8b5-p4jkd -n shop | grep -i error
#  Warning  Failed  kubelet  Error: secret "db-credentials" not found

kubectl get secret db-credentials -n shop
```

```yaml
env:
  - name: DB_PASSWORD
    valueFrom:
      secretKeyRef:
        name: db-credentials
        key: password
```

## What can go wrong

- The Secret exists but in another namespace (for example created in `default`).
- The key name does not match (`DB_PASSWORD` instead of `password`): Kubernetes is case-sensitive.
- The application was deployed before the ConfigMap and Secret were created.
- A Secret was deleted or renamed during a cleanup: existing pods keep working, but the first restart fails.
- The image runs as root while the `securityContext` requires `runAsNonRoot: true`.

## How to verify

1. In the [Operations Center](app:/operations-center) and on the [Pod](app:/k8s/pods) page the pod appears with status CreateContainerConfigError.
2. Open the pod: the **Eventi** tab shows the exact message with the name of the missing resource or key.
3. The **Relazioni** tab shows the ConfigMaps and Secrets referenced by the pod and which ones are missing.
4. Check that the resource exists in [Configurazione → ConfigMaps](app:/k8s/configmaps) or [Configurazione → Secrets](app:/k8s/secrets) in the correct namespace. Secret values are hidden: you do not need to reveal them to check key names.

## How to fix

1. **Missing resource**: create the ConfigMap or Secret in the pod's namespace. Secrets require a role with the appropriate permissions.
2. **Missing key**: add the key to the resource or fix the key name in the Deployment **YAML** tab, validating with the dry-run.
3. **Optional reference**: if the variable is not essential, set `optional: true`.
4. **runAsNonRoot**: use an image that runs as a non-root user, or set `runAsUser` to a non-zero UID.
5. The kubelet retries automatically; check that the pod becomes `Running` and `Ready`. If the service must be restored urgently after a release, consider a [rollback](guide:proc-rollback).

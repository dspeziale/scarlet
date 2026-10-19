---
title: ConfigMap
summary: Holds non-confidential configuration passed to applications as variables or files.
category: config
order: 10
keywords: configmap, configuration, environment variables, envFrom, configuration file, immutable
related: secret, volume, pod, deployment, createcontainerconfigerror
---

## In simple terms

A **ConfigMap** separates configuration from the container image. Instead of rebuilding the image to change a service URL or the log level, you put these values in a ConfigMap and the application reads them as **environment variables** or as **files**.

ConfigMaps are meant for **non-confidential** data. Passwords, tokens and keys belong in a [Secret](guide:secret).

## Technical details

- `data`: text key/value pairs; `binaryData`: base64 binary values. Maximum total size 1 MiB.
- Ways to use it in a Pod:
  - `env[].valueFrom.configMapKeyRef`: a single key as a variable.
  - `envFrom[].configMapRef`: all keys as variables.
  - `configMap` volume: each key becomes a file in the mount directory.
- **Updates**: environment variables are read **only at container startup**; to apply a change the Pods must be restarted (in Scarlet: [Operazioni → Restart](app:/operations/restart), equivalent to `kubectl rollout restart`). Files mounted from a volume update by themselves after some tens of seconds, but not when mounted with `subPath`, and the application must re-read them.
- `optional: true` lets the Pod start even if the ConfigMap or key does not exist.
- `immutable: true`: prevents changes and reduces load on the API server; to change values you create a new ConfigMap with a different name.
- It is namespaced: a Pod can only use ConfigMaps from its own namespace.

In Scarlet: [Configurazione → ConfigMaps](app:/k8s/configmaps). The Relazioni tab shows which Pods and workloads use it.

## Example

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: web-config
  namespace: shop
data:
  LOG_LEVEL: info
  API_URL: http://api.shop.svc.cluster.local
  app.properties: |
    cache.ttl=300
    feature.newCheckout=true
---
# usage in the container (excerpt)
# envFrom:
#   - configMapRef: { name: web-config }
```

## What can go wrong

- **[CreateContainerConfigError](guide:createcontainerconfigerror)**: the Pod references a ConfigMap or key that does not exist.
- **Pod stuck in ContainerCreating**: the `configMap` volume cannot be mounted because the object is missing.
- **Change with no effect**: you updated the ConfigMap but Pods still use the old values because they were not restarted.
- **Confidential data in clear text**: passwords mistakenly placed in a ConfigMap, visible to anyone who can read the namespace.
- **Format error** in a configuration file: the application goes into [CrashLoopBackOff](guide:crashloopbackoff) on restart.

## How to verify

In Scarlet open the ConfigMap to see keys and values and, in the Relazioni tab, the Pods that use it.

```bash
kubectl -n shop get configmap web-config -o yaml
kubectl -n shop describe pod <pod> | grep -A3 -i configmap
kubectl -n shop exec <pod> -- printenv LOG_LEVEL
```

## How to fix

1. Create the missing ConfigMap or fix the name/key in the workload.
2. After a change, restart the workload from the [Restart](app:/operations/restart) page so variables are re-read.
3. Validate changes in the YAML tab with the dry-run and review the diff before applying.
4. Immediately move any confidential data into a [Secret](guide:secret) and rotate the exposed credentials.

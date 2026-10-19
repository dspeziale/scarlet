---
title: Secret
summary: Stores confidential data such as passwords, tokens and certificates for applications.
category: config
order: 20
keywords: secret, password, token, certificate, tls, dockerconfigjson, base64, encryption
related: configmap, volume, ingress, imagepullbackoff, createcontainerconfigerror
---

## In simple terms

A **Secret** works like a [ConfigMap](guide:configmap), but is meant for **confidential** information: database passwords, API keys, TLS certificates, credentials to pull images from a private registry.

In PKM Secret values are **hidden by default**. Only a user with the **Administrator** role can reveal them, and every reveal is recorded in the [Audit Log](app:/security/audit). The Viewer role never sees the values.

## Technical details

- Values in `data` are **base64**-encoded: that is an encoding, **not encryption**. Anyone who can read the Secret through the API can decode it. `stringData` lets you write values in clear text in the manifest; the API server converts them into `data`.
- Real protection depends on: RBAC permissions (who can `get`/`list` secrets), encryption at rest in etcd (`EncryptionConfiguration` on the API server), and the fact that anyone who can create Pods in a namespace can mount every Secret in that namespace.
- Main types:
  - `Opaque`: generic.
  - `kubernetes.io/tls`: keys `tls.crt` and `tls.key`, used by [Ingresses](guide:ingress).
  - `kubernetes.io/dockerconfigjson`: registry credentials, referenced in `spec.imagePullSecrets` of the Pod or ServiceAccount.
  - `kubernetes.io/service-account-token`: legacy ServiceAccount token.
- Usage in a Pod: `env[].valueFrom.secretKeyRef`, `envFrom[].secretRef` or a `secret` volume (mounted on tmpfs, so not written to the node disk).
- Same update rules as ConfigMaps: variables require a restart, volumes update (except with `subPath`). 1 MiB limit; supports `immutable: true`.

In PKM: [Configurazione → Secrets](app:/k8s/secrets).

## Example

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: db-credentials
  namespace: shop
type: Opaque
stringData:
  DB_USER: shop
  DB_PASSWORD: change-me-now
```

Credentials for a private registry (shell alternative):

```bash
kubectl -n shop create secret docker-registry regcred \
  --docker-server=registry.example.com \
  --docker-username=deploy --docker-password='***'
```

## What can go wrong

- **[CreateContainerConfigError](guide:createcontainerconfigerror)**: the Pod uses a non-existent Secret or key.
- **[ImagePullBackOff](guide:imagepullbackoff)** with "unauthorized": the `imagePullSecret` is missing or the credentials expired.
- **TLS certificate not applied** by the Ingress: Secret in another namespace or of the wrong type.
- **Credential leak**: Secrets stored in clear text in Git repositories, printed in application logs or copied into ConfigMaps.
- **Incomplete rotation**: you changed the password in the Secret but Pods still use the old one because they were not restarted.

## How to verify

In PKM open the Secret: you see type, keys and value sizes without revealing them; the Relazioni tab shows the Pods using it.

```bash
kubectl -n shop get secret db-credentials
kubectl -n shop describe secret db-credentials   # shows keys and sizes, not values
kubectl auth can-i get secrets -n shop --as=system:serviceaccount:shop:default
```

## How to fix

1. Create the missing Secret or fix the name and key in the workload.
2. After rotating credentials restart the workload from [Operazioni → Restart](app:/operations/restart).
3. Restrict with RBAC who can read Secrets and, in PKM, give the Administrator role only to people who really need to reveal values.
4. If a Secret has been exposed, treat the credential as compromised: change it at the source, then update the Secret.
5. Do not include real values in manifests stored in Git; use dedicated tools (Sealed Secrets, External Secrets) if needed.

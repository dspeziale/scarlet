---
title: ImagePullBackOff and ErrImagePull
summary: The node cannot download the container image from the registry.
category: troubleshooting
order: 30
keywords: imagepullbackoff, errimagepull, image, registry, pull, imagepullsecrets, tag, authentication
related: troubleshooting, container, secret, deployment, proc-diagnosticare-pod, cos-e-podman
---

## In simple terms

Before starting a container, the node must download its image from the registry (Docker Hub, Quay, GHCR, a company registry). If the download fails, the container stays stopped with **ErrImagePull**; after a few failed attempts Kubernetes switches to **ImagePullBackOff**, meaning it waits longer and longer before retrying. The container never started, so **there are no logs**: the cause is in the events.

The most common causes are: misspelled name or tag, non-existent image, private registry without credentials, node unable to reach the registry, download limits (rate limit).

## Technical details

- The pull is performed by the node's container runtime (containerd or CRI-O), not by the control plane. The node must resolve the registry DNS name and reach it over HTTPS.
- `ErrImagePull` is the first failure; `ImagePullBackOff` is the waiting state with exponential back-off up to 5 minutes.
- `imagePullPolicy`: `IfNotPresent` (default when the tag is not `latest`), `Always` (default for `latest` or no tag), `Never`.
- Private registries need a Secret of type `kubernetes.io/dockerconfigjson` referenced in `spec.imagePullSecrets` of the pod or of its ServiceAccount. The Secret must be **in the same namespace** as the pod.
- Typical event messages:
  - `manifest unknown` / `not found`: tag or image does not exist.
  - `unauthorized` / `authentication required` / `pull access denied`: missing or wrong credentials.
  - `toomanyrequests`: registry rate limit.
  - `dial tcp ... i/o timeout` / `no such host`: network or DNS problem from the node.
  - `x509: certificate signed by unknown authority`: the registry certificate is not trusted by the node.

## Example

```bash
kubectl describe pod web-5f7c9d8b6-m2kq9 -n shop
# Events:
#   Warning  Failed   kubelet  Failed to pull image "registry.example.com/shop/web:1.4.2":
#            ... unauthorized: authentication required
#   Warning  Failed   kubelet  Error: ErrImagePull
#   Normal   BackOff  kubelet  Back-off pulling image "registry.example.com/shop/web:1.4.2"

kubectl create secret docker-registry regcred -n shop \
  --docker-server=registry.example.com --docker-username=deploy --docker-password='***'
```

```yaml
spec:
  imagePullSecrets:
    - name: regcred
  containers:
    - name: web
      image: registry.example.com/shop/web:1.4.2
```

## What can go wrong

- The tag exists in one registry but not in the one specified (for example the registry prefix is missing and Docker Hub is used).
- The pull Secret was created in another namespace.
- The registry password expired or the token was revoked.
- The corporate proxy blocks the node but not your workstation: the pull works from your PC but not from the node.
- `latest` is used with `imagePullPolicy: Always`: every restart depends on the registry being available.

## How to verify

1. In the [Operations Center](app:/operations-center) the problem is reported as ImagePullBackOff or ErrImagePull.
2. Open the pod and read the **Eventi** tab: the `Failed to pull image` message gives the exact reason.
3. In the **YAML** tab check `image` and `imagePullSecrets`.
4. Check that the Secret exists in [Configurazione → Secrets](app:/k8s/secrets) in the correct namespace.
5. In the problem card press **Verifica registry** (Check registry): it opens the [Image onboarding](app:/operations/onboarding) wizard with the image prefilled, which checks from the Scarlet server the name format, registry reachability, authentication (you can enter credentials used once and never stored), tag existence and linux/amd64 availability. Note: the check runs from the Scarlet server, not from the nodes.
6. From a shell on the node (admin alternative): `sudo crictl pull registry.example.com/shop/web:1.4.2` to reproduce the problem.

## How to fix

1. **Wrong name or tag**: fix the image from the [Deploy](app:/operations/deploy) page or in the Deployment **YAML** tab, validate with the dry-run and apply.
2. **Credentials**: create or update the `docker-registry` Secret in the pod's namespace and add it to `imagePullSecrets`.
3. **Network/DNS/certificates**: involve the system administrator for proxy, firewall or the registry CA on the nodes.
4. **Rate limit**: use an internal registry mirror or authenticated credentials.
5. If the problem appeared with a new release and the service must be restored immediately, perform a [rollback](guide:proc-rollback).

After the fix Kubernetes retries on its own; to avoid waiting for the back-off you can delete the pod and let the controller recreate it.

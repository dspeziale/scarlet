---
title: Connecting Scarlet to Kubernetes
summary: Create a dedicated ServiceAccount, generate its kubeconfig and configure it in Scarlet with the right permissions.
category: procedures
order: 20
keywords: kubeconfig, serviceaccount, rbac, clusterrole, connection, in-cluster, token
related: cos-e-kubernetes, cluster, proc-installare, proc-verificare-cluster, faq
---

## When you need it

During the first setup (**Kubernetes** step of the wizard), or when you switch cluster, rotate credentials, or see Kubernetes as **Unhealthy** on the [Health](app:/monitoring/health) page.

## Prerequisites

- Scarlet installed (see [Installing Scarlet](guide:proc-installare)).
- Administrative access to the cluster (`kubectl` with cluster-admin rights) to create the RBAC resources.
- The manifest `deploy/kubernetes/pkm-rbac.yaml` shipped in the release tarball.

Using an administrator's personal kubeconfig works, but is discouraged: Scarlet would have all your powers and its actions would appear as yours in the cluster logs. A **dedicated ServiceAccount** limits permissions to those in the ClusterRole and makes Scarlet's actions traceable.

## Procedure

1. Apply the RBAC manifest included in the package (on the cluster, with administrator rights). It creates the `pkm-system` namespace, the `pkm` ServiceAccount, the `pkm-token` Secret with a long-lived token and two ClusterRoles: `pkm-operator` (bound by default: read + the operations Scarlet offers) and `pkm-readonly` (read only; to use it change `roleRef.name` in the `pkm` ClusterRoleBinding):

   ```bash
   kubectl apply -f /opt/pkm/current/deploy/kubernetes/pkm-rbac.yaml
   kubectl -n pkm-system get serviceaccount pkm
   ```

2. Generate the ServiceAccount kubeconfig with the included script, on a machine where `kubectl` works with administrator rights (for example a control-plane node, copying the script from `/opt/pkm/current/scripts/make-kubeconfig.sh`):

   ```bash
   ./make-kubeconfig.sh -o /tmp/pkm-kubeconfig            # --context <name> to choose the cluster
   kubectl --kubeconfig /tmp/pkm-kubeconfig get nodes      # test
   ```

   The script reads the token from the `pkm-system/pkm-token` Secret, server and CA from the current context, and writes a kubeconfig with context `pkm@<cluster>`. If you run it directly on the Scarlet server as root, use `-o /etc/pkm/kubeconfig` and skip step 4.

3. The file contains a long-lived token: do not copy it to shared places and never commit it to a repository.

4. Copy the file to the Scarlet server with the right permissions (readable by user `pkm`, not by others):

   ```bash
   sudo install -o root -g pkm -m 0640 /tmp/pkm-kubeconfig /etc/pkm/kubeconfig
   rm -f /tmp/pkm-kubeconfig /tmp/ca.crt
   ```

5. In Scarlet open [Settings → Kubernetes](app:/settings/kubernetes) (or the Kubernetes step of the wizard), enter the path `/etc/pkm/kubeconfig`, save and run the connection test.

6. **In-cluster** alternative: if Scarlet runs as a Pod in the cluster, select in-cluster mode; it will use the ServiceAccount token mounted in the Pod, which must be `pkm` with the ClusterRole applied.

## Verification

- From the Scarlet server, with Scarlet's identity:

  ```bash
  sudo -u pkm kubectl --kubeconfig /etc/pkm/kubeconfig get nodes
  sudo -u pkm kubectl --kubeconfig /etc/pkm/kubeconfig auth can-i list pods -A
  ```

- On [Health](app:/monitoring/health) the Kubernetes entry is **Healthy**.
- The **LIVE** badge shows the `pkm` context.
- [Cluster → Panoramica](app:/cluster) lists the real nodes and namespaces.

## If something goes wrong

- **`x509: certificate signed by unknown authority`**: the CA in the kubeconfig is not the API server's; repeat step 3 from the correct context.
- **`Unauthorized` (401)**: expired or wrong token; generate a new one (step 2) and update the file.
- **`Forbidden` (403) on some resources**: the ClusterRole does not include that verb or resource. Check with `kubectl auth can-i --list --as=system:serviceaccount:pkm-system:pkm`. Do not widen permissions to cluster-admin for convenience.
- **`permission denied` on the file**: check `ls -l /etc/pkm/kubeconfig` (must be `root:pkm 0640`).
- **Timeout**: the Scarlet server cannot reach the API server (typically port 6443); check network and firewall.

---
title: Frequently asked questions
summary: Quick answers to the most common questions about installation, access, roles, metrics, backup and Podman.
category: faq
order: 10
keywords: faq, questions, setup token, password, roles, metrics, demo, live, backup, podman socket, tls, certificate
related: introduzione, proc-installare, proc-collegare-kubernetes, proc-collegare-podman, backup, monitoring, troubleshooting
---

## Frequently asked questions

### I lost the setup token shown at the end of the installation. What do I do?

The token is only needed for the first access to the setup wizard. You can generate a new one on the server with `sudo pkm-admin setup-token`. The token is single-use: once the first Administrator is created the wizard is no longer accessible.

### I forgot the administrator password.

Another Administrator can reset it from [Sicurezza → Utenti](app:/security/users). If there is no other administrator, run `sudo pkm-admin reset-password <user>` on the server; alternatively `sudo pkm-admin create-admin` creates a new Administrator account.

### What is the difference between LIVE and DEMO mode?

In **LIVE** PKM works on the real cluster and Podman: the header shows a green "LIVE" badge with the cluster context. In **DEMO** (`mode: demo` in `/etc/pkm/config.yaml`) the app uses sample data and shows a striped "DEMO" banner. DEMO mode is for training and trials and is accepted only with `environment: development` (with `production` the service refuses to start): never use it in production and never make decisions based on its data.

### Why do I see "Metriche avanzate non configurate"?

Pod and node CPU and memory come from **metrics-server** (the `metrics.k8s.io` API); network traffic and history come from **Prometheus**, if configured in Impostazioni. If these sources are missing PKM says so explicitly and never invents values. Check the status in [Monitoraggio → Health](app:/monitoring/health).

### What can each role do?

- **Administrator**: everything, including users, settings, backup/restore and revealing Secret values.
- **Operator**: monitoring, deploy, scale, restart, rollout, logs, troubleshooting, start/stop/restart of Podman containers.
- **Viewer**: read only, without logs and without Secret values.

Permissions are enforced by the backend: hiding a button is not what protects an action, and a forbidden operation is rejected.

### How do I see the value of a Secret?

Values are hidden by default. Only an Administrator can reveal them from the Secret page, and every reveal is recorded in the [Audit Log](app:/security/audit).

### Does the PKM backup also save my applications?

No. The PKM backup contains the application database (`/var/lib/pkm/pkm.db`) and its configuration. The Kubernetes manifests export saves the YAML of resources, but not volume data nor etcd. A real cluster backup (etcd snapshot, Velero) must be done with dedicated tools: see [Backup](guide:backup).

### Where are backups stored and when do they run?

In `/var/lib/pkm/backups`. The systemd timer `pkm-backup.timer` runs them periodically; you can start a manual one from [Operazioni → Backup](app:/operations/backup) or with `sudo pkm-admin backup`. Also copy backups off the server.

### Why does the browser say the certificate is not secure?

The installer generates a self-signed certificate in `/etc/pkm/tls/`. It is fine for the first start but must be replaced with a certificate issued by a CA your organization trusts. The TLS step of the wizard and the [system settings](app:/settings/system) help you configure it.

### Is connecting the rootful Podman socket risky?

Yes, and you should know it. Access to the `/run/podman/podman.sock` socket is equivalent to root privileges on the host: whoever controls it can start privileged containers. The installer grants access to the `pkm` group (SocketGroup=pkm, SocketMode=0660). If you do not need to manage root containers, use the rootless socket of a dedicated user (`/run/user/<uid>/podman/podman.sock`). See [Connect Podman](guide:proc-collegare-podman).

### PKM does not see the Kubernetes cluster. Where do I start?

Check [Monitoraggio → Health](app:/monitoring/health) and [Impostazioni → Kubernetes](app:/settings/kubernetes). Typical causes are a kubeconfig not readable by the `pkm` user (it should be, for example, `/etc/pkm/kubeconfig` with mode 0640 root:pkm), an unreachable API server or an expired token. You can check the configuration with `sudo pkm-admin check-config`.

### What permissions should PKM have on the cluster?

A dedicated ServiceAccount is recommended: the `deploy/kubernetes/pkm-rbac.yaml` manifest included in the package creates the `pkm-system` namespace, the `pkm` ServiceAccount and the `pkm-operator` (default) and `pkm-readonly` ClusterRoles; the kubeconfig is generated with `scripts/make-kubeconfig.sh`. Avoid using your personal cluster-admin kubeconfig.

### Are changes made in the YAML tab safe?

Before applying you can **validate** with a server-side dry-run (the API server checks the resource without saving it) and see the **diff** against the current state. Apply only after reading the diff. Remember that manual changes to resources managed by GitOps tools may be overwritten.

### Why did log streaming stop on its own?

To protect server and browser, live streaming stops after 30 minutes or 20000 lines. Restart it with the button; each request can read at most 5000 lines. For long analyses use the download.

### A pod is in CrashLoopBackOff: should I restart it?

First understand the cause by reading the previous instance logs and the events. A restart without a fix does not solve anything. See [CrashLoopBackOff](guide:crashloopbackoff) and the [troubleshooting method](guide:troubleshooting).

### How do I upgrade PKM to a new version?

Extract the new package and run `sudo ./upgrade.sh`. The script installs the new release in `/opt/pkm/releases/<version>`, migrates the database, restarts the service and checks its health; if something fails it automatically rolls back to the previous release. Take a backup first anyway.

### Where do I find the PKM logs?

In the systemd journal (`journalctl -u pkm.service`) and in the file `/var/log/pkm/pkm.log`, rotated by the application itself (10 MB × 5 files). The log level is set in [Impostazioni → Logging](app:/settings/logging).

### Does uninstalling PKM delete the data?

No: `sudo ./uninstall.sh` removes the application but keeps data, configuration and backups. Only with `--purge` are these deleted too.

### Where can I see who did what?

In [Sicurezza → Audit Log](app:/security/audit): every action that changes resources, every login and every Secret reveal is recorded with user, date and outcome.

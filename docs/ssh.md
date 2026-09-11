# SSH access to target hosts

## Remote user requirements

Create a dedicated, unprivileged user on every target (default name `scarlet`):

```bash
sudo useradd -m scarlet
sudo mkdir -p /opt/scarlet && sudo chown scarlet:scarlet /opt/scarlet     # SCARLET_REMOTE_BASE_PATH
sudo loginctl enable-linger scarlet                                       # rootless podman survives logout
sudo dnf install -y podman tar gzip nmap-ncat curl                        # tar/sha256sum/curl/nc are required
```

Required binaries on the host: `sh tar gzip sha256sum mkdir mv rm ln readlink ls cat uname nproc
free df id hostname curl nc` plus the runtime (`podman`/`docker`/`kubectl`). `getenforce` is used
when present. The user needs write access to the base path; nothing else. No `sudo` is ever used.

## Authentication

Preferred: **ed25519 private key** generated on the SCARLET server and installed in
`~scarlet/.ssh/authorized_keys` on the target (`chmod 700 ~/.ssh; chmod 600 authorized_keys`).
Optionally restrict the key in `authorized_keys`:

```
from="10.10.0.5",no-agent-forwarding,no-port-forwarding,no-X11-forwarding ssh-ed25519 AAAA... scarlet
```

Password authentication is supported for bootstrap but discouraged. Credentials are stored
encrypted (Fernet, `SCARLET_CREDENTIAL_ENCRYPTION_KEY`) and rotated by adding a new credential.

## Host key verification

- `SCARLET_SSH_HOST_KEY_POLICY=strict` (default, mandatory in production): the host key must be
  approved by an administrator. Workflow: *Scan host key* → compare the fingerprint with the value
  read on the console (`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`) → *Approve fingerprint*.
- `tofu` (development only): first key is stored automatically.
- A key different from the approved one blocks the connection, sets `MISMATCH`, marks the host
  OFFLINE and writes a CRITICAL security event (`SSH_HOST_KEY_MISMATCH`). See RUNBOOK §31.
- Changing hostname/IP/port of a host invalidates the approved key.
- Fingerprints use OpenSSH's `SHA256:` base64 format.

## Connection parameters

| Setting | Default | Purpose |
|---|---|---|
| `SCARLET_SSH_TIMEOUT` | 30 s | connect/banner/auth timeout |
| `SCARLET_SSH_COMMAND_TIMEOUT` | 600 s | default per-command timeout (pull/load up to 900 s) |
| `SCARLET_SFTP_TIMEOUT` | 1800 s | file transfer |
| keepalive | 30 s | transport keepalive |

Paramiko is used with `allow_agent=False`, `look_for_keys=False`; each command runs in its own
channel with stdout/stderr/exit code captured and a hard timeout.

## What SCARLET executes

Only allow-listed binaries with argv quoting (see `docs/security.md`). Typical command trace of a
deployment (visible in Deployments → deployment → step output):

```
mkdir -p /opt/scarlet/applications/customer-api/releases
sha256sum -- /opt/scarlet/applications/customer-api/staging/2.5.0.ab12cd34.scarlet.tar.gz
tar --no-same-owner --no-same-permissions --no-overwrite-dir -xzf … -C …/staging/2.5.0.ab12cd34.extract
mv -T -- …/staging/2.5.0.ab12cd34.extract …/releases/2.5.0
podman pull registry.example.internal/team/customer-api:2.5.0
ln -sfn -- …/releases/2.5.0 …/current.tmp && mv -T -- …/current.tmp …/current
podman run -d --name customer-api --label scarlet.application=customer-api --label scarlet.version=2.5.0 …
curl -k -s -S -o /dev/null -w %{http_code} --max-time 5 http://127.0.0.1:8080/health
```

## Troubleshooting

`ssh -vvv -i <key> scarlet@host` from the SCARLET server reproduces authentication issues;
`journalctl -u sshd` on the target shows denied logins; SELinux denials on `authorized_keys`
are fixed with `restorecon -Rv ~scarlet/.ssh`. See RUNBOOK §17.

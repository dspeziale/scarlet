# Backend tests

All commands run from `backend/` with the project virtualenv.

## Unit, API, security and failure tests

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"      # Windows: .venv\Scripts\pip
.venv/bin/python -m pytest                                        # ~2.5 min, no cluster needed
.venv/bin/python -m pytest --cov=pkm --cov-report=term-missing    # with coverage
```

They use the DEMO provider (in-memory cluster and Podman), local fake HTTP servers
for the live Kubernetes/Podman clients, and LIVE mode pointed at closed ports to
test unreachable/timeout handling. Nothing outside the machine is contacted.

| File | Scope |
|------|-------|
| `test_unit_basics.py` | config, quantities, names, passwords, rate limiter, RBAC, logging |
| `test_unit_diagnostics.py` | summaries, problem detection (every reason), relations |
| `test_unit_manifests_images.py` | deploy wizard manifests and risks, image onboarding, Podman demux, live client helpers |
| `test_unit_services.py` | users/sessions, audit, notifications, runtime settings, backup/restore, operations, Prometheus |
| `test_unit_k8s_service.py` | Kubernetes service operations on the demo cluster |
| `test_api_*.py` | every REST endpoint, RBAC matrix, CSRF, headers, SSE |
| `test_failures_live.py` | LIVE mode with cluster/Podman offline, timeouts, bad kubeconfig, 403, fake API servers |
| `test_cli.py` | `pkm-admin` / `pkm-server` |
| `test_integration.py` | real cluster and real Podman (skipped unless configured) |

## Integration tests (real Kubernetes and Podman)

Requires Docker. Example with [kind](https://kind.sigs.k8s.io/) and Podman running in a container:

```bash
kind create cluster --name pkm-it --kubeconfig /tmp/pkm-it-kubeconfig
docker run -d --privileged --name pkm-podman -p 18888:8888 \
  quay.io/podman/stable podman system service --time=0 tcp:0.0.0.0:8888

PKM_IT_KUBECONFIG=/tmp/pkm-it-kubeconfig PKM_IT_PODMAN_URL=http://127.0.0.1:18888 \
  .venv/bin/python -m pytest tests/test_integration.py -v

kind delete cluster --name pkm-it && docker rm -f pkm-podman
```

The cluster needs Internet access to pull `docker.io/library/nginx:1.27-alpine`
(override with `PKM_IT_IMAGE` / `PKM_IT_TAG`); Podman pulls `docker.io/library/busybox:1.36`
(`PKM_IT_PODMAN_IMAGE`). Nested Podman (cgroupfs inside a container) reports no container
stats; the test accepts an empty stats list in that case.

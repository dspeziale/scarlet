"""Docker e HTTP finti per i test di appctl (nessun daemon richiesto)."""

from __future__ import annotations

from pathlib import Path

from appctl.http import Probe
from appctl.runner import Result

A = "git-aaaaaaaaaaaa"
B = "git-bbbbbbbbbbbb"
BAD = "git-badbadbadbad"
CRASH = "git-crashcrashcr"

REPO = "registry.test/ised/scarlet"
COMPOSE_FILES = ["compose.yaml", "compose.db.yaml", "compose.prod.yaml"]


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


class FakeRunner:
    """Scrive il log di deploy come il CommandRunner reale (senza eseguire comandi)."""

    def __init__(self) -> None:
        self.log_file: Path | None = None

    def log(self, text: str) -> None:
        if self.log_file:
            with self.log_file.open("a", encoding="utf-8") as fh:
                fh.write(text.rstrip("\n") + "\n")


class FakeDocker:
    """Simula Docker Engine + Compose in memoria.

    ``registry``: immagini scaricabili -> {"health": "healthy|unhealthy|crash", "version":..., "commit":...}
    """

    def __init__(self, project: str, compose_env: dict[str, str]):
        self.project = project
        self.compose_env = dict(compose_env)
        self.runner = FakeRunner()
        self.registry: dict[str, dict] = {}
        self.registry_available = True
        self.local_images: dict[str, dict] = {}
        self.containers: dict[str, dict] = {}
        self.release_dir: Path | None = None
        self.compose_files: list[str] = []
        self.calls: list[tuple] = []
        self.port_busy = False
        self.fail_migration = False
        self.compose_config_ok = True
        self.networks = {"proxy"}
        self.bundle_files = {f: f"# {f}\nservices: {{}}\n" for f in COMPOSE_FILES}
        self.pg_dump_output = "-- PostgreSQL dump\nCREATE TABLE t (id int);\n"

    # --- engine
    def ping(self) -> str:
        self.calls.append(("ping",))
        return "29.0.0"

    def compose_version(self) -> str:
        return "2.40.0"

    def set_release(self, release_dir: Path, compose_files: list[str], image: str) -> None:
        self.release_dir = release_dir
        self.compose_files = compose_files
        self.compose_env["IMAGE"] = image
        self.calls.append(("set_release", release_dir.name, image))

    def image_exists_locally(self, image: str) -> bool:
        return image in self.local_images

    def image_digest(self, image: str) -> str:
        return f"{image.rsplit(':', 1)[0]}@sha256:{abs(hash(image)) % 10**12:012d}"

    def image_labels(self, image: str) -> dict[str, str]:
        meta = self.local_images.get(image, {})
        return {
            "org.opencontainers.image.version": meta.get("version", "unknown"),
            "org.opencontainers.image.revision": meta.get("commit", "unknown"),
        }

    def login(self, registry: str, user: str, token: str) -> Result:
        self.calls.append(("login", registry, user))
        if token == "good-token":
            return Result(0, "Login Succeeded", "")
        return Result(1, "", "unauthorized")

    def logout(self, registry: str) -> Result:
        self.calls.append(("logout", registry))
        return Result(0, "", "")

    def pull(self, image: str) -> Result:
        self.calls.append(("pull", image))
        if not self.registry_available:
            return Result(
                1,
                "",
                "Error response from daemon: Get https://registry.test/v2/: dial tcp: connection refused",
            )
        if image not in self.registry:
            return Result(
                1,
                "",
                f"Error response from daemon: manifest for {image} not found: manifest unknown",
            )
        self.local_images[image] = dict(self.registry[image])
        return Result(0, image, "")

    def extract_bundle(self, image: str, destination: Path, source: str = "/deploy") -> None:
        self.calls.append(("extract", image, destination.name))
        destination.mkdir(parents=True, exist_ok=True)
        for name, content in self.bundle_files.items():
            (destination / name).write_text(content)

    def prune_images(self, keep: set[str]) -> None:
        self.calls.append(("prune", tuple(sorted(keep))))

    def network_exists(self, name: str) -> bool:
        return name in self.networks

    def disk_usage(self) -> str:
        return ""

    # --- compose
    def _image(self) -> str:
        return self.compose_env.get("IMAGE", "")

    def compose(self, *args: str, **kwargs) -> Result:
        self.calls.append(("compose", *args))
        if args and args[0] == "stop":
            for c in self.containers.values():
                c["State"]["Status"] = "exited"
        return Result(0, "", "")

    def compose_config_check(self) -> Result:
        self.calls.append(("config-check",))
        return (
            Result(0, "", "")
            if self.compose_config_ok
            else Result(1, "", "service app: env file not found")
        )

    def compose_services(self) -> list[str]:
        return ["app", "db"]

    def _start(self, name: str, image: str, health: str) -> None:
        prev = self.containers.get(name)
        restarts = prev["RestartCount"] if prev else 0
        state = {
            "Status": "running",
            "Health": {
                "Status": "healthy"
                if health == "healthy"
                else ("unhealthy" if health == "unhealthy" else "starting")
            },
            "StartedAt": "2026-09-30T08:42:11.123456789Z",
            "FinishedAt": "0001-01-01T00:00:00Z",
            "ExitCode": 0,
        }
        if health == "crash":
            state.update({"Status": "exited", "ExitCode": 1, "Health": {}})
        if health == "loop":
            state.update({"Status": "restarting"})
            restarts += 2
        self.containers[name] = {
            "State": state,
            "RestartCount": restarts,
            "Config": {"Image": image},
            "HostConfig": {"LogConfig": {"Type": "json-file", "Config": {"max-size": "20m"}}},
        }

    def compose_up(self, *services: str, force_recreate: bool = False) -> Result:
        self.calls.append(("up", services, force_recreate))
        image = self._image()
        if services == ("db",):
            self._start(f"{self.project}-db", "postgres:16", "healthy")
            return Result(0, "", "")
        if self.port_busy:
            return Result(
                1,
                "",
                "Error response from daemon: Bind for 127.0.0.1:8080 failed: port is already allocated",
            )
        meta = self.local_images.get(image)
        if meta is None:
            return Result(1, "", f"Error response from daemon: No such image: {image}")
        self._start(f"{self.project}-app", image, meta.get("health", "healthy"))
        return Result(0, "", "")

    def compose_stop(self) -> Result:
        return self.compose("stop")

    def compose_restart(self) -> Result:
        self.calls.append(("restart",))
        for c in self.containers.values():
            c["State"]["Status"] = "running"
        return Result(0, "", "")

    def compose_down(self) -> Result:
        self.containers.clear()
        return Result(0, "", "")

    def compose_run(self, service: str, command: list[str]) -> Result:
        self.calls.append(("run", service, tuple(command)))
        if self.fail_migration:
            return Result(1, "", "FAILED: relation already exists\nalembic.util.exc.CommandError")
        return Result(0, "INFO  [alembic.runtime.migration] Running upgrade -> 0001", "")

    def compose_exec(
        self, service: str, command: list[str], input_text: str | None = None
    ) -> Result:
        self.calls.append(("exec", service, tuple(command)))
        if command and command[0] == "pg_dump":
            return Result(0, self.pg_dump_output, "")
        return Result(0, "", "")

    def compose_logs(self, args: list[str], stream: bool = True) -> Result:
        self.calls.append(("logs", tuple(args)))
        return Result(0, "", "")

    def compose_ps_ids(self) -> list[str]:
        return list(self.containers)

    # --- container
    def inspect_container(self, name: str) -> dict | None:
        return self.containers.get(name)

    def inspect_containers(self, ids: list[str]) -> list[dict]:
        return [self.containers[i] for i in ids if i in self.containers]

    def container_logs_tail(self, name: str, lines: int = 100) -> str:
        return "log line 1\nlog line 2\n"

    def container_stats(self, names: list[str]) -> list[dict]:
        return []


class FakeHttp:
    """Risponde in base allo stato del FakeDocker."""

    def __init__(self, docker: FakeDocker):
        self.docker = docker
        self.registry_status = 401

    def _app(self) -> tuple[dict | None, dict]:
        c = self.docker.containers.get(f"{self.docker.project}-app")
        if not c or c["State"]["Status"] != "running":
            return None, {}
        return c, self.docker.local_images.get(c["Config"]["Image"], {})

    def get(self, url: str, timeout: float = 3.0) -> Probe:
        if url.endswith("/v2/"):
            return (
                Probe(self.registry_status, None)
                if self.registry_status
                else Probe(0, None, "timeout")
            )
        c, meta = self._app()
        if c is None:
            return Probe(0, None, "connection refused")
        health = meta.get("health", "healthy")
        if url.endswith("/health"):
            return (
                Probe(200, {"status": "ok"})
                if health == "healthy"
                else Probe(503, {"status": "unhealthy"})
            )
        if url.endswith("/ready"):
            if health == "healthy":
                return Probe(200, {"status": "ready", "checks": {"database": {"ok": True}}})
            return Probe(
                503,
                {
                    "status": "not-ready",
                    "checks": {"database": {"ok": False, "error": "schema non allineato"}},
                },
            )
        if url.endswith("/version"):
            return Probe(
                200, {"version": meta.get("version", "?"), "commit": meta.get("commit", "?")}
            )
        return Probe(404, None)

    def tls_days_left(self, host: str, port: int = 443, timeout: float = 5.0) -> int | None:
        return 90


def write_app(app_dir: Path, environment: str = "production", **overrides: str) -> None:
    conf = {
        "APP_NAME": "scarlet",
        "APP_ENVIRONMENT": environment,
        "IMAGE_REPOSITORY": REPO,
        "COMPOSE_FILES": ":".join(COMPOSE_FILES),
        "DB_SERVICE": "db",
        "MIGRATE_COMMAND": "alembic upgrade head",
        "HEALTH_TIMEOUT": "30",
        "HEALTH_INTERVAL": "1",
        "KEEP_RELEASES": "3",
        "AUDIT_LOG": str(app_dir / "audit.log"),
        "BACKUP_KEEP_DAYS": "7",
    }
    conf.update(overrides)
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "app.conf").write_text("".join(f"{k}={v}\n" for k, v in conf.items()))
    (app_dir / "config").mkdir(exist_ok=True)
    (app_dir / "config" / "app.env").write_text("SCARLET_ENVIRONMENT=production\n")
    (app_dir / "secrets").mkdir(exist_ok=True)
    (app_dir / "secrets" / "app.secrets.env").write_text(
        "POSTGRES_USER=scarlet\nPOSTGRES_PASSWORD=x\nPOSTGRES_DB=scarlet\n"
    )

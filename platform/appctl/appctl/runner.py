"""Esecuzione comandi esterni e client Docker/Compose.

Tutto cio' che tocca Docker passa da ``DockerClient``: i test lo sostituiscono con un fake e
le operazioni di alto livello (ops.py) non conoscono la riga di comando docker.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from appctl.errors import AppctlError, DockerUnavailableError


@dataclass
class Result:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class CommandRunner:
    """Wrapper minimale di subprocess, con log opzionale su file."""

    def __init__(self, log_file: Path | None = None):
        self.log_file = log_file

    def log(self, text: str) -> None:
        if self.log_file:
            with self.log_file.open("a", encoding="utf-8") as fh:
                fh.write(text.rstrip("\n") + "\n")

    def run(
        self,
        cmd: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        timeout: int | None = 600,
        input_text: str | None = None,
        stream: bool = False,
    ) -> Result:
        full_env = {**os.environ, **(env or {})}
        self.log("$ " + " ".join(cmd))
        try:
            if stream:
                proc = subprocess.run(
                    cmd, env=full_env, cwd=cwd, timeout=timeout, check=False, text=True
                )
                return Result(proc.returncode, "", "")
            proc = subprocess.run(
                cmd,
                env=full_env,
                cwd=cwd,
                timeout=timeout,
                check=False,
                capture_output=True,
                text=True,
                input=input_text,
            )
        except FileNotFoundError as exc:
            raise AppctlError(f"comando non trovato: {cmd[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AppctlError(f"timeout ({timeout}s) eseguendo: {' '.join(cmd)}") from exc
        if proc.stdout:
            self.log(proc.stdout)
        if proc.stderr:
            self.log(proc.stderr)
        return Result(proc.returncode, proc.stdout or "", proc.stderr or "")


class DockerClient:
    """Operazioni Docker/Compose usate da appctl."""

    def __init__(self, runner: CommandRunner, project: str, compose_env: dict[str, str]):
        self.runner = runner
        self.project = project
        self.compose_env = compose_env
        self.compose_base: list[str] = []  # impostata da set_release()
        self._release_dir: Path | None = None

    # ------------------------------------------------------------------ setup
    def set_release(self, release_dir: Path, compose_files: list[str], image: str) -> None:
        """Punta docker compose alla release (directory con i file compose) e all'immagine."""
        self._release_dir = release_dir
        self.compose_env = {**self.compose_env, "IMAGE": image}
        self.compose_base = [
            "docker",
            "compose",
            "-p",
            self.project,
            "--project-directory",
            str(release_dir),
        ]
        for f in compose_files:
            self.compose_base += ["-f", str(release_dir / f)]

    @property
    def release_dir(self) -> Path | None:
        return self._release_dir

    def _require_release(self) -> None:
        if not self.compose_base:
            raise AppctlError("nessuna release attiva: eseguire prima 'appctl deploy <tag>'")

    # ------------------------------------------------------------------ docker engine
    def ping(self) -> str:
        if shutil.which("docker") is None:
            raise DockerUnavailableError("comando 'docker' non installato")
        r = self.runner.run(["docker", "version", "--format", "{{.Server.Version}}"], timeout=20)
        if not r.ok:
            raise DockerUnavailableError(f"Docker non raggiungibile: {r.stderr.strip()[:200]}")
        return r.stdout.strip()

    def compose_version(self) -> str:
        r = self.runner.run(["docker", "compose", "version", "--short"], timeout=20)
        if not r.ok:
            raise DockerUnavailableError(
                "Docker Compose v2 non disponibile (docker compose version)"
            )
        return r.stdout.strip()

    def image_exists_locally(self, image: str) -> bool:
        r = self.runner.run(
            ["docker", "image", "inspect", image, "--format", "{{.Id}}"], timeout=30
        )
        return r.ok

    def image_digest(self, image: str) -> str:
        r = self.runner.run(
            ["docker", "image", "inspect", image, "--format", '{{join .RepoDigests ","}}'],
            timeout=30,
        )
        if not r.ok:
            return ""
        return r.stdout.strip().split(",")[0] if r.stdout.strip() else ""

    def image_labels(self, image: str) -> dict[str, str]:
        r = self.runner.run(
            ["docker", "image", "inspect", image, "--format", "{{json .Config.Labels}}"], timeout=30
        )
        if not r.ok or not r.stdout.strip():
            return {}
        try:
            return json.loads(r.stdout) or {}
        except json.JSONDecodeError:
            return {}

    def pull(self, image: str) -> Result:
        return self.runner.run(["docker", "pull", "--quiet", image], timeout=900)

    def extract_bundle(self, image: str, destination: Path, source: str = "/deploy") -> None:
        """Copia il bundle di deploy dall'immagine (senza avviarla) in destination."""
        name = f"{self.project}-extract-{os.getpid()}"
        create = self.runner.run(["docker", "create", "--name", name, image], timeout=120)
        if not create.ok:
            raise AppctlError(
                f"impossibile creare il container temporaneo: {create.stderr.strip()[:200]}"
            )
        try:
            tmp = destination.parent / (destination.name + ".tmp")
            if tmp.exists():
                shutil.rmtree(tmp)
            tmp.mkdir(parents=True)
            cp = self.runner.run(["docker", "cp", f"{name}:{source}/.", str(tmp)], timeout=120)
            if not cp.ok:
                shutil.rmtree(tmp, ignore_errors=True)
                raise AppctlError(
                    f"l'immagine non contiene il bundle di deploy in {source}: {cp.stderr.strip()[:200]}",
                    hint="il Dockerfile deve contenere: COPY deploy /deploy",
                )
            if destination.exists():
                shutil.rmtree(destination)
            tmp.rename(destination)
        finally:
            self.runner.run(["docker", "rm", "-f", name], timeout=60)

    def prune_images(self, keep: set[str]) -> None:
        """Rimuove le immagini del repository non piu' referenziate (best effort)."""
        r = self.runner.run(
            ["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"], timeout=60
        )
        if not r.ok:
            return
        for ref in r.stdout.split():
            repo = ref.rsplit(":", 1)[0]
            if repo in {k.rsplit(":", 1)[0] for k in keep} and ref not in keep:
                self.runner.run(["docker", "image", "rm", ref], timeout=120)

    def network_exists(self, name: str) -> bool:
        return self.runner.run(
            ["docker", "network", "inspect", name, "--format", "{{.Id}}"], timeout=20
        ).ok

    def disk_usage(self) -> str:
        r = self.runner.run(["docker", "system", "df"], timeout=60)
        return r.stdout if r.ok else ""

    # ------------------------------------------------------------------ compose
    def compose(
        self,
        *args: str,
        timeout: int | None = 600,
        stream: bool = False,
        input_text: str | None = None,
    ) -> Result:
        self._require_release()
        return self.runner.run(
            [*self.compose_base, *args],
            env=self.compose_env,
            timeout=timeout,
            stream=stream,
            input_text=input_text,
        )

    def compose_config_check(self) -> Result:
        return self.compose("config", "--quiet", timeout=60)

    def compose_services(self) -> list[str]:
        r = self.compose("config", "--services", timeout=60)
        return r.stdout.split() if r.ok else []

    def compose_up(self, *services: str, force_recreate: bool = False) -> Result:
        # Nessun --wait: l'health gate (/health + /ready) e' gestito da appctl, con diagnostica.
        args = ["up", "-d", "--remove-orphans", "--no-build"]
        if force_recreate:
            args.append("--force-recreate")
        return self.compose(*args, *services, timeout=900)

    def compose_stop(self) -> Result:
        return self.compose("stop", timeout=300)

    def compose_restart(self) -> Result:
        return self.compose("restart", timeout=300)

    def compose_down(self) -> Result:
        return self.compose("down", "--remove-orphans", timeout=300)

    def compose_run(self, service: str, command: list[str]) -> Result:
        return self.compose("run", "--rm", "-T", service, *command, timeout=1800)

    def compose_exec(
        self, service: str, command: list[str], input_text: str | None = None
    ) -> Result:
        return self.compose("exec", "-T", service, *command, timeout=3600, input_text=input_text)

    def compose_logs(self, args: list[str], stream: bool = True) -> Result:
        return self.compose("logs", *args, timeout=None, stream=stream)

    def compose_ps_ids(self) -> list[str]:
        r = self.compose("ps", "-a", "-q", timeout=60)
        return r.stdout.split() if r.ok else []

    # ------------------------------------------------------------------ container
    def inspect_containers(self, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        r = self.runner.run(["docker", "inspect", *ids], timeout=60)
        if not r.ok:
            return []
        try:
            return json.loads(r.stdout)
        except json.JSONDecodeError:
            return []

    def inspect_container(self, name: str) -> dict | None:
        found = self.inspect_containers([name])
        return found[0] if found else None

    def container_logs_tail(self, name: str, lines: int = 100) -> str:
        r = self.runner.run(["docker", "logs", "--tail", str(lines), name], timeout=60)
        return (r.stdout + r.stderr) if r.ok else r.stderr

    def container_stats(self, names: list[str]) -> list[dict]:
        if not names:
            return []
        r = self.runner.run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}", *names], timeout=60
        )
        rows = []
        if r.ok:
            for line in r.stdout.splitlines():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows

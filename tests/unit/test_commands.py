import pytest

from app.deployment.domain import DesiredApplicationState, HealthSpec
from app.deployment.remote_layout import RemoteLayout
from app.errors import UnsafeCommandError, ValidationError
from app.runtimes.base import HostInfo, RuntimeContext
from app.runtimes.container import DockerRuntimeAdapter, PodmanRuntimeAdapter
from app.runtimes.factory import RuntimeFactory
from app.ssh.command import (
    FileCommands,
    RemoteCommand,
    SystemCommands,
    join_remote,
    validate_remote_path,
)


def test_render_quotes_every_argument():
    cmd = RemoteCommand(("podman", "run", "--name", "app; rm -rf /", "img"), "runtime.podman.run")
    rendered = cmd.render()
    assert "'app; rm -rf /'" in rendered
    assert rendered.startswith("podman run --name ")


def test_disallowed_binary_rejected():
    with pytest.raises(UnsafeCommandError):
        RemoteCommand(("bash", "-c", "id"), "x")
    with pytest.raises(UnsafeCommandError):
        RemoteCommand(("/usr/bin/python3", "-c", "1"), "x")


def test_restricted_binaries_only_from_builders():
    with pytest.raises(UnsafeCommandError):
        RemoteCommand(("sh", "-c", "id"), "runtime.something")
    with pytest.raises(UnsafeCommandError):
        RemoteCommand(("timeout", "5", "sh", "x"), "custom")


def test_newlines_and_nul_rejected():
    with pytest.raises(UnsafeCommandError):
        RemoteCommand(("ls", "a\nb"), "x")
    with pytest.raises(UnsafeCommandError):
        RemoteCommand(("ls", "a\x00b"), "x")


def test_env_prefix_rendering():
    cmd = RemoteCommand(("true",), "x", env={"SCARLET_APP": "a b"})
    assert cmd.render() == "SCARLET_APP='a b' true"
    with pytest.raises(UnsafeCommandError):
        RemoteCommand(("true",), "x", env={"bad-key": "v"})


def test_sensitive_command_is_redacted_in_logs():
    cmd = RemoteCommand(("podman", "login", "-p", "secret"), "runtime.login", sensitive=True)
    assert "secret" not in cmd.rendered_for_log()


@pytest.mark.parametrize(
    "path",
    [
        "/opt/scarlet/../etc",
        "/etc/passwd",
        "opt/scarlet/x",
        "/opt/scarlet/./x",
        "/opt/scarlet/a;b",
        "/opt/scarletx",
    ],
)
def test_remote_path_escape_rejected(path):
    with pytest.raises((UnsafeCommandError, ValidationError)):
        validate_remote_path(path, "/opt/scarlet")


def test_remote_path_ok():
    assert validate_remote_path("/opt/scarlet/applications/app/releases/1.0.0", "/opt/scarlet")
    assert join_remote("/opt/scarlet", "applications", "app") == "/opt/scarlet/applications/app"
    with pytest.raises(ValidationError):
        join_remote("/opt/scarlet", "..")


def test_file_commands_refuse_top_level_rmtree():
    fs = FileCommands("/opt/scarlet")
    with pytest.raises(UnsafeCommandError):
        fs.remove_tree("/opt/scarlet")
    with pytest.raises(UnsafeCommandError):
        fs.remove_tree("/opt/scarlet/applications")
    cmd = fs.remove_tree("/opt/scarlet/applications/app/staging/x")
    assert cmd.argv[:3] == ("rm", "-rf", "--")


def test_atomic_symlink_switch():
    fs = FileCommands("/opt/scarlet")
    cmds = fs.atomic_symlink_switch(
        "/opt/scarlet/applications/app/releases/2.0.0", "/opt/scarlet/applications/app/current"
    )
    assert cmds[0].argv[0] == "ln" and "-sfn" in cmds[0].argv
    assert cmds[1].argv[0] == "mv" and "-T" in cmds[1].argv
    assert cmds[0].argv[-1].endswith("current.tmp")


def test_hook_command_constraints():
    fs = FileCommands("/opt/scarlet")
    release = "/opt/scarlet/applications/app/releases/1.0.0"
    cmd = fs.run_hook(f"{release}/scripts/pre.sh", release, 60, {"SCARLET_VERSION": "1.0.0"})
    assert cmd.argv[:4] == ("timeout", "60", "sh", "-e")
    with pytest.raises(UnsafeCommandError):
        fs.run_hook(f"{release}/config/pre.sh", release, 60, {})
    with pytest.raises(UnsafeCommandError):
        fs.run_hook(f"{release}/scripts/pre.py", release, 60, {})
    with pytest.raises(UnsafeCommandError):
        fs.run_hook(f"{release}/scripts/pre.sh", release, 60, {"PATH": "/tmp"})


def test_system_commands_are_read_only_binaries():
    for cmd in (
        SystemCommands.os_release(),
        SystemCommands.uname(),
        SystemCommands.nproc(),
        SystemCommands.memory(),
        SystemCommands.disk(),
        SystemCommands.whoami(),
    ):
        assert cmd.argv[0] in {"cat", "uname", "nproc", "free", "df", "id"}
    with pytest.raises(UnsafeCommandError):
        SystemCommands.which("python3")


class Recorder:
    def __init__(self):
        self.commands = []

    def run(self, command):
        from app.ssh.result import CommandResult
        from app.utils.time import utcnow

        self.commands.append(command)
        now = utcnow()
        return CommandResult(
            command=command.render(),
            exit_code=0,
            stdout="",
            stderr="",
            started_at=now,
            completed_at=now,
            duration_seconds=0.0,
        )

    def upload(self, *a, **k):
        return 0

    def read_file(self, *a, **k):
        return ""

    def close(self):
        pass


def _ctx(runtime="PODMAN"):
    layout = RemoteLayout("/opt/scarlet", "customer-api")
    return RuntimeContext(
        executor=Recorder(),
        host=HostInfo(name="h", runtime_type=runtime, base_path="/opt/scarlet"),
        application_code="customer-api",
        layout=layout,
    )


def _desired():
    return DesiredApplicationState(
        application_code="customer-api",
        version="1.2.3",
        image="company/customer-api:1.2.3",
        manifest={
            "deployment": {"restart_policy": "unless-stopped", "stop_grace_period": 10},
            "resources": {"cpu": "500m", "memory": "512Mi"},
        },
        ports=("8080:8080",),
        volumes=("/opt/scarlet/applications/customer-api/shared/data/data:/var/lib/app",),
        health=HealthSpec(),
    )


def test_podman_run_args_are_safe_and_labelled():
    adapter = PodmanRuntimeAdapter()
    ctx = _ctx()
    args = adapter._run_args(ctx, _desired())
    assert args[0:2] == ["run", "-d"]
    assert "--label" in args and "scarlet.version=1.2.3" in args
    assert "--env-file" in args and ctx.layout.env_file in args
    assert "-p" in args and "8080:8080" in args
    assert any(a.endswith(":Z") for a in args)  # SELinux relabel for podman volumes
    assert "--memory" in args and "512m" in args
    assert "--cpus" in args and "0.5" in args
    assert args[-1] == "company/customer-api:1.2.3"
    cmd = RemoteCommand(("podman", *args), "runtime.podman.run")
    assert "$(" not in cmd.render()


def test_docker_adapter_does_not_relabel():
    args = DockerRuntimeAdapter()._run_args(_ctx("DOCKER"), _desired())
    assert not any(a.endswith(":Z") for a in args)


def test_logs_since_validation():
    adapter = PodmanRuntimeAdapter()
    with pytest.raises(ValidationError):
        adapter.logs(_ctx(), lines=10, since="10m; id")
    with pytest.raises(ValidationError):
        adapter.logs(_ctx(), lines=999999)


def test_runtime_factory():
    assert RuntimeFactory.get("podman").runtime_type.value == "PODMAN"
    assert set(RuntimeFactory.supported()) == {"DOCKER", "PODMAN", "KUBERNETES"}
    from app.errors import RuntimeNotSupportedError

    with pytest.raises(RuntimeNotSupportedError):
        RuntimeFactory.get("LXC")


def test_remote_layout_paths():
    layout = RemoteLayout("/opt/scarlet", "customer-api")
    assert layout.release_dir("1.0.0") == "/opt/scarlet/applications/customer-api/releases/1.0.0"
    assert layout.current_link.endswith("/customer-api/current")
    with pytest.raises(ValidationError):
        layout.release_dir("../x")
    with pytest.raises(ValidationError):
        RemoteLayout("/opt/scarlet", "Bad Code")

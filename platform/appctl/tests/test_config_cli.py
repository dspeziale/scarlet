from __future__ import annotations

from pathlib import Path

import pytest
from fakes import write_app

from appctl import cli
from appctl.audit import current_actor
from appctl.config import load_config, parse_env_file, resolve_app_dir, validate_tag
from appctl.errors import EXIT_USAGE, UsageError
from appctl.state import DeploymentRecord, StateStore, fmt_ts


def test_parse_env_file(tmp_path: Path):
    f = tmp_path / "x.env"
    f.write_text("# commento\nA=1\nB=\"due parole\"\nC='tre'\nD = spazi \n\nINVALIDA\n")
    assert parse_env_file(f) == {"A": "1", "B": "due parole", "C": "tre", "D": "spazi"}
    assert parse_env_file(tmp_path / "missing.env") == {}


def test_load_config_defaults(app_dir: Path):
    cfg = load_config(app_dir)
    assert cfg.name == "scarlet"
    assert cfg.health_url == "http://127.0.0.1:8080/health"
    assert cfg.app_container == "scarlet-app"
    assert cfg.image_ref("git-abc") == "registry.test/ised/scarlet:git-abc"
    assert cfg.registry_host == "registry.test"
    assert cfg.compose_env("img")["APP_DIR"] == str(app_dir)


@pytest.mark.parametrize(
    "overrides,fragment",
    [
        ({"APP_NAME": "Bad_Name"}, "APP_NAME"),
        ({"APP_ENVIRONMENT": "staging"}, "APP_ENVIRONMENT"),
        ({"PULL_POLICY": "never"}, "PULL_POLICY"),
        ({"IMAGE_REPOSITORY": ""}, "obbligatorie"),
    ],
)
def test_load_config_validation(tmp_path: Path, overrides, fragment):
    d = tmp_path / "bad"
    write_app(d, **overrides)
    with pytest.raises(UsageError) as exc:
        load_config(d)
    assert fragment in exc.value.message


def test_missing_manifest(tmp_path: Path):
    with pytest.raises(UsageError):
        load_config(tmp_path)


@pytest.mark.parametrize("tag", ["git-abc123", "v1.2.3", "1.0.0-rc.1"])
def test_valid_tags(tag):
    assert validate_tag(tag) == tag


@pytest.mark.parametrize("tag", ["", "-x", "a b", "tag;rm", "../etc", "x" * 200])
def test_invalid_tags(tag):
    with pytest.raises(UsageError):
        validate_tag(tag)


def test_resolve_app_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("appctl.config.APPS_ROOT", tmp_path)
    with pytest.raises(UsageError):
        resolve_app_dir(None, None)
    write_app(tmp_path / "one")
    assert resolve_app_dir(None, None) == tmp_path / "one"
    write_app(tmp_path / "two")
    with pytest.raises(UsageError) as exc:
        resolve_app_dir(None, None)
    assert "one, two" in (exc.value.hint or "")
    assert resolve_app_dir("two", None) == tmp_path / "two"
    assert resolve_app_dir(None, str(tmp_path / "x")) == (tmp_path / "x").resolve()
    monkeypatch.setenv("APPCTL_APP", "one")
    assert resolve_app_dir(None, None) == tmp_path / "one"
    with pytest.raises(UsageError):
        resolve_app_dir("Bad!", None)


def test_actor_precedence(monkeypatch):
    monkeypatch.delenv("APPCTL_ACTOR", raising=False)
    monkeypatch.delenv("SUDO_USER", raising=False)
    assert current_actor()
    monkeypatch.setenv("SUDO_USER", "mario")
    assert current_actor() == "mario"
    monkeypatch.setenv("APPCTL_ACTOR", "github-actions:anna")
    assert current_actor() == "github-actions:anna"


def test_state_store_roundtrip(tmp_path: Path):
    st = StateStore(tmp_path / "state")
    a = DeploymentRecord("scarlet", "production", "img:a", "a", version="1")
    b = DeploymentRecord("scarlet", "production", "img:b", "b", version="2")
    st.set_current(a)
    assert st.current().tag == "a" and st.previous() is None
    st.set_current(b)
    assert st.current().tag == "b" and st.previous().tag == "a"
    st.set_current(b)  # stesso tag: previous invariato
    assert st.previous().tag == "a"
    st.append_history(a)
    st.append_history(b)
    assert [r.tag for r in st.history()] == ["a", "b"]
    assert [r.tag for r in st.history(limit=1)] == ["b"]
    # riga corrotta ignorata
    with st.history_file.open("a") as fh:
        fh.write("{not json\n")
    assert len(st.history()) == 2
    # campi sconosciuti ignorati (compatibilita' futura)
    rec = DeploymentRecord.from_dict({**a.to_dict(), "nuovo_campo": 1})
    assert rec.tag == "a"


def test_fmt_ts():
    assert fmt_ts("0001-01-01T00:00:00Z") == "-"
    assert fmt_ts(None) == "-"
    assert fmt_ts("2026-09-30T08:42:11.123456789Z").startswith("2026-09-30")
    assert fmt_ts("not a date") == "not a date"


def test_cli_usage_errors(app_dir: Path, capsys, monkeypatch):
    monkeypatch.delenv("SUDO_USER", raising=False)
    assert cli.main(["--app-dir", str(app_dir / "missing"), "status"]) == EXIT_USAGE
    assert "manifest non trovato" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["--app-dir", str(app_dir)])  # comando mancante


def test_cli_actor_ignored_under_sudo(app_dir: Path, monkeypatch, capsys):
    monkeypatch.setenv("SUDO_USER", "mario")
    parser = cli.build_parser()
    args = parser.parse_args(["--app-dir", str(app_dir), "--actor", "fake", "config"])
    ctx = cli.build_context(args)
    assert ctx.actor == "mario"
    assert "--actor ignorato" in capsys.readouterr().err
    monkeypatch.delenv("SUDO_USER")
    args = parser.parse_args(
        ["--app-dir", str(app_dir), "--actor", "github-actions:anna", "config"]
    )
    assert cli.build_context(args).actor == "github-actions:anna"


def test_cli_config_command(app_dir: Path, capsys, monkeypatch):
    monkeypatch.delenv("SUDO_USER", raising=False)
    assert cli.main(["--app-dir", str(app_dir), "config"]) == 0
    out = capsys.readouterr().out
    assert "APP_NAME" in out and "scarlet" in out
    assert cli.main(["--app-dir", str(app_dir), "--json", "config"]) == 0
    import json

    assert json.loads(capsys.readouterr().out)["APP_NAME"] == "scarlet"

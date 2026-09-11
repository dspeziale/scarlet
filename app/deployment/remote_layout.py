"""Predictable remote filesystem layout for an application on a target host.

    <base>/applications/<app>/
        releases/<version>/       immutable extracted release
        current -> releases/<v>   atomic symlink to the active release
        shared/config|data|logs   persistent data shared across releases
        staging/                  uploads and temporary extraction
        backups/
"""

from __future__ import annotations

from dataclasses import dataclass

from app.security.validators import validate_app_code, validate_version
from app.ssh.command import join_remote, validate_remote_path


@dataclass(frozen=True)
class RemoteLayout:
    base_path: str
    application_code: str

    def __post_init__(self) -> None:
        validate_remote_path(self.base_path, self.base_path)
        validate_app_code(self.application_code)

    @property
    def applications_dir(self) -> str:
        return join_remote(self.base_path, "applications")

    @property
    def app_dir(self) -> str:
        return join_remote(self.base_path, "applications", self.application_code)

    @property
    def releases_dir(self) -> str:
        return join_remote(self.base_path, "applications", self.application_code, "releases")

    @property
    def current_link(self) -> str:
        return join_remote(self.base_path, "applications", self.application_code, "current")

    @property
    def shared_dir(self) -> str:
        return join_remote(self.base_path, "applications", self.application_code, "shared")

    @property
    def shared_config_dir(self) -> str:
        return join_remote(self.base_path, "applications", self.application_code, "shared", "config")

    @property
    def shared_data_dir(self) -> str:
        return join_remote(self.base_path, "applications", self.application_code, "shared", "data")

    @property
    def shared_logs_dir(self) -> str:
        return join_remote(self.base_path, "applications", self.application_code, "shared", "logs")

    @property
    def staging_dir(self) -> str:
        return join_remote(self.base_path, "applications", self.application_code, "staging")

    @property
    def backups_dir(self) -> str:
        return join_remote(self.base_path, "applications", self.application_code, "backups")

    @property
    def env_file(self) -> str:
        return join_remote(self.base_path, "applications", self.application_code, "shared", "config", "scarlet.env")

    def release_dir(self, version: str) -> str:
        validate_version(version)
        return join_remote(self.base_path, "applications", self.application_code, "releases", version)

    def release_tmp_dir(self, version: str, token: str) -> str:
        validate_version(version)
        return join_remote(
            self.base_path, "applications", self.application_code, "staging", f"{version}.{token}.extract"
        )

    def staging_package(self, version: str, token: str) -> str:
        validate_version(version)
        return join_remote(
            self.base_path, "applications", self.application_code, "staging", f"{version}.{token}.scarlet.tar.gz"
        )

    def all_dirs(self) -> list[str]:
        return [
            self.app_dir,
            self.releases_dir,
            self.shared_dir,
            self.shared_config_dir,
            self.shared_data_dir,
            self.shared_logs_dir,
            self.staging_dir,
            self.backups_dir,
        ]

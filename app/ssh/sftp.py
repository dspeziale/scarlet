"""SFTP file transfer with temporary file + atomic rename and size verification."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from pathlib import PurePosixPath

from app.errors import FileTransferError


def upload_file(
    client,
    local_path: str,
    remote_path: str,
    progress: Callable[[int, int], None] | None = None,
) -> int:
    """Upload ``local_path`` to ``remote_path`` through the client's SFTP session.

    The file is written to ``<remote_path>.part`` and renamed only when the
    transferred size matches the local size. Callers must additionally verify
    the SHA-256 checksum with a remote ``sha256sum`` command.
    """
    sftp = client.sftp()
    local_size = os.path.getsize(local_path)
    remote = PurePosixPath(remote_path)
    part_path = str(remote) + ".part"
    try:
        try:
            sftp.stat(str(remote.parent))
        except OSError as exc:
            raise FileTransferError(f"Remote directory {remote.parent} does not exist.") from exc
        sftp.put(local_path, part_path, callback=progress, confirm=True)
        attrs = sftp.stat(part_path)
        if attrs.st_size != local_size:
            try:
                sftp.remove(part_path)
            finally:
                pass
            raise FileTransferError(
                "Transferred size does not match local size.",
                details={"local_size": local_size, "remote_size": attrs.st_size},
            )
        sftp.chmod(part_path, stat.S_IRUSR | stat.S_IWUSR)
        try:
            sftp.remove(str(remote))
        except OSError:
            pass
        sftp.rename(part_path, str(remote))
    except FileTransferError:
        raise
    except OSError as exc:
        raise FileTransferError(f"SFTP upload failed: {exc}") from exc
    return local_size


def download_file(client, remote_path: str, local_path: str) -> int:
    sftp = client.sftp()
    try:
        sftp.get(remote_path, local_path)
    except OSError as exc:
        raise FileTransferError(f"SFTP download failed: {exc}") from exc
    return os.path.getsize(local_path)

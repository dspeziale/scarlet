"""Package upload and release endpoints."""

from __future__ import annotations

from flask import request

from app.api import api
from app.api.responses import created, list_params, ok, paged, parse_bool
from app.errors import ValidationError
from app.repositories import PackageRepository
from app.security.rbac import get_current_user, require_permission
from app.services.package_service import PackageService


@api.get("/packages")
@require_permission("package.view")
def list_packages():
    params = list_params(default_sort="created_at")
    page = PackageRepository().list(
        **params,
        status=(request.args.get("status") or "").upper() or None,
        application_id=request.args.get("application_id") or None,
    )
    return paged(page)


@api.get("/packages/<int:package_id>")
@require_permission("package.view")
def get_package(package_id: int):
    package = PackageRepository().get_or_404(package_id, "Package")
    data = package.to_dict()
    data["manifest"] = package.manifest
    return ok(data)


@api.post("/packages/upload")
@require_permission("package.upload")
def upload_package():
    """Multipart upload: field ``file`` (the .scarlet.tar.gz), optional ``application_id``, ``release_notes``, ``auto_release``."""
    file = request.files.get("file")
    if file is None or not file.filename:
        raise ValidationError(
            "No file uploaded. Use multipart/form-data with a 'file' field.",
            errors={"file": ["Required."]},
        )
    application_id = request.form.get("application_id") or None
    try:
        application_id = int(application_id) if application_id else None
    except ValueError as exc:
        raise ValidationError("application_id must be an integer.") from exc
    package = PackageService().upload(
        file.stream,
        file.filename,
        user=get_current_user(),
        application_id=application_id,
        release_notes=PackageService.validate_release_notes(request.form.get("release_notes")),
        auto_release=parse_bool(request.form.get("auto_release", "true"), default=True),
    )
    data = package.to_dict()
    data["manifest"] = package.manifest
    return created(data)


@api.post("/packages/<int:package_id>/release")
@require_permission("package.upload")
def release_package(package_id: int):
    package = PackageRepository().get_or_404(package_id, "Package")
    version = PackageService().release(
        package,
        user=get_current_user(),
        release_notes=PackageService.validate_release_notes(
            (request.get_json(silent=True) or {}).get("release_notes")
        ),
    )
    return created(version.to_dict())


@api.post("/packages/<int:package_id>/revalidate")
@require_permission("package.upload")
def revalidate_package(package_id: int):
    package = PackageRepository().get_or_404(package_id, "Package")
    if package.version_id is not None:
        raise ValidationError(
            "Released packages are immutable; use integrity verification on the version instead."
        )
    return ok(PackageService().validate(package).to_dict())


@api.delete("/packages/<int:package_id>")
@require_permission("package.delete")
def delete_package(package_id: int):
    package = PackageRepository().get_or_404(package_id, "Package")
    PackageService().delete_invalid(package, user=get_current_user())
    return ok({"deleted": True})

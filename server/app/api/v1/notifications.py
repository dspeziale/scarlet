"""
/api/v1/tenant/notifications — per-tenant Telegram + Gmail settings and a test send.

TenantAdmin manages its own tenant; SuperAdmin may target any via ?tenant_id=.
Secrets (bot token, app password) are write-only — never returned.
"""

from flask import g, jsonify, request

from app.api.v1 import api_v1_bp
from app.auth.rbac import require_tenant_admin_or_above
from app.services.tenant_service import TenantService
from app.services.notification_service import NotificationService

_tsvc = TenantService()


def _resolve_tenant_id():
    user = g.current_user
    if user.is_superadmin:
        body = request.get_json(silent=True) or {}
        return request.args.get("tenant_id") or body.get("tenant_id") or user.tenant_id
    return user.tenant_id


@api_v1_bp.get("/tenant/notifications")
@require_tenant_admin_or_above
def get_notifications():
    tenant_id = _resolve_tenant_id()
    if not tenant_id:
        return jsonify(error="validation_error", message="tenant_id required"), 400
    try:
        tenant = _tsvc.get_tenant(tenant_id)
    except ValueError as e:
        return jsonify(error="not_found", message=str(e)), 404
    return jsonify(tenant.notification_settings_dict()), 200


@api_v1_bp.put("/tenant/notifications")
@require_tenant_admin_or_above
def update_notifications():
    body = request.get_json(silent=True) or {}
    tenant_id = _resolve_tenant_id()
    if not tenant_id:
        return jsonify(error="validation_error", message="tenant_id required"), 400

    # Only forward known fields that are actually present.
    fields = {k: body[k] for k in TenantService.NOTIFY_FIELDS if k in body}
    # Treat empty strings for secrets as "leave unchanged".
    for secret in ("telegram_bot_token", "gmail_app_password"):
        if secret in fields and fields[secret] == "":
            del fields[secret]

    try:
        tenant = _tsvc.update_notifications(tenant_id, **fields)
    except ValueError as e:
        return jsonify(error="not_found", message=str(e)), 404
    return jsonify(tenant.notification_settings_dict()), 200


@api_v1_bp.post("/tenant/notifications/test")
@require_tenant_admin_or_above
def test_notification():
    tenant_id = _resolve_tenant_id()
    if not tenant_id:
        return jsonify(error="validation_error", message="tenant_id required"), 400
    try:
        tenant = _tsvc.get_tenant(tenant_id)
    except ValueError as e:
        return jsonify(error="not_found", message=str(e)), 404

    results = NotificationService().notify_tenant(
        tenant,
        subject="SOC Seattle — Test notifica",
        message="Questo è un messaggio di test dalle impostazioni di notifica del tenant.",
    )
    return jsonify({"results": results}), 200

"""
/api/v1/accounting  — resource usage accounting.
"""

from datetime import date

from flask import g, jsonify, request

from app.api.v1 import api_v1_bp
from app.auth.rbac import require_role, TENANT_ADMIN, SUPERADMIN
from app.services.accounting_service import AccountingService

_svc = AccountingService()


@api_v1_bp.get("/accounting/daily")
@require_role(SUPERADMIN, TENANT_ADMIN)
def daily_summary():
    user = g.current_user
    tenant_id = request.args.get("tenant_id") if user.is_superadmin else user.tenant_id
    date_str = request.args.get("date", date.today().isoformat())
    try:
        period = date.fromisoformat(date_str)
    except ValueError:
        return jsonify(error="validation_error", message="Invalid date format (YYYY-MM-DD)"), 400

    summary = _svc.get_daily_summary(tenant_id, period)
    return jsonify(summary), 200


@api_v1_bp.get("/accounting/monthly")
@require_role(SUPERADMIN, TENANT_ADMIN)
def monthly_summary():
    user = g.current_user
    tenant_id = request.args.get("tenant_id") if user.is_superadmin else user.tenant_id
    today = date.today()
    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))
    summary = _svc.get_monthly_summary(tenant_id, year, month)
    return jsonify(summary), 200


@api_v1_bp.get("/accounting/usage")
@require_role(SUPERADMIN, TENANT_ADMIN)
def usage_list():
    user = g.current_user
    tenant_id = request.args.get("tenant_id") if user.is_superadmin else user.tenant_id
    probe_id = request.args.get("probe_id")
    limit = int(request.args.get("limit", 30))
    rows = _svc.list_usage(tenant_id, probe_id=probe_id, limit=limit)
    return jsonify([r.to_dict() for r in rows]), 200

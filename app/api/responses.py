"""Consistent JSON response envelope and request parsing helpers."""

from __future__ import annotations

from typing import Any

from flask import Response, jsonify, request

from app.errors import ValidationError
from app.repositories.base import Page


def ok(data: Any = None, status: int = 200, **meta: Any) -> tuple[Response, int]:
    payload: dict[str, Any] = {"ok": True, "data": data}
    if meta:
        payload["meta"] = meta
    return jsonify(payload), status


def accepted(data: Any = None, **meta: Any) -> tuple[Response, int]:
    return ok(data, 202, **meta)


def created(data: Any = None) -> tuple[Response, int]:
    return ok(data, 201)


def error(
    code: str, message: str, status: int = 400, errors: dict[str, Any] | None = None, **extra: Any
) -> tuple[Response, int]:
    body: dict[str, Any] = {"code": code, "message": message}
    if errors:
        body["errors"] = errors
    body.update(extra)
    return jsonify({"ok": False, "error": body}), status


def paged(page: Page, serializer=None) -> tuple[Response, int]:
    data = page.to_dict(serializer)
    return (
        jsonify(
            {
                "ok": True,
                "data": data["items"],
                "meta": {"pagination": data["pagination"], "filters": data["filters"]},
            }
        ),
        200,
    )


def json_body(required: bool = True) -> dict[str, Any]:
    if not request.data and not request.form:
        if required:
            raise ValidationError("A JSON body is required.")
        return {}
    if request.is_json:
        data = request.get_json(silent=True)
        if data is None:
            raise ValidationError("Malformed JSON body.")
        if not isinstance(data, dict):
            raise ValidationError("JSON body must be an object.")
        return data
    if request.form:
        return {k: v for k, v in request.form.items()}
    raise ValidationError("Content-Type must be application/json.")


def list_params(default_sort: str = "id", max_per_page: int = 200) -> dict[str, Any]:
    args = request.args
    try:
        page = max(1, int(args.get("page", 1)))
        per_page = min(max(1, int(args.get("per_page", 25))), max_per_page)
    except ValueError as exc:
        raise ValidationError("page and per_page must be integers.") from exc
    direction = args.get("direction", "desc").lower()
    if direction not in {"asc", "desc"}:
        raise ValidationError("direction must be asc or desc.")
    search = (args.get("search") or "").strip()[:200]
    return {
        "page": page,
        "per_page": per_page,
        "sort": args.get("sort", default_sort)[:64],
        "direction": direction,
        "search": search or None,
    }


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

"""OpenAPI 3 document generated from the registered routes + Swagger UI."""

from __future__ import annotations

import re
from typing import Any

from flask import Response, current_app, jsonify, render_template, url_for

from app.api import api
from app.errors import NotFoundError
from app.security.rbac import login_required_any

TAG_FOR_PREFIX = {
    "auth": "Authentication",
    "hosts": "Hosts",
    "host-groups": "Host groups",
    "environments": "Environments",
    "applications": "Applications",
    "packages": "Packages",
    "deployments": "Deployments",
    "operations": "Operations",
    "jobs": "Jobs",
    "audit": "Audit",
    "security-events": "Audit",
    "users": "Users & roles",
    "roles": "Users & roles",
    "permissions": "Users & roles",
    "settings": "System",
    "notifications": "System",
    "dashboard": "Dashboard",
    "meta": "System",
    "health": "Monitoring",
    "ready": "Monitoring",
    "metrics": "Monitoring",
}

REQUEST_SCHEMAS: dict[str, dict[str, Any]] = {
    "api.login": {
        "type": "object",
        "required": ["username", "password"],
        "properties": {
            "username": {"type": "string"},
            "password": {"type": "string", "format": "password"},
            "remember": {"type": "boolean"},
        },
    },
    "api.create_host": {
        "type": "object",
        "required": ["name", "hostname", "ssh_username", "environment"],
        "properties": {
            "name": {"type": "string"},
            "hostname": {"type": "string"},
            "ip_address": {"type": "string"},
            "ssh_port": {"type": "integer", "default": 22},
            "ssh_username": {"type": "string"},
            "environment": {"type": "string", "enum": ["DEV", "PROD"]},
            "runtime_type": {"type": "string", "enum": ["DOCKER", "PODMAN", "KUBERNETES", "NONE"]},
            "kubernetes_namespace": {"type": "string"},
            "description": {"type": "string"},
            "group_ids": {"type": "array", "items": {"type": "integer"}},
        },
    },
    "api.set_credential": {
        "type": "object",
        "required": ["credential_type", "secret"],
        "properties": {
            "credential_type": {
                "type": "string",
                "enum": ["PASSWORD", "PRIVATE_KEY", "KUBECONFIG"],
            },
            "secret": {"type": "string", "format": "password"},
            "passphrase": {"type": "string", "format": "password"},
            "username": {"type": "string"},
        },
    },
    "api.approve_host_key": {
        "type": "object",
        "required": ["fingerprint"],
        "properties": {"fingerprint": {"type": "string", "example": "SHA256:..."}},
    },
    "api.create_application": {
        "type": "object",
        "required": ["name", "code", "runtime_type"],
        "properties": {
            "name": {"type": "string"},
            "code": {"type": "string", "pattern": "^[a-z][a-z0-9-]*$"},
            "runtime_type": {"type": "string", "enum": ["DOCKER", "PODMAN", "KUBERNETES"]},
            "description": {"type": "string"},
            "owner": {"type": "string"},
            "default_port": {"type": "integer"},
            "healthcheck_type": {"type": "string"},
            "healthcheck_url": {"type": "string"},
            "allow_hooks": {"type": "boolean"},
            "allowed_environments": {"type": "array", "items": {"type": "string"}},
            "allowed_runtimes": {"type": "array", "items": {"type": "string"}},
        },
    },
    "api.create_deployment": {
        "type": "object",
        "required": ["application_id", "version_id", "host_ids"],
        "properties": {
            "application_id": {"type": "integer"},
            "version_id": {"type": "integer"},
            "host_ids": {"type": "array", "items": {"type": "integer"}},
            "host_group_id": {"type": "integer"},
            "strategy": {"type": "string", "enum": ["SEQUENTIAL", "PARALLEL"]},
            "reason": {"type": "string"},
            "confirmation": {
                "type": "string",
                "description": "Required for PROD: the configured confirmation phrase",
            },
            "auto_rollback": {"type": "boolean"},
        },
    },
    "api.preflight": {
        "type": "object",
        "required": ["application_id", "version_id", "host_ids"],
        "properties": {
            "application_id": {"type": "integer"},
            "version_id": {"type": "integer"},
            "host_ids": {"type": "array", "items": {"type": "integer"}},
            "remote": {"type": "boolean"},
        },
    },
    "api.rollback_application": {
        "type": "object",
        "required": ["host_id"],
        "properties": {
            "host_id": {"type": "integer"},
            "version_id": {"type": "integer"},
            "reason": {"type": "string"},
            "confirmation": {"type": "string"},
        },
    },
    "api.start_application": {
        "type": "object",
        "required": ["host_id"],
        "properties": {
            "host_id": {"type": "integer"},
            "reason": {"type": "string"},
            "confirmation": {"type": "string"},
        },
    },
    "api.stop_application": {
        "type": "object",
        "required": ["host_id"],
        "properties": {
            "host_id": {"type": "integer"},
            "reason": {"type": "string"},
            "confirmation": {"type": "string"},
        },
    },
    "api.restart_application": {
        "type": "object",
        "required": ["host_id"],
        "properties": {
            "host_id": {"type": "integer"},
            "reason": {"type": "string"},
            "confirmation": {"type": "string"},
        },
    },
    "api.create_user": {
        "type": "object",
        "required": ["username", "password", "roles"],
        "properties": {
            "username": {"type": "string"},
            "password": {"type": "string", "format": "password"},
            "roles": {"type": "array", "items": {"type": "string"}},
            "email": {"type": "string"},
            "full_name": {"type": "string"},
        },
    },
    "api.update_setting": {"type": "object", "required": ["value"], "properties": {"value": {}}},
    "api.update_configuration": {
        "type": "object",
        "required": ["entries"],
        "properties": {
            "entries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "string"},
                        "value_type": {"type": "string", "enum": ["CONFIG", "SECRET"]},
                        "description": {"type": "string"},
                    },
                },
            },
            "change_summary": {"type": "string"},
        },
    },
}


def build_openapi() -> dict[str, Any]:
    paths: dict[str, Any] = {}
    for rule in current_app.url_map.iter_rules():
        if not rule.rule.startswith("/api/") or rule.endpoint in {
            "api.openapi_json",
            "api.swagger_ui",
        }:
            continue
        path = re.sub(r"<(?:[a-z]+:)?([a-zA-Z_]+)>", r"{\1}", rule.rule)
        params = [
            {
                "name": name,
                "in": "path",
                "required": True,
                "schema": {"type": "integer" if f"<int:{name}>" in rule.rule else "string"},
            }
            for name in re.findall(r"<(?:[a-z]+:)?([a-zA-Z_]+)>", rule.rule)
        ]
        prefix = rule.rule.split("/")[2]
        view = current_app.view_functions.get(rule.endpoint)
        summary = (
            (view.__doc__ or rule.endpoint.split(".")[-1].replace("_", " ")).strip().splitlines()[0]
            if view
            else ""
        )
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            operation: dict[str, Any] = {
                "tags": [TAG_FOR_PREFIX.get(prefix, prefix.title())],
                "summary": summary,
                "operationId": f"{method.lower()}_{rule.endpoint.split('.')[-1]}",
                "parameters": params
                + (
                    [
                        {"name": "page", "in": "query", "schema": {"type": "integer"}},
                        {"name": "per_page", "in": "query", "schema": {"type": "integer"}},
                        {"name": "search", "in": "query", "schema": {"type": "string"}},
                        {"name": "sort", "in": "query", "schema": {"type": "string"}},
                        {
                            "name": "direction",
                            "in": "query",
                            "schema": {"type": "string", "enum": ["asc", "desc"]},
                        },
                    ]
                    if method == "GET" and rule.endpoint.split(".")[-1].startswith("list_")
                    else []
                ),
                "responses": {
                    "200": {
                        "description": "Success",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Envelope"}
                            }
                        },
                    },
                    "400": {
                        "description": "Validation error",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ErrorEnvelope"}
                            }
                        },
                    },
                    "401": {"description": "Authentication required"},
                    "403": {"description": "Forbidden (missing permission or PROD safety)"},
                    "404": {"description": "Not found"},
                    "409": {"description": "Conflict / concurrent operation"},
                    "429": {"description": "Rate limited"},
                },
                "security": (
                    []
                    if rule.endpoint in {"api.login", "api.health", "api.ready", "api.metrics"}
                    else [{"sessionCookie": []}, {"bearerToken": []}]
                ),
            }
            if method in {"POST", "PUT", "PATCH"}:
                schema = REQUEST_SCHEMAS.get(rule.endpoint, {"type": "object"})
                if rule.endpoint == "api.upload_package":
                    operation["requestBody"] = {
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "required": ["file"],
                                    "properties": {
                                        "file": {"type": "string", "format": "binary"},
                                        "application_id": {"type": "integer"},
                                        "release_notes": {"type": "string"},
                                        "auto_release": {"type": "boolean"},
                                    },
                                }
                            }
                        }
                    }
                else:
                    operation["requestBody"] = {"content": {"application/json": {"schema": schema}}}
            if method in {"POST"} and rule.endpoint.split(".")[-1] in {
                "create_deployment",
                "start_application",
                "stop_application",
                "restart_application",
                "test_connection",
                "discover",
                "rollback_application",
            }:
                operation["responses"]["202"] = {
                    "description": "Accepted: background job queued; poll the URL in meta.poll"
                }
            paths.setdefault(path, {})[method.lower()] = operation
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "SCARLET API",
            "version": current_app.config.get("APP_VERSION", "1.0.0"),
            "description": "System Container Application Release, Lifecycle & Environment Tool. All operational endpoints require authentication and the listed permission. Production targets additionally require `prod.*` permissions and typed confirmation.",
        },
        "servers": [{"url": "/"}],
        "components": {
            "securitySchemes": {
                "sessionCookie": {
                    "type": "apiKey",
                    "in": "cookie",
                    "name": current_app.config.get("SESSION_COOKIE_NAME", "scarlet_session"),
                },
                "bearerToken": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Personal API token (scl_...)",
                },
            },
            "schemas": {
                "Envelope": {
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean", "example": True},
                        "data": {},
                        "meta": {"type": "object"},
                    },
                },
                "ErrorEnvelope": {
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean", "example": False},
                        "error": {
                            "type": "object",
                            "properties": {
                                "code": {"type": "string"},
                                "message": {"type": "string"},
                                "errors": {"type": "object"},
                                "request_id": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
        "paths": dict(sorted(paths.items())),
    }


@api.get("/openapi.json")
@login_required_any
def openapi_json():
    if not current_app.config.get("SCARLET_API_DOCS_ENABLED", True):
        raise NotFoundError("API documentation is disabled.")
    return jsonify(build_openapi())


@api.get("/docs")
@login_required_any
def swagger_ui():
    if not current_app.config.get("SCARLET_API_DOCS_ENABLED", True):
        raise NotFoundError("API documentation is disabled.")
    return Response(
        render_template("system/api_docs.html", spec_url=url_for("api.openapi_json")),
        mimetype="text/html",
    )

"""HTTP security headers (OWASP secure headers) compatible with AdminLTE 4."""

from __future__ import annotations

from flask import Flask, Response, request

CDN_HOSTS = "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com"


def build_csp(asset_mode: str) -> str:
    script_src = "'self'"
    style_src = "'self' 'unsafe-inline'"  # AdminLTE/Bootstrap set inline styles on components
    font_src = "'self' data:"
    if asset_mode == "cdn":
        script_src += f" {CDN_HOSTS}"
        style_src += f" {CDN_HOSTS}"
        font_src += f" {CDN_HOSTS}"
    return (
        f"default-src 'self'; "
        f"script-src {script_src}; "
        f"style-src {style_src}; "
        f"font-src {font_src}; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "base-uri 'self'; "
        "object-src 'none'"
    )


def register_security_headers(app: Flask) -> None:
    csp = build_csp(app.config.get("SCARLET_ASSET_MODE", "cdn"))
    hsts_enabled = app.config.get("SCARLET_HSTS_ENABLED", False)

    @app.after_request
    def _apply(response: Response) -> Response:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if not request.path.startswith("/api/docs"):
            response.headers.setdefault("Content-Security-Policy", csp)
        if hsts_enabled and (request.is_secure or request.headers.get("X-Forwarded-Proto") == "https"):
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        if request.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

"""
/api/v1/auth  — login, refresh, logout, me, MFA setup.

---
tags: [auth]
"""

from datetime import datetime, timezone

from flask import jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from app.api.v1 import api_v1_bp
from app.services.auth_service import AuthService
from app import limiter

_svc = AuthService()


@api_v1_bp.post("/auth/login")
@limiter.limit("10 per minute")
def login():
    """
    Authenticate user and return JWT tokens.
    ---
    tags: [auth]
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            required: [email, password]
            properties:
              email: {type: string}
              password: {type: string}
    responses:
      200:
        description: Tokens issued
      401:
        description: Invalid credentials
    """
    body = request.get_json(silent=True) or {}
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")

    if not email or not password:
        return jsonify(error="validation_error", message="email and password required"), 400

    try:
        result = _svc.login(email, password)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="authentication_failed", message=str(e)), 401


@api_v1_bp.post("/auth/refresh")
@jwt_required(refresh=True)
def refresh():
    """Issue a new access token using the refresh token."""
    identity = get_jwt_identity()
    claims = get_jwt()
    result = _svc.refresh(identity, claims)
    return jsonify(result), 200


@api_v1_bp.delete("/auth/logout")
@jwt_required()
def logout():
    """Revoke the current access token."""
    jwt_data = get_jwt()
    _svc.logout(
        jti=jwt_data["jti"],
        token_type=jwt_data["type"],
        expires_at=datetime.fromtimestamp(jwt_data["exp"], tz=timezone.utc),
        user_id=get_jwt_identity(),
    )
    return jsonify(message="Logged out successfully"), 200


@api_v1_bp.get("/auth/me")
@jwt_required()
def me():
    """Return current user profile."""
    from flask import g
    from app.auth.rbac import jwt_required_with_user
    from app.extensions import db
    from app.models.user import User
    user = db.session.get(User, get_jwt_identity())
    if not user:
        return jsonify(error="not_found"), 404
    return jsonify(user.to_dict()), 200


@api_v1_bp.post("/auth/probe-login")
def probe_login():
    """
    Re-authentication for a registered probe.
    Returns a short-lived JWT the probe uses for heartbeat / task polling.
    """
    from app.extensions import db
    from app.models.probe import Probe
    from flask_jwt_extended import create_access_token

    body = request.get_json(silent=True) or {}
    probe_id = body.get("probe_id")
    if not probe_id:
        return jsonify(error="validation_error", message="probe_id required"), 400

    probe = db.session.get(Probe, probe_id)
    if not probe or not probe.enabled:
        return jsonify(error="authentication_failed", message="probe not found or disabled"), 401

    token = create_access_token(identity=f"probe:{probe_id}")
    return jsonify(access_token=token), 200


@api_v1_bp.post("/auth/mfa/setup")
@jwt_required()
def mfa_setup():
    """Generate MFA secret and return provisioning URI."""
    from app.auth.mfa import generate_mfa_secret, get_totp_uri
    from app.extensions import db
    from app.models.user import User

    user = db.session.get(User, get_jwt_identity())
    if not user:
        return jsonify(error="not_found"), 404

    secret = generate_mfa_secret()
    user.mfa_secret = secret
    db.session.commit()

    uri = get_totp_uri(secret, user.email)
    return jsonify({"totp_uri": uri, "secret": secret}), 200


@api_v1_bp.post("/auth/mfa/verify")
@jwt_required()
def mfa_verify():
    """Confirm MFA token and enable MFA for the account."""
    from app.auth.mfa import verify_totp
    from app.extensions import db
    from app.models.user import User

    user = db.session.get(User, get_jwt_identity())
    if not user or not user.mfa_secret:
        return jsonify(error="mfa_not_setup"), 400

    body = request.get_json(silent=True) or {}
    token = body.get("token", "")
    if not verify_totp(user.mfa_secret, token):
        return jsonify(error="invalid_totp_token"), 400

    user.mfa_enabled = True
    db.session.commit()
    return jsonify(message="MFA enabled"), 200

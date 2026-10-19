"""Users, login, lockout and server-side sessions."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from ..config import AuthConfig
from ..db import Database, iso, parse_iso, utcnow
from ..errors import BadRequest, Conflict, NotFound, ValidationFailed
from .passwords import hash_password, needs_rehash, password_problems, verify_password
from .rbac import Role

USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{1,62}$")
LANGUAGES = ("it", "en")


@dataclass(frozen=True)
class User:
    id: int
    username: str
    display_name: str
    email: str
    role: str
    active: bool
    must_change_password: bool
    language: str
    last_login_at: str | None
    created_at: str
    locked_until: str | None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "email": self.email,
            "role": self.role,
            "active": self.active,
            "must_change_password": self.must_change_password,
            "language": self.language,
            "last_login_at": self.last_login_at,
            "created_at": self.created_at,
            "locked": bool(self.locked_until and (parse_iso(self.locked_until) or utcnow()) > utcnow()),
        }


@dataclass(frozen=True)
class Session:
    id: str  # sha256 of the raw token
    user: User
    csrf_token: str
    created_at: str
    expires_at: str

    @property
    def ref(self) -> str:
        """Short non-secret reference used in the audit log."""
        return self.id[:12]


class LoginResult:
    OK = "ok"
    INVALID = "invalid"
    LOCKED = "locked"
    DISABLED = "disabled"


def _row_to_user(row: Any) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        email=row["email"],
        role=row["role"],
        active=bool(row["active"]),
        must_change_password=bool(row["must_change_password"]),
        language=row["language"],
        last_login_at=row["last_login_at"],
        created_at=row["created_at"],
        locked_until=row["locked_until"],
    )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class UserService:
    def __init__(self, db: Database, cfg: AuthConfig) -> None:
        self.db = db
        self.cfg = cfg

    # --- users -----------------------------------------------------------------
    def count(self) -> int:
        with self.db.connect() as c:
            return int(c.execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def list(self) -> list[User]:
        with self.db.connect() as c:
            return [_row_to_user(r) for r in c.execute("SELECT * FROM users ORDER BY username")]

    def get(self, user_id: int) -> User:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise NotFound("user not found")
        return _row_to_user(row)

    def get_by_username(self, username: str) -> User | None:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return _row_to_user(row) if row else None

    def validate_password(self, password: str, username: str) -> None:
        problems = password_problems(password, username=username, min_length=self.cfg.password_min_length)
        if problems:
            raise ValidationFailed(
                "password does not satisfy the policy",
                params={"problems": problems, "min_length": self.cfg.password_min_length},
            )

    def create(
        self,
        username: str,
        password: str,
        role: str,
        *,
        display_name: str = "",
        email: str = "",
        language: str = "it",
        must_change_password: bool = False,
    ) -> User:
        if not USERNAME_RE.match(username):
            raise ValidationFailed("invalid username", params={"field": "username"})
        if role not in {r.value for r in Role}:
            raise ValidationFailed("invalid role", params={"field": "role"})
        if language not in LANGUAGES:
            raise ValidationFailed("invalid language", params={"field": "language"})
        self.validate_password(password, username)
        now = iso()
        with self.db.transaction() as c:
            if c.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                raise Conflict("username already exists", params={"field": "username"})
            cur = c.execute(
                "INSERT INTO users(username, display_name, email, password_hash, role, active, "
                "must_change_password, language, created_at, updated_at) VALUES (?,?,?,?,?,1,?,?,?,?)",
                (username, display_name[:120], email[:200], hash_password(password), role,
                 int(must_change_password), language, now, now),
            )  # fmt: skip
            user_id = int(cur.lastrowid or 0)
        return self.get(user_id)

    def update(self, user_id: int, *, actor_id: int, **fields: Any) -> User:
        allowed = {"display_name", "email", "role", "active", "language"}
        changes = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if "role" in changes and changes["role"] not in {r.value for r in Role}:
            raise ValidationFailed("invalid role", params={"field": "role"})
        if "language" in changes and changes["language"] not in LANGUAGES:
            raise ValidationFailed("invalid language", params={"field": "language"})
        user = self.get(user_id)
        demoting = ("role" in changes and changes["role"] != Role.ADMIN) or changes.get("active") is False
        if user.role == Role.ADMIN and demoting:
            if user_id == actor_id:
                raise BadRequest("you cannot remove your own administrator access", params={"rule": "self"})
            self._ensure_other_admin(user_id)
        if not changes:
            return user
        sets = ", ".join(f"{k} = ?" for k in changes)
        values = [int(v) if isinstance(v, bool) else v for v in changes.values()]
        with self.db.transaction() as c:
            c.execute(f"UPDATE users SET {sets}, updated_at = ? WHERE id = ?", (*values, iso(), user_id))  # noqa: S608
            if changes.get("active") is False:
                c.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return self.get(user_id)

    def _ensure_other_admin(self, user_id: int) -> None:
        with self.db.connect() as c:
            n = c.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1 AND id != ?", (user_id,)
            ).fetchone()[0]
        if n == 0:
            raise BadRequest("at least one active administrator is required", params={"rule": "last_admin"})

    def delete(self, user_id: int, *, actor_id: int) -> User:
        user = self.get(user_id)
        if user_id == actor_id:
            raise BadRequest("you cannot delete your own account", params={"rule": "self"})
        if user.role == Role.ADMIN:
            self._ensure_other_admin(user_id)
        with self.db.transaction() as c:
            c.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return user

    def set_password(self, user_id: int, password: str, *, must_change: bool) -> None:
        user = self.get(user_id)
        self.validate_password(password, user.username)
        with self.db.transaction() as c:
            c.execute(
                "UPDATE users SET password_hash = ?, must_change_password = ?, failed_attempts = 0, "
                "locked_until = NULL, updated_at = ? WHERE id = ?",
                (hash_password(password), int(must_change), iso(), user_id),
            )
            c.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def change_own_password(self, user_id: int, current: str, new: str) -> None:
        with self.db.connect() as c:
            row = c.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row or not verify_password(row["password_hash"], current):
            raise ValidationFailed("current password is wrong", params={"field": "current_password"})
        if current == new:
            raise ValidationFailed("the new password must be different", params={"field": "new_password"})
        self.set_password(user_id, new, must_change=False)

    def unlock(self, user_id: int) -> None:
        with self.db.connect() as c:
            c.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?", (user_id,))

    # --- authentication --------------------------------------------------------
    def authenticate(self, username: str, password: str) -> tuple[str, User | None]:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row is None:
            verify_password(None, password)  # uniform timing
            return LoginResult.INVALID, None
        user = _row_to_user(row)
        locked_until = parse_iso(row["locked_until"])
        if locked_until and locked_until > utcnow():
            return LoginResult.LOCKED, user
        if not verify_password(row["password_hash"], password):
            attempts = row["failed_attempts"] + 1
            lock = None
            if attempts >= self.cfg.login_max_attempts:
                lock = iso(utcnow() + timedelta(minutes=self.cfg.lockout_minutes))
                attempts = 0
            with self.db.connect() as c:
                c.execute(
                    "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                    (attempts, lock, user.id),
                )
            return (LoginResult.LOCKED if lock else LoginResult.INVALID), user
        if not user.active:
            return LoginResult.DISABLED, user
        new_hash = hash_password(password) if needs_rehash(row["password_hash"]) else row["password_hash"]
        with self.db.connect() as c:
            c.execute(
                "UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login_at = ?, "
                "password_hash = ? WHERE id = ?",
                (iso(), new_hash, user.id),
            )
        return LoginResult.OK, self.get(user.id)

    # --- sessions --------------------------------------------------------------
    def create_session(self, user: User, ip: str, user_agent: str) -> tuple[str, Session]:
        token = secrets.token_urlsafe(32)
        sid = _token_hash(token)
        csrf = secrets.token_urlsafe(32)
        now = utcnow()
        expires = now + timedelta(hours=self.cfg.session_absolute_hours)
        with self.db.connect() as c:
            c.execute(
                "INSERT INTO sessions(id, user_id, csrf_token, created_at, last_seen_at, expires_at, ip, "
                "user_agent) VALUES (?,?,?,?,?,?,?,?)",
                (sid, user.id, csrf, iso(now), iso(now), iso(expires), ip[:64], user_agent[:300]),
            )
        return token, Session(sid, user, csrf, iso(now), iso(expires))

    def resolve_session(self, token: str) -> Session | None:
        if not token or len(token) > 200:
            return None
        sid = _token_hash(token)
        with self.db.connect() as c:
            row = c.execute(
                "SELECT s.id AS sid, s.csrf_token, s.created_at AS s_created, s.last_seen_at, s.expires_at, u.* "
                "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.id = ?",
                (sid,),
            ).fetchone()
            if not row:
                return None
            now = utcnow()
            last_seen = parse_iso(row["last_seen_at"]) or now
            expired = (parse_iso(row["expires_at"]) or now) <= now or (
                now - last_seen > timedelta(minutes=self.cfg.session_idle_minutes)
            )
            if expired or not row["active"]:
                c.execute("DELETE FROM sessions WHERE id = ?", (sid,))
                return None
            if (now - last_seen).total_seconds() > 30:
                c.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (iso(now), sid))
        return Session(row["sid"], _row_to_user(row), row["csrf_token"], row["s_created"], row["expires_at"])

    def delete_session(self, session_id: str) -> None:
        with self.db.connect() as c:
            c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def list_sessions(self, user_id: int) -> list[dict[str, Any]]:
        with self.db.connect() as c:
            rows = c.execute(
                "SELECT id, created_at, last_seen_at, expires_at, ip, user_agent FROM sessions "
                "WHERE user_id = ? ORDER BY last_seen_at DESC",
                (user_id,),
            ).fetchall()
        return [{**dict(r), "id": r["id"][:12]} for r in rows]

    def revoke_user_sessions(self, user_id: int, except_session: str | None = None) -> int:
        with self.db.connect() as c:
            cur = c.execute(
                "DELETE FROM sessions WHERE user_id = ? AND id != ?", (user_id, except_session or "")
            )
            return cur.rowcount

    def purge_expired_sessions(self) -> int:
        idle_cutoff = iso(utcnow() - timedelta(minutes=self.cfg.session_idle_minutes))
        with self.db.connect() as c:
            cur = c.execute(
                "DELETE FROM sessions WHERE expires_at <= ? OR last_seen_at <= ?", (iso(), idle_cutoff)
            )
            return cur.rowcount


def csrf_matches(expected: str, provided: str | None) -> bool:
    return bool(provided) and hmac.compare_digest(expected.encode(), (provided or "").encode())


# --- setup token (first run) ----------------------------------------------------
SETUP_TOKEN_KEY = "setup_token_hash"  # noqa: S105 - key name, not a secret


def new_setup_token(db: Database) -> str:
    token = secrets.token_urlsafe(18)
    db.set_state(SETUP_TOKEN_KEY, _token_hash(token))
    return token


def check_setup_token(db: Database, token: str | None) -> bool:
    stored = db.get_state(SETUP_TOKEN_KEY)
    if not stored or not token:
        return False
    return hmac.compare_digest(stored, _token_hash(token.strip()))

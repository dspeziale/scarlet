"""Notifications: in-app records, optional e-mail. Extensible through channels."""

from __future__ import annotations

import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage
from typing import Any

from flask import current_app

from app.config.logging import get_logger
from app.extensions import db
from app.models.enums import NotificationLevel
from app.models.notification import Notification
from app.models.user import User
from app.repositories import NotificationRepository
from app.utils.time import utcnow

log = get_logger(__name__)


class NotificationChannel(ABC):
    name = "abstract"

    @abstractmethod
    def send(self, notification: Notification, recipients: list[User]) -> None: ...


class InAppChannel(NotificationChannel):
    name = "in-app"

    def send(self, notification: Notification, recipients: list[User]) -> None:
        # notification row already persisted; nothing else to do
        return None


class EmailChannel(NotificationChannel):
    name = "email"

    def send(self, notification: Notification, recipients: list[User]) -> None:
        cfg = current_app.config
        if not cfg.get("SCARLET_MAIL_ENABLED") or not cfg.get("SCARLET_MAIL_SERVER"):
            return
        addresses = [u.email for u in recipients if u.email]
        if not addresses:
            return
        msg = EmailMessage()
        msg["Subject"] = f"[SCARLET] {notification.title}"
        msg["From"] = cfg.get("SCARLET_MAIL_FROM", "scarlet@localhost")
        msg["To"] = ", ".join(addresses)
        body = notification.message
        if notification.link:
            body += f"\n\n{notification.link}"
        msg.set_content(body)
        try:
            with smtplib.SMTP(cfg["SCARLET_MAIL_SERVER"], int(cfg.get("SCARLET_MAIL_PORT", 587)), timeout=15) as smtp:
                if cfg.get("SCARLET_MAIL_USE_TLS", True):
                    smtp.starttls()
                if cfg.get("SCARLET_MAIL_USERNAME"):
                    smtp.login(cfg["SCARLET_MAIL_USERNAME"], cfg.get("SCARLET_MAIL_PASSWORD", ""))
                smtp.send_message(msg)
            notification.email_sent = True
            db.session.commit()
        except (OSError, smtplib.SMTPException) as exc:
            log.warning("email notification failed: %s", exc)


class NotificationService:
    def __init__(self, channels: list[NotificationChannel] | None = None) -> None:
        self.channels = channels or [InAppChannel(), EmailChannel()]
        self.repo = NotificationRepository()

    def notify(
        self,
        event_type: str,
        title: str,
        message: str = "",
        *,
        level: NotificationLevel | str = NotificationLevel.INFO,
        link: str | None = None,
        user_ids: list[int] | None = None,
        permission: str | None = None,
        details: dict[str, Any] | None = None,
        email: bool = False,
    ) -> list[Notification]:
        """Create notifications for explicit users, users with a permission, or broadcast."""
        recipients: list[User] = []
        if user_ids:
            recipients = list(db.session.execute(db.select(User).where(User.id.in_(user_ids), User.is_active.is_(True))).scalars())
        elif permission:
            recipients = [u for u in db.session.execute(db.select(User).where(User.is_active.is_(True))).scalars() if u.has_permission(permission)]
        created: list[Notification] = []
        lvl = level.value if isinstance(level, NotificationLevel) else str(level)
        if recipients:
            for user in recipients:
                created.append(Notification(user_id=user.id, level=lvl, event_type=event_type, title=title[:255], message=message, link=link, created_at=utcnow(), details=details))
        else:
            created.append(Notification(user_id=None, level=lvl, event_type=event_type, title=title[:255], message=message, link=link, created_at=utcnow(), details=details))
        db.session.add_all(created)
        db.session.commit()
        for channel in self.channels:
            if isinstance(channel, EmailChannel) and not email:
                continue
            try:
                channel.send(created[0], recipients)
            except Exception as exc:  # noqa: BLE001 - notifications must never break operations
                log.warning("notification channel %s failed: %s", channel.name, exc)
        return created

    def list_for(self, user: User, unread_only: bool = False, limit: int = 50) -> list[Notification]:
        return self.repo.for_user(user.id, unread_only=unread_only, limit=limit)

    def unread_count(self, user: User) -> int:
        return self.repo.unread_count(user.id)

    def mark_read(self, user: User, notification_id: int | None = None) -> int:
        stmt = db.select(Notification).where((Notification.user_id == user.id) | (Notification.user_id.is_(None)), Notification.read.is_(False))
        if notification_id is not None:
            stmt = stmt.where(Notification.id == notification_id)
        rows = list(db.session.execute(stmt).scalars())
        for row in rows:
            if row.user_id is None:
                # broadcast: mark read only for this user by creating no per-user row; simply skip
                continue
            row.read = True
            row.read_at = utcnow()
        db.session.commit()
        return len(rows)


def notify_operators(event_type: str, title: str, message: str, *, level=NotificationLevel.INFO, link: str | None = None, details=None, email: bool = False) -> None:
    """Convenience used by background jobs (deployment result, health failure...)."""
    NotificationService().notify(event_type, title, message, level=level, link=link, permission="deployment.view", details=details, email=email)

"""
Per-tenant notifications: Telegram bot messages and Gmail (SMTP) e-mails.

Credentials live on the Tenant row (telegram_bot_token, gmail_address,
gmail_app_password). Recipients default to the probe's contact_email /
telegram_id, falling back to the tenant-level notify_email / telegram_chat_id.
"""

from __future__ import annotations

import json
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage

import structlog

log = structlog.get_logger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_GMAIL_HOST = "smtp.gmail.com"
_GMAIL_PORT = 465


class NotificationError(Exception):
    pass


class NotificationService:
    # ── Channels ─────────────────────────────────────────────────────────────

    def send_telegram(self, bot_token: str, chat_id: str, text: str) -> None:
        if not bot_token or not chat_id:
            raise NotificationError("telegram bot token and chat_id required")
        payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(
            _TELEGRAM_API.format(token=bot_token),
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status != 200:
                    raise NotificationError(f"telegram API error {resp.status}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:200]
            raise NotificationError(f"telegram API error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise NotificationError(f"telegram request failed: {exc}") from exc

    def send_email(
        self, gmail_address: str, app_password: str,
        to: str, subject: str, body: str,
    ) -> None:
        if not gmail_address or not app_password:
            raise NotificationError("gmail address and app password required")
        if not to:
            raise NotificationError("recipient email required")
        msg = EmailMessage()
        msg["From"] = gmail_address
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(_GMAIL_HOST, _GMAIL_PORT, context=ctx, timeout=20) as smtp:
                smtp.login(gmail_address, app_password)
                smtp.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            raise NotificationError(f"gmail send failed: {exc}") from exc

    # ── High-level ───────────────────────────────────────────────────────────

    def notify_tenant(
        self, tenant, subject: str, message: str, probe=None,
    ) -> dict:
        """
        Send a notification for a tenant over whatever channels are configured.
        Recipients prefer the probe's referente; fall back to tenant defaults.
        Returns a per-channel result dict; never raises (errors are reported).
        """
        results: dict[str, str] = {}
        if not getattr(tenant, "notify_enabled", False):
            return {"skipped": "notifications disabled for tenant"}

        email_to = (getattr(probe, "contact_email", None) if probe else None) or tenant.notify_email
        chat_id = (getattr(probe, "telegram_id", None) if probe else None) or tenant.telegram_chat_id

        if tenant.gmail_address and tenant.gmail_app_password and email_to:
            try:
                self.send_email(tenant.gmail_address, tenant.gmail_app_password,
                                email_to, subject, message)
                results["email"] = f"sent to {email_to}"
            except NotificationError as exc:
                results["email"] = f"error: {exc}"
                log.warning("notify_email_failed", tenant_id=tenant.id, error=str(exc))

        if tenant.telegram_bot_token and chat_id:
            try:
                text = f"<b>{subject}</b>\n{message}"
                self.send_telegram(tenant.telegram_bot_token, chat_id, text)
                results["telegram"] = f"sent to {chat_id}"
            except NotificationError as exc:
                results["telegram"] = f"error: {exc}"
                log.warning("notify_telegram_failed", tenant_id=tenant.id, error=str(exc))

        if not results:
            results["skipped"] = "no channel configured or no recipient"
        return results

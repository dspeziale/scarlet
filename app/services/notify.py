"""Outbound notification helpers: Telegram messages and Gmail (SMTP) emails.

Credentials are read from SystemSetting so they can be configured from the admin UI:
  TELEGRAM_BOT_TOKEN, GMAIL_USER, GMAIL_APP_PASSWORD
"""

import smtplib
import requests
from email.message import EmailMessage

from app.models.settings import SystemSetting


def send_telegram(chat_id, text, token=None):
    """Sends a Telegram message. Returns (ok, message)."""
    token = token or SystemSetting.get_value('TELEGRAM_BOT_TOKEN', '')
    if not token:
        return False, "Telegram bot token is not configured."
    if not chat_id:
        return False, "No Telegram chat id provided."
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
        if r.status_code == 200 and r.json().get("ok"):
            return True, "Telegram message sent."
        return False, f"Telegram API error: {r.text[:200]}"
    except Exception as e:
        return False, f"Telegram request failed: {e}"


def send_email(to_addr, subject, body, attachments=None):
    """Sends an email through Gmail SMTP. `attachments` is a list of
    (filename, bytes, mimetype) tuples. Returns (ok, message)."""
    user = SystemSetting.get_value('GMAIL_USER', '')
    password = SystemSetting.get_value('GMAIL_APP_PASSWORD', '')
    if not user or not password:
        return False, "Gmail account / app password is not configured."
    if not to_addr:
        return False, "No recipient address provided."

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content(body)

    for att in (attachments or []):
        try:
            filename, data, mimetype = att
            maintype, _, subtype = mimetype.partition('/')
            msg.add_attachment(data, maintype=maintype, subtype=subtype or 'octet-stream', filename=filename)
        except Exception:
            continue

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)
        return True, f"Email sent to {to_addr}."
    except Exception as e:
        return False, f"Email send failed: {e}"

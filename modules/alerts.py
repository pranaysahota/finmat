"""Sends Telegram alerts for critical rule triggers and delivers the daily digest email."""

import html
import logging
import os
import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

import requests

# Allow direct invocation (python modules/alerts.py) as well as import
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


_TELEGRAM_MAX_CHARS = 4096


def _split_message(text: str) -> list[str]:
    """Split text into chunks of at most _TELEGRAM_MAX_CHARS, breaking on newlines.

    Args:
        text: The full message text to split.

    Returns:
        List of chunks, each ≤ _TELEGRAM_MAX_CHARS characters.
    """
    if len(text) <= _TELEGRAM_MAX_CHARS:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in text.split("\n"):
        # +1 for the newline that will rejoin them
        line_len = len(line) + 1
        if current_len + line_len > _TELEGRAM_MAX_CHARS and current:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len

    if current:
        chunks.append("\n".join(current))

    return chunks


def _send_error_notification(error_summary: str) -> None:
    """Send a plain-text error notification to Telegram without HTML parsing.

    Used as a last-resort fallback when a normal send_message call fails with a
    400, so the user is actively notified on Telegram rather than only in logs.
    Sends directly via requests — never calls send_message to avoid recursion.

    Args:
        error_summary: Short description of the failure (no HTML).
    """
    url = TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text":    f"[Finance Agent] Telegram send failed: {error_summary}",
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception:
        pass  # Nothing left to do if the error notification itself fails


def send_message(text: str) -> bool:
    """Send an HTML-formatted message to the configured Telegram chat.

    If the message exceeds Telegram's 4096-character limit it is split into
    multiple messages on newline boundaries. Never raises an exception — any
    failure is printed and returns False so the caller can continue.

    If a chunk fails with HTTP 400 (e.g. a single line longer than the limit),
    a plain-text error notification is sent to Telegram so the failure is
    visible actively rather than only in server logs.

    Args:
        text: Message text. Supports Telegram HTML: <b>bold</b>, <i>italic</i>.
              Any user-generated or AI-generated content must be html.escaped before
              being embedded in the text.

    Returns:
        True if all chunks were delivered (HTTP 200), False if any chunk failed.
    """
    url = TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)
    chunks = _split_message(text)
    success = True
    for i, chunk in enumerate(chunks):
        payload = {
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       chunk,
            "parse_mode": "HTML",
        }
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
        except requests.HTTPError as exc:
            print(f"  ⚠️  Telegram send failed: {exc}")
            success = False
            if response.status_code == 400:
                try:
                    detail = response.json().get("description", "unknown 400 error")
                except Exception:
                    detail = "unknown 400 error"
                chunk_info = f"chunk {i + 1}/{len(chunks)}" if len(chunks) > 1 else "message"
                _send_error_notification(f"HTTP 400 on {chunk_info} — {detail}")
        except Exception as exc:
            print(f"  ⚠️  Telegram send failed: {exc}")
            success = False
    return success


def send_critical_alert(ticker: str, message: str) -> None:
    """Send an immediate CRITICAL alert to Telegram.

    Called by run_price_check() when a stop-loss or other CRITICAL rule
    is triggered. Formatted distinctively for urgency.

    Args:
        ticker:  The ticker symbol that triggered the alert e.g. "NVDA".
        message: The human-readable alert message from check_rules().
    """
    text = f"🔴 <b>CRITICAL — {html.escape(ticker)}</b>\n\n{html.escape(message)}"
    send_message(text)


def send_weekly_email(subject: str, body: str) -> None:
    """Send the daily digest as an HTML email via STARTTLS SMTP.

    All configuration is loaded from environment variables. If any required
    variable is missing or empty, logs a single warning and returns silently.
    Any SMTP error is logged and swallowed — never raises.

    Args:
        subject: Email subject line.
        body:    HTML email body.
    """
    sender    = os.environ.get("EMAIL_SENDER",     "")
    password  = os.environ.get("EMAIL_PASSWORD",   "")
    recipient = os.environ.get("EMAIL_RECIPIENT",  "")
    smtp_host = os.environ.get("EMAIL_SMTP_HOST",  "smtp.gmail.com")
    smtp_port = os.environ.get("EMAIL_SMTP_PORT",  "587")

    if not all([sender, password, recipient]):
        logging.warning(
            "send_weekly_email: EMAIL_SENDER, EMAIL_PASSWORD, or EMAIL_RECIPIENT "
            "not set — skipping email delivery."
        )
        return

    try:
        port = int(smtp_port)
    except ValueError:
        logging.warning("send_weekly_email: EMAIL_SMTP_PORT is not a valid integer — skipping.")
        return

    msg = MIMEText(body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = recipient

    try:
        with smtplib.SMTP(smtp_host, port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
    except Exception as exc:
        logging.error("send_weekly_email: SMTP error — %s", exc)


# HOW TO CREATE YOUR TELEGRAM BOT:
# 1. Open Telegram, search @BotFather, send /newbot
# 2. Follow prompts → copy the token into .env as TELEGRAM_BOT_TOKEN
# 3. Start a chat with your new bot
# 4. Visit: https://api.telegram.org/bot{YOUR_TOKEN}/getUpdates in a browser
# 5. Send any message to your bot, then refresh the URL
# 6. Find "id" under "chat" in the JSON — that is your TELEGRAM_CHAT_ID

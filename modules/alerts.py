"""Sends Telegram alerts for daily briefings, critical rule triggers, and portfolio events."""

import html
import logging
import os
import smtplib
import sys
from datetime import datetime, timedelta
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


def send_message(text: str) -> bool:
    """Send an HTML-formatted message to the configured Telegram chat.

    If the message exceeds Telegram's 4096-character limit it is split into
    multiple messages on newline boundaries. Never raises an exception — any
    failure is printed and returns False so the caller can continue.

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
    for chunk in chunks:
        payload = {
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       chunk,
            "parse_mode": "HTML",
        }
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
        except Exception as exc:
            print(f"  ⚠️  Telegram send failed: {exc}")
            success = False
    return success


def send_daily_briefing(
    portfolio_state:  dict,
    decision:         str,
    triggered_rules:  list,
    bucket_drift:     list,
    performance:      dict,
    macro_sentiment:  dict | None = None,
) -> None:
    """Format and send the full daily portfolio briefing to Telegram.

    Uses 🚨 header if any rules are triggered, otherwise 📊.
    Includes portfolio value, P&L, crypto weight, EUR/USD note, the Claude
    decision text, triggered rules and drift alerts (if any), and the
    inception performance footer. Macro theme sentiment is embedded in the
    decision text by the decision engine.

    Args:
        portfolio_state: Dict as returned by calculate_portfolio().
        decision:        Formatted briefing string from get_decision().
        triggered_rules: List of alert dicts from check_rules().
        bucket_drift:    List of drift alert dicts from check_bucket_drift().
        performance:     Dict from get_performance_summary(), or empty dict.
        macro_sentiment: Dict of {theme: sentiment_dict} from get_macro_sentiment().
                         Already incorporated into decision text; stored for reference.
    """
    now        = datetime.now()
    has_alerts = bool(triggered_rules)
    header_icon = "🚨" if has_alerts else "📊"

    total_value   = portfolio_state.get("total_value",   0.0)
    total_pnl_usd = portfolio_state.get("total_pnl_usd", 0.0)
    total_pnl_pct = portfolio_state.get("total_pnl_pct", 0.0)

    lines: list[str] = [
        f"{header_icon} <b>Finance Agent — Daily Briefing</b>",
        f"<i>{now.strftime('%A, %d %B %Y  %H:%M')}</i>",
        "",
        f"<b>Portfolio Value:</b> ${total_value:,.2f}",
        f"<b>Total P&L:</b> ${total_pnl_usd:+,.2f} ({total_pnl_pct:+.2f}%)",
        "",
        "<i>Portfolio priced in USD — gains/losses in EUR will vary with exchange rate at time of disposal</i>",
        "",
        "---",
        "",
        html.escape(decision),
    ]

    if triggered_rules:
        lines.append("")
        lines.append("⚠️ <b>Rules Triggered:</b>")
        for alert in triggered_rules:
            lines.append(html.escape(alert.get("message", "")))

    if bucket_drift:
        lines.append("")
        lines.append("📐 <b>Bucket Drift:</b>")
        for alert in bucket_drift:
            lines.append(html.escape(alert.get("message", "")))

    if performance:
        inception_pct = performance.get("since_inception_pct", 0.0)
        inception_usd = performance.get("since_inception_usd", 0.0)
        lines.append("")
        lines.append(
            f"📈 Since inception: {inception_pct:+.2f}% (${inception_usd:+,.2f})"
        )

    send_message("\n".join(lines))


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


def send_weekly_digest(performance: dict, portfolio_state: dict) -> None:
    """Format and send the weekly portfolio digest to Telegram.

    Includes portfolio value, best/worst performers, inception return,
    and the Irish CGT reminder footer.

    Args:
        performance:     Dict from get_performance_summary().
        portfolio_state: Dict as returned by calculate_portfolio().
    """
    now        = datetime.now()
    week_start = (now - timedelta(days=7)).strftime("%d %b")
    week_end   = now.strftime("%d %b %Y")

    total_value = portfolio_state.get("total_value", 0.0)

    lines: list[str] = [
        f"📅 <b>Weekly Digest — {week_start} – {week_end}</b>",
        "",
        f"<b>Portfolio value:</b> ${total_value:,.2f}",
    ]

    if performance:
        seven_day_pct  = performance.get("last_7_days_pct")
        inception_pct  = performance.get("since_inception_pct", 0.0)
        inception_usd  = performance.get("since_inception_usd", 0.0)
        best           = performance.get("best_performer")
        worst          = performance.get("worst_performer")

        if seven_day_pct is not None:
            lines.append(f"<b>This week:</b> {seven_day_pct:+.2f}%")

        if best:
            lines.append(f"<b>Best performer:</b>  {html.escape(str(best['ticker']))} ({best['pnl_pct']:+.2f}%)")
        if worst:
            lines.append(f"<b>Worst performer:</b> {html.escape(str(worst['ticker']))} ({worst['pnl_pct']:+.2f}%)")

        lines.append(
            f"<b>Total return since inception:</b> {inception_pct:+.2f}% (${inception_usd:+,.2f})"
        )

    lines.append("")
    lines.append(
        "🇮🇪 Irish CGT reminder: pay by 15 Dec for Jan–Nov disposals, "
        "31 Jan for December disposals. €1,270 annual exemption resets 1 Jan."
    )

    send_message("\n".join(lines))


def send_weekly_email(subject: str, body: str) -> None:
    """Send the weekly digest as an HTML email via STARTTLS SMTP.

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

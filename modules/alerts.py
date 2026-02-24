"""Sends Telegram alerts for daily briefings, critical rule triggers, and portfolio events."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

# Allow direct invocation (python modules/alerts.py) as well as import
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def send_message(text: str) -> bool:
    """Send a Markdown-formatted message to the configured Telegram chat.

    POSTs to the Telegram Bot API. Never raises an exception — any failure
    is printed and returns False so the caller can continue.

    Args:
        text: Message text. Supports Telegram Markdown: *bold*, _italic_, `code`.

    Returns:
        True if the message was delivered (HTTP 200), False otherwise.
    """
    url = TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       text,
        "parse_mode": "Markdown",
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except Exception as exc:
        print(f"  ⚠️  Telegram send failed: {exc}")
        return False


def send_daily_briefing(
    portfolio_state:  dict,
    decision:         str,
    triggered_rules:  list,
    bucket_drift:     list,
    performance:      dict,
) -> None:
    """Format and send the full daily portfolio briefing to Telegram.

    Uses 🚨 header if any rules are triggered, otherwise 📊.
    Includes portfolio value, P&L, crypto weight, EUR/USD note, the Claude
    decision text, triggered rules and drift alerts (if any), and the
    inception performance footer.

    Args:
        portfolio_state: Dict as returned by calculate_portfolio().
        decision:        Formatted briefing string from get_decision().
        triggered_rules: List of alert dicts from check_rules().
        bucket_drift:    List of drift alert dicts from check_bucket_drift().
        performance:     Dict from get_performance_summary(), or empty dict.
    """
    now        = datetime.now()
    has_alerts = bool(triggered_rules)
    header_icon = "🚨" if has_alerts else "📊"

    total_value   = portfolio_state.get("total_value",   0.0)
    total_pnl_usd = portfolio_state.get("total_pnl_usd", 0.0)
    total_pnl_pct = portfolio_state.get("total_pnl_pct", 0.0)
    crypto_weight = portfolio_state.get("crypto_weight", 0.0)

    lines: list[str] = [
        f"{header_icon} *Finance Agent — Daily Briefing*",
        f"_{now.strftime('%A, %d %B %Y  %H:%M')}_",
        "",
        f"*Portfolio Value:* ${total_value:,.2f}",
        f"*Total P&L:* ${total_pnl_usd:+,.2f} ({total_pnl_pct:+.2f}%)",
        f"*Crypto weight:* {crypto_weight:.1f}%",
        "",
        "_Portfolio priced in USD — gains/losses in EUR will vary with exchange rate at time of disposal_",
        "",
        "---",
        "",
        decision,
    ]

    if triggered_rules:
        lines.append("")
        lines.append("⚠️ *Rules Triggered:*")
        for alert in triggered_rules:
            lines.append(alert.get("message", ""))

    if bucket_drift:
        lines.append("")
        lines.append("📐 *Bucket Drift:*")
        for alert in bucket_drift:
            lines.append(alert.get("message", ""))

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
    text = f"🔴 *CRITICAL — {ticker}*\n\n{message}"
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
        f"📅 *Weekly Digest — {week_start} – {week_end}*",
        "",
        f"*Portfolio value:* ${total_value:,.2f}",
    ]

    if performance:
        seven_day_pct  = performance.get("last_7_days_pct")
        inception_pct  = performance.get("since_inception_pct", 0.0)
        inception_usd  = performance.get("since_inception_usd", 0.0)
        best           = performance.get("best_performer")
        worst          = performance.get("worst_performer")

        if seven_day_pct is not None:
            lines.append(f"*This week:* {seven_day_pct:+.2f}%")

        if best:
            lines.append(f"*Best performer:*  {best['ticker']} ({best['pnl_pct']:+.2f}%)")
        if worst:
            lines.append(f"*Worst performer:* {worst['ticker']} ({worst['pnl_pct']:+.2f}%)")

        lines.append(
            f"*Total return since inception:* {inception_pct:+.2f}% (${inception_usd:+,.2f})"
        )

    lines.append("")
    lines.append(
        "🇮🇪 Irish CGT reminder: pay by 15 Dec for Jan–Nov disposals, "
        "31 Jan for December disposals. €1,270 annual exemption resets 1 Jan."
    )

    send_message("\n".join(lines))


# HOW TO CREATE YOUR TELEGRAM BOT:
# 1. Open Telegram, search @BotFather, send /newbot
# 2. Follow prompts → copy the token into .env as TELEGRAM_BOT_TOKEN
# 3. Start a chat with your new bot
# 4. Visit: https://api.telegram.org/bot{YOUR_TOKEN}/getUpdates in a browser
# 5. Send any message to your bot, then refresh the URL
# 6. Find "id" under "chat" in the JSON — that is your TELEGRAM_CHAT_ID

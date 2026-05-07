"""Entry point — wires all modules together, runs daily CRITICAL price checks and daily digest on a schedule."""

import html
from datetime import datetime

import markdown as md
from zoneinfo import ZoneInfo

import schedule
import time

import modules.portfolio as portfolio_mod

from config import (
    CRYPTO_ACTIVE,
    PORTFOLIO,
    load_portfolio,
)
from modules.alerts import (
    send_critical_alert,
    send_daily_email,
)
from modules.decision_engine import (
    get_weekly_analysis,
    get_weekly_sell_recommendations,
)
from modules.history import (
    get_performance_summary,
    load_history,
    save_snapshot,
)
from modules.news_sentiment import get_all_sentiment, get_macro_sentiment
from modules.portfolio import (
    calculate_portfolio,
    check_bucket_drift,
    check_rules,
)
from modules.price_fetcher import get_all_prices


def _current_et_time() -> datetime:
    """Return the current wall-clock time in America/New_York. Extracted for testability."""
    return datetime.now(ZoneInfo("America/New_York"))


def is_market_open() -> bool:
    """Return True if the US stock market is currently open.

    US market hours: Monday–Friday, 09:30–16:00 America/New_York.
    Public holidays are not accounted for — keeps the logic simple.

    Returns:
        True if today is a weekday and current ET time is in [09:30, 16:00).
    """
    now_et = _current_et_time()
    if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    market_open  = now_et.replace(hour=9,  minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0,  second=0, microsecond=0)
    return market_open <= now_et < market_close


def run_price_check() -> None:
    """Fast hourly pipeline: fetch prices → calculate portfolio → check rules.

    No AI calls, no news, no file writes. Runs in under 10 seconds.
    Fires send_critical_alert immediately for any CRITICAL rule triggered.
    Always prints a timestamped one-liner to the terminal.
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    if not is_market_open():
        now_et = _current_et_time()
        print(f"[{ts}] ⏸  Market closed — skipping price check ({now_et.strftime('%A %H:%M')} ET)")
        return

    portfolio = load_portfolio()
    portfolio_mod.PORTFOLIO = portfolio

    try:
        prices          = get_all_prices(portfolio)
        portfolio_state = calculate_portfolio(prices)
        triggered_rules = check_rules(portfolio_state)
        bucket_drift    = check_bucket_drift(portfolio_state)

        critical = [a for a in triggered_rules if a.get("level") == "CRITICAL"]
        for alert in critical:
            send_critical_alert(alert["ticker"], alert["message"])

        alert_summary = f"{len(critical)} CRITICAL" if critical else "OK"
        print(f"[{ts}] Price check — ${portfolio_state['total_value']:,.2f}  {alert_summary}")

    except Exception as exc:
        print(f"[{ts}] Price check FAILED: {exc}")


def run_daily_digest() -> None:
    """Daily 14:30 digest: prices → sentiment → Gemini analysis → sell recs → send.

    Pipeline:
        get_performance_summary
        → get_all_prices + calculate_portfolio + check_rules
        → get_all_sentiment + get_macro_sentiment
        → get_weekly_analysis      (Gemini + Google Search)
        → get_weekly_sell_recommendations  (Gemini, no Search)
        → assemble HTML digest body
        → send_daily_email

    Each step is wrapped independently — a failure at any step does not
    prevent subsequent steps from running.
    """
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M")
    now = datetime.now()
    print(f"[{ts}] ── Daily Digest started ──")

    # ── 1. Performance summary ──
    try:
        performance = get_performance_summary()
    except Exception as exc:
        print(f"[{ts}] Performance summary FAILED: {exc}")
        performance = {}

    # ── 2. Prices + portfolio state + rules ──
    portfolio = load_portfolio()
    portfolio_mod.PORTFOLIO = portfolio

    try:
        prices          = get_all_prices(portfolio)
        portfolio_state = calculate_portfolio(prices)
        triggered_rules = check_rules(portfolio_state)
    except Exception as exc:
        print(f"[{ts}] Prices/portfolio FAILED: {exc}")
        portfolio_state = {}
        triggered_rules = []

    # ── 2a. Save daily snapshot ──
    if portfolio_state:
        try:
            save_snapshot(portfolio_state)
        except Exception as exc:
            print(f"[{ts}] Snapshot save FAILED: {exc}")

    # ── 3. Sentiment (stocks only) + macro sentiment ──
    sentiment      = {}
    macro_sentiment = {}
    print(f"[{ts}] 📊 Fetching sentiment for daily digest...")
    try:
        stock_tickers = [
            ticker
            for bucket, holdings in portfolio.items()
            for ticker, asset in holdings.items()
            if asset.get("type") == "stock" and asset.get("qty", 0) > 0
        ]
        sentiment = get_all_sentiment(stock_tickers)
    except Exception as exc:
        print(f"[{ts}] Sentiment FAILED: {exc}")

    try:
        macro_sentiment = get_macro_sentiment(portfolio_state)
    except Exception as exc:
        print(f"[{ts}] Macro sentiment FAILED: {exc}")

    # ── 4. Gemini per-stock analysis ──
    gemini_analysis = ""
    print(f"[{ts}] 🤖 Running Gemini per-stock analysis...")
    try:
        gemini_analysis = get_weekly_analysis(
            portfolio_state, performance, sentiment, macro_sentiment
        )
    except Exception as exc:
        print(f"[{ts}] Gemini analysis FAILED: {exc}")
        gemini_analysis = "⚠️ Gemini analysis unavailable this week."

    # ── 5. Sell recommendations ──
    sell_recs = ""
    print(f"[{ts}] 🧠 Running sell recommendations...")
    try:
        sell_recs = get_weekly_sell_recommendations(
            portfolio_state, triggered_rules, sentiment, macro_sentiment
        )
    except Exception as exc:
        print(f"[{ts}] Sell recommendations FAILED: {exc}")
        sell_recs = "⚠️ Sell recommendations unavailable this week."

    # ── 6. Assemble digest ──
    date_range  = now.strftime("%d %b %Y")
    total_value = portfolio_state.get("total_value", 0.0)

    seven_day_pct = performance.get("last_7_days_pct")
    inception_pct = performance.get("since_inception_pct", 0.0)
    inception_usd = performance.get("since_inception_usd", 0.0)
    best          = performance.get("best_performer")
    worst         = performance.get("worst_performer")

    cgt_footer = (
        "🇮🇪 Irish CGT reminder: pay by 15 Dec for Jan–Nov disposals, "
        "31 Jan for December disposals. €1,270 annual exemption resets 1 Jan."
    )

    # HTML email body
    perf_rows = f"<tr><td><b>Portfolio value</b></td><td>${total_value:,.2f}</td></tr>\n"
    if seven_day_pct is not None:
        perf_rows += f"    <tr><td><b>This week</b></td><td>{seven_day_pct:+.2f}%</td></tr>\n"
    if best:
        perf_rows += f"    <tr><td><b>Best performer</b></td><td>{html.escape(str(best['ticker']))} ({best['pnl_pct']:+.2f}%)</td></tr>\n"
    if worst:
        perf_rows += f"    <tr><td><b>Worst performer</b></td><td>{html.escape(str(worst['ticker']))} ({worst['pnl_pct']:+.2f}%)</td></tr>\n"
    perf_rows += f"    <tr><td><b>Since inception</b></td><td>{inception_pct:+.2f}% (${inception_usd:+,.2f})</td></tr>"

    email_body = f"""<!DOCTYPE html>
<html>
<body style="font-family: monospace; font-size: 14px; color: #222; max-width: 800px; margin: 0 auto;">
  <h2>📊 Daily Digest — {html.escape(date_range)}</h2>

  <table style="border-collapse: collapse; margin-bottom: 24px;">
    {perf_rows}
  </table>

  <h3>📈 Per-Stock Analysis</h3>
  <div style="background: #f5f5f5; padding: 12px; border-radius: 4px;">{md.markdown(gemini_analysis)}</div>

  <h3>💡 Sell Recommendations</h3>
  <div style="background: #f5f5f5; padding: 12px; border-radius: 4px;">{md.markdown(sell_recs)}</div>

  <hr>
  <p style="color: #555; font-size: 12px;">🇮🇪 {html.escape(cgt_footer)}</p>
</body>
</html>"""

    # ── 7. Send email ──
    print(f"[{ts}] 📧 Sending daily digest email...")
    try:
        send_daily_email(f"📊 Finmat Daily — {date_range}", email_body)
    except Exception as exc:
        print(f"[{ts}] Email send FAILED: {exc}")


if __name__ == "__main__":
    import sys
    run_once = "--once" in sys.argv

    startup_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"🚀 Finance Agent started — {startup_ts}")

    history = load_history()
    print(f"📂 History: {len(history)} snapshots loaded")

    if not CRYPTO_ACTIVE:
        print(
            "ℹ️  Crypto bucket inactive — set CRYPTO_ACTIVE = True in config.py "
            "when first purchase is made"
        )

    if run_once:
        run_daily_digest()
        sys.exit(0)

    # Schedule recurring jobs
    schedule.every().day.at("13:00").do(run_price_check)   # CRITICAL-only daily check
    schedule.every().day.at("14:30").do(run_daily_digest)

    try:
        while True:
            schedule.run_pending()
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n👋 Finance Agent stopped.")

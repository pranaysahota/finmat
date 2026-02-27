"""Entry point — wires all modules together, runs price checks and daily briefings on a schedule."""

from datetime import datetime

import schedule
import time

from config import (
    DAILY_BRIEFING_TIME,
    PORTFOLIO,
    PRICE_CHECK_INTERVAL,
)
from modules.alerts import (
    send_critical_alert,
    send_daily_briefing,
    send_weekly_digest,
)
from modules.decision_engine import get_decision
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


def run_price_check() -> None:
    """Fast hourly pipeline: fetch prices → calculate portfolio → check rules.

    No AI calls, no news, no file writes. Runs in under 10 seconds.
    Fires send_critical_alert immediately for any CRITICAL rule triggered.
    Always prints a timestamped one-liner to the terminal.
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        prices          = get_all_prices(PORTFOLIO)
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


def run_daily_briefing() -> None:
    """Full morning pipeline.

    Runs every day at DAILY_BRIEFING_TIME (default 08:00) and once on startup.
    Each step is wrapped individually so a single failure does not abort the
    entire briefing. Safe fallbacks (empty lists / empty dicts) are used when
    a step fails so downstream steps still receive valid input.

    Pipeline:
        get_all_prices
        → calculate_portfolio
        → check_rules + check_bucket_drift
        → save_snapshot
        → get_performance_summary
        → get_all_sentiment  (stocks only)
        → get_decision
        → send_daily_briefing
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n[{ts}] ── Daily Briefing started ──")

    # ── 1. Prices ──
    try:
        print(f"[{ts}] Fetching prices…")
        prices = get_all_prices(PORTFOLIO)
    except Exception as exc:
        print(f"[{ts}] Price fetch FAILED: {exc}")
        return

    # ── 2. Portfolio state ──
    try:
        print(f"[{ts}] Calculating portfolio…")
        portfolio_state = calculate_portfolio(prices)
    except Exception as exc:
        print(f"[{ts}] Portfolio calculation FAILED: {exc}")
        return

    # ── 3. Rules ──
    try:
        triggered_rules = check_rules(portfolio_state)
        bucket_drift    = check_bucket_drift(portfolio_state)
        print(f"[{ts}] Rules checked — {len(triggered_rules)} triggered")
    except Exception as exc:
        print(f"[{ts}] Rules check FAILED: {exc}")
        triggered_rules = []
        bucket_drift    = []

    # ── 4. Snapshot ──
    try:
        print(f"[{ts}] Saving snapshot…")
        save_snapshot(portfolio_state)
    except Exception as exc:
        print(f"[{ts}] Snapshot save FAILED: {exc}")

    # ── 5. Performance ──
    try:
        print(f"[{ts}] Loading performance summary…")
        performance = get_performance_summary()
    except Exception as exc:
        print(f"[{ts}] Performance summary FAILED: {exc}")
        performance = {}

    # ── 6. Sentiment (stocks only) ──
    try:
        stock_tickers = [
            ticker
            for bucket, holdings in PORTFOLIO.items()
            for ticker, asset in holdings.items()
            if asset.get("type") == "stock"
        ]
        print(f"[{ts}] Running sentiment for {len(stock_tickers)} stock tickers…")
        sentiment = get_all_sentiment(stock_tickers)
    except Exception as exc:
        print(f"[{ts}] Sentiment FAILED: {exc}")
        sentiment = {}

    # ── 6b. Macro sentiment (cross-position themes) ──
    try:
        print(f"[{ts}] Running macro sentiment (4 themes)…")
        macro_sentiment = get_macro_sentiment(portfolio_state)
    except Exception as exc:
        print(f"[{ts}] Macro sentiment FAILED: {exc}")
        macro_sentiment = {}

    # ── 7. Decision ──
    try:
        print(f"[{ts}] Generating decision…")
        decision = get_decision(
            portfolio_state, triggered_rules, bucket_drift,
            macro_sentiment, sentiment, performance,
        )
    except Exception as exc:
        print(f"[{ts}] Decision engine FAILED: {exc}")
        decision = "⚠️ Decision engine unavailable."

    # ── 8. Send ──
    try:
        print(f"[{ts}] Sending daily briefing…")
        send_daily_briefing(
            portfolio_state, decision, triggered_rules, bucket_drift,
            performance, macro_sentiment,
        )
    except Exception as exc:
        print(f"[{ts}] Send FAILED: {exc}")

    print(f"[{ts}] ── Daily Briefing complete ──\n")


def run_weekly_digest() -> None:
    """Weekly Sunday 09:00 digest: prices → portfolio → performance → send.

    Silently skips if fewer than 2 history snapshots exist (not enough data).
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{ts}] ── Weekly Digest started ──")

    try:
        performance = get_performance_summary()
        if not performance:
            print(f"[{ts}] Weekly Digest skipped — insufficient history")
            return

        prices          = get_all_prices(PORTFOLIO)
        portfolio_state = calculate_portfolio(prices)
        send_weekly_digest(performance, portfolio_state)
        print(f"[{ts}] ── Weekly Digest sent ──")

    except Exception as exc:
        print(f"[{ts}] Weekly Digest FAILED: {exc}")


if __name__ == "__main__":
    startup_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"🚀 Finance Agent started — {startup_ts}")

    history = load_history()
    print(f"📂 History: {len(history)} snapshots loaded")

    # Run briefing immediately on first start for testing
    run_daily_briefing()

    # Schedule recurring jobs
    schedule.every(PRICE_CHECK_INTERVAL).hours.do(run_price_check)
    schedule.every().day.at(DAILY_BRIEFING_TIME).do(run_daily_briefing)
    schedule.every().sunday.at("09:00").do(run_weekly_digest)

    try:
        while True:
            schedule.run_pending()
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n👋 Finance Agent stopped.")

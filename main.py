"""Entry point — wires all modules together, runs price checks and daily briefings on a schedule."""

import html
from datetime import datetime, timedelta

import markdown as md
from zoneinfo import ZoneInfo

import schedule
import time

from config import (
    CRYPTO_ACTIVE,
    DAILY_BRIEFING_TIME,
    PORTFOLIO,
    PRICE_CHECK_INTERVAL,
)
from modules.alerts import (
    send_critical_alert,
    send_daily_briefing,
    send_weekly_email,
)
from modules.run_logger import RunLogger, extract_final_signal
from modules.decision_engine import (
    build_context,
    get_decision,
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

    Runs every day at DAILY_BRIEFING_TIME (default 13:00) and once on startup.
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

    # ── Logger ──
    all_tickers = [t for bucket in PORTFOLIO.values() for t in bucket.keys()]
    logger = RunLogger()
    logger.start_run(all_tickers)

    # ── 1. Prices ──
    try:
        print(f"[{ts}] Fetching prices…")
        prices = get_all_prices(PORTFOLIO)
        logger.log_step("fetch", {
            "tickers":       list(prices.keys()),
            "data_snapshot": prices,
        })
    except Exception as exc:
        print(f"[{ts}] Price fetch FAILED: {exc}")
        logger.finalise("error", f"Price fetch FAILED: {exc}")
        return

    # ── 2. Portfolio state ──
    try:
        print(f"[{ts}] Calculating portfolio…")
        portfolio_state = calculate_portfolio(prices)
    except Exception as exc:
        print(f"[{ts}] Portfolio calculation FAILED: {exc}")
        logger.finalise("error", f"Portfolio calculation FAILED: {exc}")
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
        print(f"[{ts}] Running macro sentiment…")
        macro_sentiment = get_macro_sentiment(portfolio_state)
    except Exception as exc:
        print(f"[{ts}] Macro sentiment FAILED: {exc}")
        macro_sentiment = {}

    # ── 7. Decision ──
    try:
        print(f"[{ts}] Generating decision…")
        # Build context separately so it can be captured for logging (pure function)
        context = build_context(
            portfolio_state, triggered_rules, bucket_drift,
            macro_sentiment, sentiment, performance,
        )
        decision = get_decision(
            portfolio_state, triggered_rules, bucket_drift,
            macro_sentiment, sentiment, performance,
        )
        logger.log_step("analyse", {
            "prompt_sent":   context,
            "raw_response":  decision,
            "parsed_output": {"sentiment": sentiment},
        })
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
        logger.log_step("format", {
            "prompt_sent":  decision,
            "raw_response": "",
            "final_signal": extract_final_signal(decision),
        })
    except Exception as exc:
        print(f"[{ts}] Send FAILED: {exc}")
        logger.log_step("format", {
            "prompt_sent":  decision,
            "raw_response": "",
            "final_signal": extract_final_signal(decision),
            "error":        str(exc),
        })

    logger.finalise("success")
    print(f"[{ts}] ── Daily Briefing complete ──\n")


def run_weekly_digest() -> None:
    """Weekly Sunday 14:30 digest: prices → sentiment → Gemini analysis → sell recs → send.

    Pipeline:
        get_performance_summary  (skips if insufficient history)
        → get_all_prices + calculate_portfolio + check_rules
        → get_all_sentiment + get_macro_sentiment
        → get_weekly_analysis      (Gemini + Google Search)
        → get_weekly_sell_recommendations  (Gemini, no Search)
        → assemble HTML digest body
        → send_weekly_email

    Each step is wrapped independently — a failure at any step does not
    prevent subsequent steps from running.
    """
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M")
    now = datetime.now()
    print(f"[{ts}] ── Weekly Digest started ──")

    # ── 1. Performance summary ──
    try:
        performance = get_performance_summary()
        if not performance:
            print(f"[{ts}] Weekly Digest skipped — insufficient history")
            return
    except Exception as exc:
        print(f"[{ts}] Performance summary FAILED: {exc}")
        return

    # ── 2. Prices + portfolio state + rules ──
    try:
        prices          = get_all_prices(PORTFOLIO)
        portfolio_state = calculate_portfolio(prices)
        triggered_rules = check_rules(portfolio_state)
    except Exception as exc:
        print(f"[{ts}] Prices/portfolio FAILED: {exc}")
        portfolio_state = {}
        triggered_rules = []

    # ── 3. Sentiment (stocks only) + macro sentiment ──
    sentiment      = {}
    macro_sentiment = {}
    print(f"[{ts}] 📊 Fetching sentiment for weekly digest...")
    try:
        stock_tickers = [
            ticker
            for bucket, holdings in PORTFOLIO.items()
            for ticker, asset in holdings.items()
            if asset.get("type") == "stock"
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
    week_start  = (now - timedelta(days=7)).strftime("%d %b")
    week_end    = now.strftime("%d %b %Y")
    date_range  = f"{week_start} – {week_end}"
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
  <h2>📊 Weekly Digest — {html.escape(date_range)}</h2>

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
    print(f"[{ts}] 📧 Sending weekly email...")
    try:
        send_weekly_email(f"📊 Finmat Weekly — {date_range}", email_body)
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
        run_daily_briefing()
        sys.exit(0)

    # Schedule recurring jobs
    schedule.every(PRICE_CHECK_INTERVAL).hours.do(run_price_check)
    schedule.every().day.at(DAILY_BRIEFING_TIME).do(run_daily_briefing)
    schedule.every().sunday.at("14:30").do(run_weekly_digest)

    try:
        while True:
            schedule.run_pending()
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n👋 Finance Agent stopped.")

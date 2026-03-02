"""Sends portfolio state, triggered rules, and sentiment to Claude and returns a structured investment briefing."""

import sys
from pathlib import Path

# Allow direct invocation (python modules/decision_engine.py) as well as import
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import ANTHROPIC_API_KEY, RULES

import anthropic

_SYSTEM_PROMPT_NORMAL = """\
You are a personal investment advisor monitoring a moderate-risk $8,000 \
portfolio based in Ireland with a 6-12 month horizon.

PORTFOLIO STRUCTURE:
- 60% Diversified (MSFT, AAPL, JPM, JNJ, ASML, BRK.B, XOM)
- 25% Growth (GOOG, NVDA)
- 15% Crypto (BTC, ETH — currently inactive)

HEDGING CONTEXT:
JPM, JNJ, XOM and BRK.B are deliberate hedges against tech/AI weakness.
When AI or semiconductor theme sentiment is bearish, check whether defensives
are offsetting before flagging concern. A bearish AI theme with rising JPM
and XOM means the hedge is working — not a problem.

The investor is in a HOLD phase. Do not comment on CGT or tax implications
unless directly asked. Focus on:
- Whether the macro environment supports continuing to hold each position
- Which positions are showing strength or weakness worth watching
- Whether news sentiment is a short-term blip or a structural shift
- How the defensive positions are behaving relative to growth positions

Respond in exactly this format:

MARKET MOOD: [one sentence]

PORTFOLIO STATUS: [2-3 sentences — overall health, which buckets helping
vs hurting, any macro theme dominating]

WATCH LIST:
[2-3 specific things to monitor this week with brief reason.
Prioritise DOUBLE SIGNAL positions and macro themes affecting >50% of portfolio]

No fluff. Reference actual tickers and numbers.
Plain text only — no Markdown, no asterisks, no underscores used for
formatting, no HTML tags."""

_SYSTEM_PROMPT_ALERT = _SYSTEM_PROMPT_NORMAL + """

ONE OR MORE ALERT RULES HAVE TRIGGERED. For any position flagged as \
CRITICAL (stop-loss) or HIGH (take-profit), include a CGT IMPACT section \
in your response with the following:

- Whether selling crystallises a gain or a loss
- If a gain: estimated CGT owed at 33% on the gain amount
- If a loss: note that this loss can be offset against future CGT gains \
  and carries forward indefinitely under Irish tax law
- The €1,270 annual exemption remaining if applicable
- Whether EUR/USD rate movement materially changes the calculation

Add this section to your response format:

CGT IMPACT (triggered positions only):
[one line per triggered position with the tax calculation]"""

_FALLBACK_DECISION = (
    "⚠️ Decision engine unavailable — Claude API error. "
    "Please check your ANTHROPIC_API_KEY and retry."
)


def build_context(
    portfolio_state:  dict,
    triggered_rules:  list,
    bucket_drift:     list,
    macro_sentiment:  dict,
    sentiment:        dict,
    performance:      dict,
) -> str:
    """Build a structured, human-readable context block for the decision engine.

    Formats all portfolio data into a clear text block that the Claude Sonnet
    system prompt can reason over. Sections included:
      - Portfolio Snapshot (totals and crypto weight)
      - Bucket Breakdown (current vs target per bucket)
      - Holdings (ticker, price, P&L, risk proximity flags)
      - Triggered Rules (alert list or 'None triggered')
      - Bucket Drift (drift alerts or 'Within targets')
      - Macro Themes (cross-position themes with portfolio weight affected)
      - Sentiment (label + summary per ticker, with DOUBLE SIGNAL detection)
      - Performance History (since inception + 7-day if available)

    Args:
        portfolio_state: Dict as returned by calculate_portfolio().
        triggered_rules: List of alert dicts from check_rules().
        bucket_drift:    List of drift alert dicts from check_bucket_drift().
        macro_sentiment: Dict of {theme: {score, label, summary, affected_tickers}}
                         from get_macro_sentiment(). May be empty.
        sentiment:       Dict of {ticker: {score, label, summary}} from get_all_sentiment().
        performance:     Dict from get_performance_summary(), or empty dict.

    Returns:
        Formatted multi-line string ready to pass as the user message to Claude.
    """
    lines: list[str] = []

    # ── Portfolio Snapshot ──
    lines.append("PORTFOLIO SNAPSHOT")
    lines.append(f"  Total value:   ${portfolio_state.get('total_value', 0):,.2f}")
    lines.append(f"  Total cost:    ${portfolio_state.get('total_cost', 0):,.2f}")
    lines.append(
        f"  P&L:           ${portfolio_state.get('total_pnl_usd', 0):+,.2f} "
        f"({portfolio_state.get('total_pnl_pct', 0):+.2f}%)"
    )
    lines.append(f"  Crypto weight: {portfolio_state.get('crypto_weight', 0):.1f}%")

    # ── Bucket Breakdown ──
    lines.append("\nBUCKET BREAKDOWN")
    bucket_values  = portfolio_state.get("bucket_values",  {})
    bucket_weights = portfolio_state.get("bucket_weights", {})
    bucket_targets = {"Diversified": 60, "Growth": 25, "Crypto": 15}
    for bucket in bucket_values:
        val    = bucket_values.get(bucket, 0.0)
        actual = bucket_weights.get(bucket, 0.0)
        target = bucket_targets.get(bucket, 0)
        lines.append(f"  {bucket:<14} ${val:>10,.2f}  {actual:.1f}% (target {target}%)")

    # ── Holdings (risk-annotated) ──
    lines.append("\nHOLDINGS")
    for ticker, data in portfolio_state.get("holdings", {}).items():
        pnl_pct = data.get("pnl_pct", 0.0)
        pnl_usd = data.get("pnl_usd", 0.0)
        bucket  = data.get("bucket", "")
        price   = data.get("current_price", 0.0)
        line = (
            f"  {ticker:<8} | ${price:>10,.2f} | "
            f"P&L: {pnl_pct:+.1f}% (${pnl_usd:+,.2f}) | {bucket}"
        )
        if pnl_pct <= -12.0:
            line += "  ⚠️ STOP-LOSS PROXIMITY"
        elif pnl_pct >= 32.0:
            line += "  🎯 TAKE-PROFIT PROXIMITY"
        lines.append(line)

    # ── Triggered Rules ──
    lines.append("\nTRIGGERED RULES")
    if triggered_rules:
        for alert in triggered_rules:
            lines.append(f"  [{alert.get('level')}] {alert.get('message')}")
    else:
        lines.append("  None triggered")

    # ── Bucket Drift ──
    lines.append("\nBUCKET DRIFT")
    if bucket_drift:
        for alert in bucket_drift:
            lines.append(f"  {alert.get('message')}")
    else:
        lines.append("  Within targets")

    # ── Macro Themes (cross-position) ──
    lines.append("\nMACRO THEMES (cross-position)")
    if macro_sentiment:
        total_value = portfolio_state.get("total_value", 0.0)
        holdings    = portfolio_state.get("holdings", {})
        for theme_label, theme_data in macro_sentiment.items():
            affected  = theme_data.get("affected_tickers", [])
            theme_val = sum(
                holdings[t]["current_value"]
                for t in affected
                if t in holdings
            )
            theme_weight = (theme_val / total_value * 100) if total_value else 0.0
            lines.append(
                f"  {theme_label}: {theme_data.get('label')} "
                f"({theme_data.get('score', 0.0):+.2f}) — "
                f"affects: {', '.join(affected)}"
            )
            lines.append(f"    Summary: {theme_data.get('summary', '')}")
            lines.append(f"    {theme_label} affects {theme_weight:.0f}% of portfolio by value")
    else:
        lines.append("  No macro theme data available.")

    # ── Sentiment (per ticker, with DOUBLE SIGNAL detection) ──
    lines.append("\nSENTIMENT (per ticker)")
    if sentiment:
        # Build set of tickers that appear in any bearish macro theme
        bearish_macro_tickers: set[str] = set()
        for theme_data in macro_sentiment.values():
            if theme_data.get("score", 0.0) < 0:
                bearish_macro_tickers.update(theme_data.get("affected_tickers", []))

        for ticker, data in sentiment.items():
            ticker_score = data.get("score", 0.0)
            lines.append(
                f"  {ticker:<8} {data.get('label', 'NEUTRAL'):<18} "
                f"({ticker_score:+.2f}) | "
                f"current P&L: {portfolio_state.get('holdings', {}).get(ticker, {}).get('pnl_pct', 0.0):+.1f}%"
            )
            lines.append(f"    {data.get('summary', '')}")
            if ticker in bearish_macro_tickers and ticker_score < 0:
                lines.append(
                    f"    🔴 DOUBLE SIGNAL: bearish on both ticker and macro theme"
                )
    else:
        lines.append("  No sentiment data available")

    # ── Performance History ──
    lines.append("\nPERFORMANCE HISTORY")
    if performance:
        inception_pct = performance.get("since_inception_pct")
        inception_usd = performance.get("since_inception_usd")
        seven_day_pct = performance.get("last_7_days_pct")
        first_date    = performance.get("first_date", "unknown")
        latest_date   = performance.get("latest_date", "unknown")

        lines.append(
            f"  Since inception ({first_date} → {latest_date}): "
            f"{inception_pct:+.2f}% (${inception_usd:+,.2f})"
        )
        if seven_day_pct is not None:
            lines.append(f"  Last 7 days: {seven_day_pct:+.2f}%")
        else:
            lines.append("  Last 7 days: insufficient data")

        best  = performance.get("best_performer")
        worst = performance.get("worst_performer")
        if best:
            lines.append(f"  Best performer:  {best['ticker']} ({best['pnl_pct']:+.2f}%)")
        if worst:
            lines.append(f"  Worst performer: {worst['ticker']} ({worst['pnl_pct']:+.2f}%)")
    else:
        lines.append("  Insufficient history — agent started recently")

    return "\n".join(lines)


def get_decision(
    portfolio_state:  dict,
    triggered_rules:  list,
    bucket_drift:     list,
    macro_sentiment:  dict,
    sentiment:        dict,
    performance:      dict,
) -> str:
    """Generate a structured daily investment briefing using Claude Sonnet.

    Calls build_context() to format the portfolio data, then sends it to
    Claude Sonnet 4.6 with the investment advisor system prompt.

    Args:
        portfolio_state: Dict as returned by calculate_portfolio().
        triggered_rules: List of alert dicts from check_rules().
        bucket_drift:    List of drift alert dicts from check_bucket_drift().
        macro_sentiment: Dict of {theme: sentiment_dict} from get_macro_sentiment().
        sentiment:       Dict of {ticker: sentiment_dict} from get_all_sentiment().
        performance:     Dict from get_performance_summary(), or empty dict.

    Returns:
        Claude's formatted briefing text as a string.
        Returns a clear fallback message on any API error so the pipeline continues.
    """
    context = build_context(
        portfolio_state, triggered_rules, bucket_drift, macro_sentiment, sentiment, performance
    )

    triggered_critical_or_high = any(
        r["level"] in ("CRITICAL", "HIGH") for r in triggered_rules
    )
    system_prompt = _SYSTEM_PROMPT_ALERT if triggered_critical_or_high else _SYSTEM_PROMPT_NORMAL

    try:
        client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model      = "claude-sonnet-4-6",
            max_tokens = 2000,
            system     = system_prompt,
            messages   = [{"role": "user", "content": context}],
        )
        return response.content[0].text.strip()

    except Exception as exc:
        print(f"  ⚠️  Decision engine error: {exc}")
        return _FALLBACK_DECISION


# ── Manual test ────────────────────────────────────────────────
if __name__ == "__main__":
    # Minimal mock data so the module can be tested without live data
    mock_portfolio_state = {
        "total_value":    8200.00,
        "total_cost":     8000.00,
        "total_pnl_usd":  200.00,
        "total_pnl_pct":  2.50,
        "crypto_weight":  14.8,
        "bucket_values":  {"Diversified": 4980.0, "Growth": 2010.0, "Crypto": 1210.0},
        "bucket_weights": {"Diversified": 60.7, "Growth": 24.5, "Crypto": 14.8},
        "holdings": {
            "MSFT": {"current_price": 430.0, "current_value": 1290.0,
                     "cost_basis": 1200.0, "pnl_pct": 7.5, "pnl_usd": 90.0, "bucket": "Diversified"},
            "NVDA": {"current_price": 140.0, "current_value": 700.0,
                     "cost_basis": 675.0, "pnl_pct": 3.7, "pnl_usd": 25.0, "bucket": "Growth"},
        },
    }
    mock_sentiment = {
        "MSFT": {"score": 0.6, "label": "BULLISH", "summary": "Azure growth beats expectations."},
        "NVDA": {"score": 0.3, "label": "SLIGHTLY_BULLISH", "summary": "AI chip demand remains strong."},
    }
    mock_performance = {
        "since_inception_pct": 2.5,
        "since_inception_usd": 200.0,
        "last_7_days_pct":     None,
        "best_performer":      {"ticker": "MSFT", "pnl_pct": 7.5},
        "worst_performer":     {"ticker": "NVDA", "pnl_pct": 3.7},
        "total_snapshots":     1,
        "first_date":          "2026-02-24",
        "latest_date":         "2026-02-24",
    }

    mock_macro_sentiment = {
        "AI_TECH_THEME": {
            "score": -0.3, "label": "SLIGHTLY_BEARISH",
            "summary": "AI spending concerns weigh on big tech.",
            "affected_tickers": ["MSFT", "AAPL", "GOOG", "NVDA", "ASML"],
        },
        "DEFENSIVE_THEME": {
            "score": 0.2, "label": "SLIGHTLY_BULLISH",
            "summary": "Financials and energy holding steady.",
            "affected_tickers": ["JPM", "JNJ", "XOM", "BRK.B"],
        },
    }

    print("\n── Context block ──\n")
    ctx = build_context(
        mock_portfolio_state, [], [], mock_macro_sentiment, mock_sentiment, mock_performance
    )
    print(ctx)

    print("\n── Decision (live API) ──\n")
    decision = get_decision(
        mock_portfolio_state, [], [], mock_macro_sentiment, mock_sentiment, mock_performance
    )
    print(decision)

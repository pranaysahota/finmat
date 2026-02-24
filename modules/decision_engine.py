"""Sends portfolio state, triggered rules, and sentiment to Claude and returns a structured investment briefing."""

import sys
from pathlib import Path

# Allow direct invocation (python modules/decision_engine.py) as well as import
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import ANTHROPIC_API_KEY, RULES

import anthropic

_SYSTEM_PROMPT = """\
You are a personal investment advisor for a moderate-risk $8,000 portfolio \
based in Ireland with a 6-12 month horizon.

PORTFOLIO STRUCTURE:
- 60% Diversified (MSFT, AAPL, JPM, JNJ, ASML, BRK.B, XOM)
  Multi-sector stocks replacing ETFs for Irish tax efficiency.
- 25% Growth (GOOG, NVDA) — high-conviction AI/tech plays
- 15% Crypto (BTC, ETH)

IRISH TAX CONTEXT — THIS IS CRITICAL:
- All positions are subject to Irish CGT at 33% on actual disposal only.
- ETFs are deliberately excluded — Irish exit tax (38%) + 8-year deemed
  disposal makes them unfavourable for this investor.
- Never recommend selling and rebuying to rebalance unless the tax cost
  is explicitly worth it — every disposal is a taxable event.
- The investor has a €1,270 annual CGT exemption — factor this in when
  suggesting any partial profit-taking.
- Crypto-to-crypto swaps (e.g. BTC → ETH) are also taxable events.
- Benchmark: MSFT is the largest position and acts as the internal
  performance anchor — not an external index like VOO.

Analyse the data and respond in exactly this format:

MARKET MOOD: [one sentence]

PORTFOLIO STATUS: [2-3 sentences on overall health and trend]

ACTIONS REQUIRED:
[bullet list of specific actions, or 'No action needed']

WATCH LIST:
[2-3 things to monitor this week with brief reason]

Be specific. Reference actual tickers and numbers. No fluff.
Always factor in Irish CGT before recommending any disposal."""

_FALLBACK_DECISION = (
    "⚠️ Decision engine unavailable — Claude API error. "
    "Please check your ANTHROPIC_API_KEY and retry."
)


def build_context(
    portfolio_state:  dict,
    triggered_rules:  list,
    bucket_drift:     list,
    sentiment:        dict,
    performance:      dict,
) -> str:
    """Build a structured, human-readable context block for the decision engine.

    Formats all portfolio data into a clear text block that the Claude Sonnet
    system prompt can reason over. Sections included:
      - Portfolio Snapshot (totals and crypto weight)
      - Bucket Breakdown (current vs target per bucket)
      - Holdings (ticker, price, P&L)
      - Triggered Rules (alert list or 'None triggered')
      - Bucket Drift (drift alerts or 'Within targets')
      - Sentiment (label + summary per ticker)
      - Performance History (since inception + 7-day if available)

    Args:
        portfolio_state: Dict as returned by calculate_portfolio().
        triggered_rules: List of alert dicts from check_rules().
        bucket_drift:    List of drift alert dicts from check_bucket_drift().
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
    for bucket in ("Diversified", "Growth", "Crypto"):
        val    = bucket_values.get(bucket, 0.0)
        actual = bucket_weights.get(bucket, 0.0)
        target = bucket_targets.get(bucket, 0)
        lines.append(f"  {bucket:<14} ${val:>10,.2f}  {actual:.1f}% (target {target}%)")

    # ── Holdings ──
    lines.append("\nHOLDINGS")
    for ticker, data in portfolio_state.get("holdings", {}).items():
        lines.append(
            f"  {ticker:<10} price ${data.get('current_price', 0):>10,.2f}  "
            f"value ${data.get('current_value', 0):>10,.2f}  "
            f"P&L {data.get('pnl_pct', 0):+.1f}%"
        )

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

    # ── Sentiment ──
    lines.append("\nSENTIMENT")
    if sentiment:
        for ticker, data in sentiment.items():
            lines.append(
                f"  {ticker:<10} [{data.get('label', 'NEUTRAL'):<18}]  "
                f"{data.get('summary', '')}"
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
        sentiment:       Dict of {ticker: sentiment_dict} from get_all_sentiment().
        performance:     Dict from get_performance_summary(), or empty dict.

    Returns:
        Claude's formatted briefing text as a string.
        Returns a clear fallback message on any API error so the pipeline continues.
    """
    context = build_context(
        portfolio_state, triggered_rules, bucket_drift, sentiment, performance
    )

    try:
        client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model      = "claude-sonnet-4-6",
            max_tokens = 600,
            system     = _SYSTEM_PROMPT,
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

    print("\n── Context block ──\n")
    ctx = build_context(mock_portfolio_state, [], [], mock_sentiment, mock_performance)
    print(ctx)

    print("\n── Decision (live API) ──\n")
    decision = get_decision(mock_portfolio_state, [], [], mock_sentiment, mock_performance)
    print(decision)

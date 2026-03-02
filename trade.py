"""CLI tool to log a trade after a Revolut purchase.

Updates portfolio/local.py in-place (preserving all comments and structure)
and permanently appends the trade to data/trades.json.

Usage:
    python trade.py
"""

import ast
import importlib.util
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT           = Path(__file__).parent
PORTFOLIO_FILE = ROOT / "portfolio" / "local.py"
DATA_DIR       = ROOT / "data"
TRADES_FILE    = DATA_DIR / "trades.json"

VALID_BUCKETS = {"Diversified", "Growth", "Crypto"}
VALID_TYPES   = {"stock", "crypto"}
UNIT          = {"stock": "shares", "crypto": "coins"}


# ── Portfolio loading ──────────────────────────────────────────────

def _load_portfolio() -> dict:
    """Load PORTFOLIO from portfolio/local.py via importlib (avoids import cache)."""
    spec = importlib.util.spec_from_file_location("portfolio_local", PORTFOLIO_FILE)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.PORTFOLIO


def _find_ticker(portfolio: dict, ticker: str) -> tuple[str | None, dict | None]:
    """Return (bucket_name, asset_dict) or (None, None) if not found."""
    for bucket, holdings in portfolio.items():
        if ticker in holdings:
            return bucket, holdings[ticker]
    return None, None


# ── Input helpers ──────────────────────────────────────────────────

def _get_float(prompt: str) -> float:
    """Prompt until a valid positive float is entered."""
    while True:
        try:
            val = float(input(prompt).strip())
            if val <= 0:
                print("  ❌ Must be greater than 0. Try again.")
            else:
                return val
        except ValueError:
            print("  ❌ Invalid number. Try again.")


def _get_choice(prompt: str, valid: set) -> str:
    """Prompt until one of the valid choices is entered."""
    while True:
        val = input(prompt).strip()
        if val in valid:
            return val
        print(f"  ❌ Must be one of: {', '.join(sorted(valid))}. Try again.")


def _normalise_ticker(raw: str, asset_type: str) -> str:
    """Uppercase for stocks/ETFs, lowercase for crypto (bitcoin not BITCOIN)."""
    return raw.lower() if asset_type == "crypto" else raw.upper()


# ── AST-based surgical file updater ───────────────────────────────

def _find_field_node(source: str, ticker: str, field: str) -> tuple[int | None, int | None]:
    """
    Parse source with ast and return (lineno, col_offset) of the value node
    for portfolio[bucket][ticker][field].  Returns (None, None) if not found.
    """
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "PORTFOLIO" for t in node.targets):
            continue

        for bucket_val in node.value.values:
            if not isinstance(bucket_val, ast.Dict):
                continue
            for asset_key, asset_val in zip(bucket_val.keys, bucket_val.values):
                if not (isinstance(asset_key, ast.Constant) and asset_key.value == ticker):
                    continue
                if not isinstance(asset_val, ast.Dict):
                    continue
                for k, v in zip(asset_val.keys, asset_val.values):
                    if isinstance(k, ast.Constant) and k.value == field:
                        return v.lineno, v.col_offset

    return None, None


def _replace_value_at(source: str, lineno: int, col_offset: int, new_value: str) -> str:
    """
    Replace the numeric literal that starts at (lineno, col_offset) with new_value.
    Works character-by-character so surrounding comments are never touched.
    AST lineno is 1-indexed; col_offset is 0-indexed.
    """
    lines = source.splitlines(keepends=True)
    line  = lines[lineno - 1]

    # Walk forward from col_offset to find where the number ends
    end = col_offset
    while end < len(line) and (line[end].isdigit() or line[end] == "."):
        end += 1

    lines[lineno - 1] = line[:col_offset] + new_value + line[end:]
    return "".join(lines)


def _update_existing_ticker(ticker: str, new_qty: float, new_avg_buy: float) -> None:
    """Update qty and avg_buy for an existing ticker using AST-located positions."""
    source = PORTFOLIO_FILE.read_text()

    qty_line, qty_col = _find_field_node(source, ticker, "qty")
    avg_line, avg_col = _find_field_node(source, ticker, "avg_buy")

    if qty_line is None or avg_line is None:
        raise ValueError(f"Could not locate qty/avg_buy for '{ticker}' in portfolio/local.py")

    # Apply both replacements. qty comes before avg_buy so replace qty first;
    # since they're on different lines the col_offset of avg_buy stays valid.
    source = _replace_value_at(source, qty_line, qty_col, str(new_qty))
    source = _replace_value_at(source, avg_line, avg_col, f"{new_avg_buy:.2f}")

    PORTFOLIO_FILE.write_text(source)


def _add_new_ticker(ticker: str, bucket: str, asset_type: str,
                    new_qty: float, new_avg_buy: float) -> None:
    """
    Insert a new asset block into the correct bucket in portfolio/local.py.
    Uses ast.end_lineno to find the closing brace of the target bucket dict,
    then inserts the new block immediately before it.
    """
    source = PORTFOLIO_FILE.read_text()
    tree   = ast.parse(source)

    bucket_end_line = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "PORTFOLIO" for t in node.targets):
            continue
        for bk, bv in zip(node.value.keys, node.value.values):
            if isinstance(bk, ast.Constant) and bk.value == bucket:
                bucket_end_line = bv.end_lineno   # line of the bucket's closing }
                break

    if bucket_end_line is None:
        raise ValueError(f"Bucket '{bucket}' not found in portfolio/local.py")

    new_block = (
        f'        "{ticker}": {{\n'
        f'            "type":           "{asset_type}",\n'
        f'            "qty":            {new_qty},\n'
        f'            "avg_buy":        {new_avg_buy:.2f},\n'
        f'            "allocation_usd": 0,        # set target allocation when known\n'
        f'            "bucket_pct":     0,         # set bucket weight when known\n'
        f'        }},\n'
    )

    lines = source.splitlines(keepends=True)
    # bucket_end_line is 1-indexed; insert before the closing brace (0-indexed = bucket_end_line - 1)
    lines.insert(bucket_end_line - 1, new_block)
    PORTFOLIO_FILE.write_text("".join(lines))


# ── Trade log ──────────────────────────────────────────────────────

def _append_trade(trade: dict) -> None:
    """Append a trade record to data/trades.json (creates file if missing)."""
    DATA_DIR.mkdir(exist_ok=True)

    history = []
    if TRADES_FILE.exists():
        try:
            history = json.loads(TRADES_FILE.read_text())
        except json.JSONDecodeError:
            print("  ⚠️  trades.json was malformed — starting fresh.")

    history.append(trade)
    TRADES_FILE.write_text(json.dumps(history, indent=2))


# ── CGT calculation ────────────────────────────────────────────────

def _calc_cgt(gross_gain: float) -> float:
    """Calculate CGT owed under Irish law (33% on gain above €1,270 annual exemption).

    Simplified estimate: the gain is passed in USD (portfolio is priced in USD),
    and the €1,270 exemption is applied as-is. This is only accurate when USD ≈ EUR.
    The caller should convert to EUR at the actual disposal-time exchange rate
    and verify with a tax professional.

    Returns 0.0 for a loss or a gain within the exemption.
    """
    return round(max(0.0, gross_gain - 1270) * 0.33, 2)


# ── Sell flow ──────────────────────────────────────────────────────

def _run_sell(portfolio: dict) -> None:
    """Interactive sell flow: validate ticker, display CGT estimate, update portfolio."""

    # ── Step 1: ticker ───────────────────────────────────────────
    raw = input("  Ticker to sell: ").strip()
    if not raw:
        print("  ❌ Ticker cannot be empty.")
        sys.exit(1)

    bucket, asset = _find_ticker(portfolio, raw.upper())
    if asset is None:
        bucket, asset = _find_ticker(portfolio, raw.lower())

    asset_type = asset["type"] if asset else None
    ticker     = _normalise_ticker(raw, asset_type or "stock")

    if asset is None:
        bucket, asset = _find_ticker(portfolio, ticker)

    if asset is None or asset["qty"] == 0:
        print(f"  ❌ {ticker} not found in portfolio or qty is zero.")
        sys.exit(1)

    current_qty = asset["qty"]
    avg_buy     = asset["avg_buy"]
    asset_type  = asset["type"]

    # ── Step 2: quantity and price ───────────────────────────────
    qty_sold = _get_float("  Quantity sold:    > ")
    if qty_sold > current_qty:
        print(f"  ❌ You hold {current_qty} shares. Cannot sell {qty_sold}.")
        sys.exit(1)

    price = _get_float("  Price per share:  > ")

    # ── Step 3: CGT calculation ──────────────────────────────────
    total_cost         = round(avg_buy * qty_sold, 2)
    total_proceeds     = round(price * qty_sold, 2)
    gross_gain_or_loss = round(total_proceeds - total_cost, 2)
    cgt_owed           = _calc_cgt(gross_gain_or_loss)
    remaining_qty      = round(current_qty - qty_sold, 8)

    if gross_gain_or_loss > 0:
        cgt_detail = f"    CGT owed*:        ~€{cgt_owed:.2f}"
    else:
        cgt_detail = (
            f"    Loss banked*:     ~€{abs(gross_gain_or_loss):.2f}"
            f" offsettable against future gains"
        )

    print(f"""
  ────────────────────────────────
  SELL SUMMARY — {ticker}
  ────────────────────────────────
  Shares sold:        {qty_sold} @ ${price:,.2f}
  Proceeds:           ${total_proceeds:,.2f}
  Cost basis:         ${total_cost:,.2f} (avg_buy: ${avg_buy:,.2f})
  Gross gain/loss:    ${gross_gain_or_loss:,.2f}

  CGT ESTIMATE (Irish, 33%):
    Result:           {"GAIN" if gross_gain_or_loss > 0 else "LOSS"}
{cgt_detail}
  * USD-denominated estimate. Apply EUR/USD rate at disposal for exact EUR gain.
  * €1,270 annual exemption assumed unused. Verify with your tax records.

  Remaining position: {remaining_qty} shares
  ────────────────────────────────""")

    confirm = input("  Confirm sell? (y/n): ").strip().lower()
    if confirm != "y":
        print("  Aborted — no changes made.")
        sys.exit(0)

    # ── Step 4: update portfolio and log trade ───────────────────
    new_avg_buy = 0.0 if remaining_qty == 0.0 else avg_buy
    _update_existing_ticker(ticker, remaining_qty, new_avg_buy)

    sell_trade = {
        "id":             str(uuid.uuid4()),
        "timestamp":      datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "side":           "sell",
        "ticker":         ticker,
        "bucket":         bucket,
        "type":           asset_type,
        "qty_sold":       qty_sold,
        "price_received": price,
        "total_proceeds": total_proceeds,
        "cost_basis":     total_cost,
        "gross_pnl":      gross_gain_or_loss,
        "cgt_estimate":   cgt_owed,
        "remaining_qty":  remaining_qty,
        "source":         "Revolut",
    }
    _append_trade(sell_trade)

    print(f"  ✅ Sell logged. Remaining {ticker} position: {remaining_qty} shares.")
    print(
        "  📋 Remember to file CGT with Revenue by 15 Dec "
        "(or 31 Jan for December disposals)."
    )


# ── Main flow ──────────────────────────────────────────────────────

def main() -> None:
    print("\n📈 Finance Agent — Log a Trade\n")

    print("  Trade type:")
    print("  [1] Buy")
    print("  [2] Sell")
    side = input("  > ").strip()
    if side not in ("1", "2"):
        print("  ❌ Invalid choice. Enter 1 or 2.")
        sys.exit(1)

    portfolio = _load_portfolio()

    if side == "2":
        _run_sell(portfolio)
        return

    # ── Step 1: ticker ───────────────────────────────────────────
    raw = input("  Ticker / coin (e.g. NVDA, VOO, bitcoin): ").strip()
    if not raw:
        print("  ❌ Ticker cannot be empty.")
        sys.exit(1)

    # Try to find the ticker to determine its type before normalising
    bucket, asset = _find_ticker(portfolio, raw.upper())
    if asset is None:
        bucket, asset = _find_ticker(portfolio, raw.lower())

    asset_type = asset["type"] if asset else None
    ticker     = _normalise_ticker(raw, asset_type or "stock")

    # ── Step 2: quantity and price ───────────────────────────────
    qty_bought  = _get_float("  Quantity bought:                          ")
    price_paid  = _get_float("  Price paid per share/coin (USD):          ")
    trade_value = round(qty_bought * price_paid, 2)

    # ── Step 3: resolve ticker ───────────────────────────────────
    is_new = False

    if asset is None:
        # Re-check with the normalised ticker (handles mixed-case edge cases)
        bucket, asset = _find_ticker(portfolio, ticker)

    if asset is None:
        print(f"\n  '{ticker}' not found in your portfolio.")
        add = input("  Is this a new position? (y/n): ").strip().lower()
        if add != "y":
            print("  Aborted.")
            sys.exit(0)

        bucket     = _get_choice("  Enter bucket (Diversified / Growth / Crypto):  ", VALID_BUCKETS)
        asset_type = _get_choice("  Enter type   (stock / crypto):          ", VALID_TYPES)
        ticker     = _normalise_ticker(raw, asset_type)
        old_qty    = 0.0
        old_avg    = 0.0
        is_new     = True
    else:
        asset_type = asset["type"]
        old_qty    = asset["qty"]
        old_avg    = asset["avg_buy"]

    # ── Step 4: weighted average calculation ─────────────────────
    new_qty = round(old_qty + qty_bought, 8)
    new_avg = price_paid if old_qty == 0 else round(
        (old_qty * old_avg + qty_bought * price_paid) / new_qty, 2
    )

    # ── Step 5: confirm ──────────────────────────────────────────
    unit = UNIT[asset_type]
    print(f"""
  ─────────────────────────────
  Ticker:       {ticker}
  Bought:       {qty_bought} {unit} @ ${price_paid:,.2f}
  Trade value:  ${trade_value:,.2f}
  New qty:      {new_qty} {unit}
  New avg buy:  ${new_avg:,.2f}
  ─────────────────────────────""")

    confirm = input("\n  Confirm? (y/n): ").strip().lower()
    if confirm != "y":
        print("  Aborted — no changes made.")
        sys.exit(0)

    # ── Step 6: update portfolio/local.py ────────────────────────
    if is_new:
        _add_new_ticker(ticker, bucket, asset_type, new_qty, new_avg)
    else:
        _update_existing_ticker(ticker, new_qty, new_avg)

    # ── Step 7: log trade ─────────────────────────────────────────
    trade = {
        "id":          str(uuid.uuid4()),
        "timestamp":   datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "ticker":      ticker,
        "bucket":      bucket,
        "type":        asset_type,
        "qty_bought":  qty_bought,
        "price_paid":  price_paid,
        "trade_value": trade_value,
        "new_qty":     new_qty,
        "new_avg_buy": new_avg,
        "source":      "Revolut",
    }
    _append_trade(trade)

    # ── Step 8: confirmation output ───────────────────────────────
    print(f"""
  ✓ Trade logged
  ─────────────────────────────
  Ticker:       {ticker}
  Bought:       {qty_bought} {unit} @ ${price_paid:,.2f}
  Trade value:  ${trade_value:,.2f}
  New qty:      {new_qty} {unit}
  New avg buy:  ${new_avg:,.2f}
  ─────────────────────────────
  portfolio.local.py updated ✓
  data/trades.json updated   ✓

  Run 'python main.py' to see the updated briefing.
""")


if __name__ == "__main__":
    main()

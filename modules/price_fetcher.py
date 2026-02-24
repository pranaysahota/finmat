"""Fetches live stock/ETF prices from Yahoo Finance and crypto prices from CoinGecko."""

import sys
import time
from pathlib import Path

import requests

# Allow direct invocation (python modules/price_fetcher.py) as well as import
sys.path.insert(0, str(Path(__file__).parent.parent))

YAHOO_URL    = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
HEADERS      = {"User-Agent": "Mozilla/5.0"}
MAX_RETRIES  = 2
RETRY_DELAY  = 3  # seconds


def get_stock_price(ticker: str) -> float | None:
    """Fetch the latest market price for a stock or ETF from Yahoo Finance.

    Uses the unofficial Yahoo Finance chart API — no API key required.
    Retries up to MAX_RETRIES times with a RETRY_DELAY second pause between
    attempts, as the API occasionally returns empty responses on first try.

    Args:
        ticker: Stock ticker symbol e.g. "MSFT", "NVDA", "BRK.B".

    Returns:
        Current market price rounded to 2 decimal places, or None on any error.
    """
    url = YAHOO_URL.format(ticker=ticker)
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            response.raise_for_status()
            data  = response.json()
            price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
            return round(float(price), 2)
        except Exception as exc:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                print(f"  ⚠️  {ticker}: failed to fetch stock price — {exc}")
                return None
    return None


def get_crypto_price(coin_id: str) -> float | None:
    """Fetch the latest USD price for a cryptocurrency from CoinGecko.

    Uses the CoinGecko free API — no key required for the basic tier.
    Retries up to MAX_RETRIES times with a RETRY_DELAY second pause between
    attempts.

    Args:
        coin_id: CoinGecko coin ID e.g. "bitcoin", "ethereum".
                 Must match the key used in PORTFOLIO["Crypto"].

    Returns:
        Current USD price rounded to 2 decimal places, or None on any error.
    """
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.get(
                COINGECKO_URL,
                params={"ids": coin_id, "vs_currencies": "usd"},
                timeout=10,
            )
            response.raise_for_status()
            data  = response.json()
            price = data[coin_id]["usd"]
            return round(float(price), 2)
        except Exception as exc:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                print(f"  ⚠️  {coin_id}: failed to fetch crypto price — {exc}")
                return None
    return None


def get_all_prices(portfolio: dict) -> dict:
    """Fetch live prices for every asset in the portfolio.

    Iterates all buckets and assets, detects type ("stock" or "crypto"),
    and calls the appropriate fetch function. Prices are fetched for all
    tickers regardless of qty — planned positions (qty=0) still need a
    current price for display.

    Args:
        portfolio: The PORTFOLIO dict from config.py, structured as
                   {bucket: {ticker: {type, qty, avg_buy, ...}}}.

    Returns:
        Flat dict of {ticker: price} for every asset.
        A ticker whose fetch fails will map to None — never raises.
    """
    prices: dict = {}

    for bucket, holdings in portfolio.items():
        for symbol, asset in holdings.items():
            asset_type = asset.get("type")

            if asset_type == "crypto":
                fetched_price = get_crypto_price(symbol)
                icon          = "🪙"
            else:
                fetched_price = get_stock_price(symbol)
                icon          = "📈"

            prices[symbol] = fetched_price
            status = f"${fetched_price:,.2f}" if fetched_price is not None else "FAILED"
            print(f"  {icon} {symbol:<12} {status}")

    return prices


# ── Manual test ───────────────────────────────────────────────
if __name__ == "__main__":
    from config import PORTFOLIO

    print("\n── Fetching all prices ──\n")
    prices = get_all_prices(PORTFOLIO)

    print("\n── Results ──\n")
    for ticker, price in prices.items():
        if price is not None:
            print(f"  {ticker:<14} ${price:,.2f}")
        else:
            print(f"  {ticker:<14} FAILED")

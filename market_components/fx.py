"""
fx — Exchange Rate Utilities
=============================

Simple forex rate retrieval for non-US tickers.
"""

import os
import requests


def rate(pair: str = "AUD/USD") -> float:
    """Get forex exchange rate from Twelve Data."""
    key = os.environ.get("TWELVEDATA_API_KEY", "")
    r = requests.get(
        f"https://api.twelvedata.com/exchange_rate?symbol={pair}&apikey={key}",
        timeout=10,
    )
    return float(r.json().get("rate", 1.0))


def aud_usd() -> float:
    """Shorthand for AUD/USD rate."""
    return rate("AUD/USD")

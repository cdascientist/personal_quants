"""
datafetch — Market Data Retrieval
==================================

Functions for fetching live quotes, fundamentals, and candles.
Supports Finnhub (global) and Twelve Data (US) sources.
"""

import os
import requests
from datetime import datetime, timezone


class MarketClosedError(Exception):
    """Raised when API returns zero-price (market closed / holiday)."""
    pass


def quote_finnhub(ticker: str) -> dict:
    """Fetch live quote from Finnhub API.

    Returns
    -------
    {
        "current_price": float, "open": float, "high": float,
        "low": float, "prev_close": float,
        "dollar_change": float, "percent_change": float
    }

    Raises MarketClosedError if current_price == 0.
    """
    key = os.environ.get("FINNHUB_API_KEY", "")
    r = requests.get(
        f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={key}",
        timeout=10,
    )
    j = r.json()
    c = j.get("c", 0.0)
    if c == 0.0:
        raise MarketClosedError(f"{ticker}: current_price=0 (market closed)")
    o = j.get("o", c)
    pc = j.get("pc", c)
    return {
        "current_price": c,
        "open": o,
        "high": j.get("h", c),
        "low": j.get("l", c),
        "prev_close": pc,
        "dollar_change": c - pc,
        "percent_change": ((c - pc) / pc * 100) if pc else 0.0,
    }


def fundamentals_finnhub(ticker: str) -> dict:
    """Fetch fundamental metrics (P/E, 52w, market cap)."""
    key = os.environ.get("FINNHUB_API_KEY", "")
    r = requests.get(
        f"https://finnhub.io/api/v1/stock/metric?symbol={ticker}&metric=all&token={key}",
        timeout=10,
    )
    m = r.json().get("metric", {})
    return {
        "market_cap": m.get("marketCapitalization", 0),
        "pe_ratio": m.get("peBasicExclExtraTTM", 0),
        "high_52w": m.get("52WeekHigh", 0),
        "low_52w": m.get("52WeekLow", 0),
    }


def profile_finnhub(ticker: str) -> dict:
    """Fetch company profile (name, industry, exchange)."""
    key = os.environ.get("FINNHUB_API_KEY", "")
    r = requests.get(
        f"https://finnhub.io/api/v1/stock/profile2?symbol={ticker}&token={key}",
        timeout=10,
    )
    j = r.json()
    return {
        "name": j.get("name", ""),
        "industry": j.get("finnhubIndustry", ""),
        "exchange": j.get("exchange", ""),
    }


def candles_finnhub(ticker: str, resolution: str = "5", days: int = 1) -> list:
    """Fetch historical OHLCV candles from Finnhub.

    Parameters
    ----------
    ticker : str
    resolution : str   — "1", "5", "15", "30", "60", "D", "W", "M"
    days : int         — lookback in calendar days

    Returns list of dicts with keys: time, open, high, low, close, volume
    """
    key = os.environ.get("FINNHUB_API_KEY", "")
    to_ts = int(datetime.now(timezone.utc).timestamp())
    fr_ts = to_ts - days * 86400
    r = requests.get(
        f"https://finnhub.io/api/v1/stock/candle"
        f"?symbol={ticker}&resolution={resolution}"
        f"&from={fr_ts}&to={to_ts}&token={key}",
        timeout=10,
    )
    j = r.json()
    if j.get("s") != "ok":
        return []
    candles = []
    for i in range(len(j.get("t", []))):
        candles.append({
            "time": j["t"][i],
            "open": j["o"][i],
            "high": j["h"][i],
            "low": j["l"][i],
            "close": j["c"][i],
            "volume": j["v"][i],
        })
    return candles


def price_twelvedata(ticker: str) -> float:
    """Quick real-time price from Twelve Data."""
    key = os.environ.get("TWELVEDATA_API_KEY", "")
    r = requests.get(
        f"https://api.twelvedata.com/price?symbol={ticker}&apikey={key}",
        timeout=10,
    )
    return float(r.json().get("price", 0))


def candles_twelvedata(
    ticker: str,
    interval: str = "5min",
    outputsize: int = 100,
) -> list:
    """Fetch time-series candles from Twelve Data.

    Parameters
    ----------
    ticker : str
    interval : str  — "1min", "5min", "15min", "1day", "1week"
    outputsize : int

    Returns list of dicts with keys: datetime, open, high, low, close, volume
    """
    key = os.environ.get("TWELVEDATA_API_KEY", "")
    r = requests.get(
        f"https://api.twelvedata.com/time_series"
        f"?symbol={ticker}&interval={interval}"
        f"&outputsize={outputsize}&apikey={key}",
        timeout=10,
    )
    j = r.json()
    values = j.get("values", [])
    return [
        {
            "datetime": v["datetime"],
            "open": float(v["open"]),
            "high": float(v["high"]),
            "low": float(v["low"]),
            "close": float(v["close"]),
            "volume": int(v.get("volume", 0)),
        }
        for v in values
    ]


def exchange_rate(pair: str = "AUD/USD") -> float:
    """Get forex exchange rate from Twelve Data."""
    key = os.environ.get("TWELVEDATA_API_KEY", "")
    r = requests.get(
        f"https://api.twelvedata.com/exchange_rate"
        f"?symbol={pair}&apikey={key}",
        timeout=10,
    )
    return float(r.json().get("rate", 1.0))

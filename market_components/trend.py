"""
trend — Trend Bias Detection
=============================

Count higher-highs vs lower-lows in recent window.

Formulas
--------
    higher_highs = count(high[i] > high[i-1] for last N candles)
    lower_lows   = count(low[i]  < low[i-1]  for last N candles)
    bias = "bullish" if hh > ll else "bearish" if ll > hh else "neutral"
"""

from typing import List, Dict


WINDOW_SIZE = 10


def from_candles(candles: List[Dict]) -> dict:
    """Analyse trend bias from OHLCV candle list.

    Parameters
    ----------
    candles : list[dict]  — each dict must have "high" and "low" keys

    Returns
    -------
    {"bias": str, "hh": int, "ll": int}
    """
    if len(candles) < 3:
        return {"bias": "neutral", "hh": 0, "ll": 0}

    recent = candles[-min(WINDOW_SIZE, len(candles)):]
    hh = sum(
        1 for i in range(1, len(recent))
        if recent[i]["high"] > recent[i - 1]["high"]
    )
    ll = sum(
        1 for i in range(1, len(recent))
        if recent[i]["low"] < recent[i - 1]["low"]
    )
    bias = "bullish" if hh > ll else ("bearish" if ll > hh else "neutral")
    return {"bias": bias, "hh": hh, "ll": ll}

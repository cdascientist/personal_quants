"""
volatility — Volatility State & ATR
====================================

Uses coefficient-of-variation (CV) to classify market state,
and Average True Range (ATR) as an absolute measure.

Formulas
--------
    CV   = σ(P) / μ(P)
    ATR  = mean(max(high-low, |high-prev_close|, |low-prev_close|))

States
------
    "expanding"   — CV >= HIGH_VOL_CV
    "compressing" — CV <= LOW_VOL_CV
    "normal"      — between thresholds
"""

import statistics
from typing import List, Dict

from market_components.constants import HIGH_VOL_CV, LOW_VOL_CV


def state_from_prices(prices: List[float]) -> dict:
    """CV-based volatility classification.

    Parameters
    ----------
    prices : list[float]  — ordered close prices

    Returns
    -------
    {"state": str, "cv": float}
    """
    if len(prices) < 2:
        return {"state": "unknown", "cv": 0.0}
    mean_p = sum(prices) / len(prices)
    std_p = statistics.stdev(prices) if len(prices) > 1 else 0.0
    cv = std_p / mean_p if mean_p else 0.0
    state = (
        "expanding" if cv >= HIGH_VOL_CV
        else "compressing" if cv <= LOW_VOL_CV
        else "normal"
    )
    return {"state": state, "cv": round(cv, 6)}


def atr(candles: List[Dict]) -> float:
    """Average True Range over candle set.

    Parameters
    ----------
    candles : list[dict]  — each must have "high", "low", "close"/adj key

    Returns float (ATR value)
    """
    if len(candles) < 2:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        hl = candles[i]["high"] - candles[i]["low"]
        hpc = abs(candles[i]["high"] - candles[i - 1]["close"])
        lpc = abs(candles[i]["low"] - candles[i - 1]["close"])
        trs.append(max(hl, hpc, lpc))
    return sum(trs) / len(trs) if trs else 0.0

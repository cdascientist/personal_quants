"""
gbm — Geometric Brownian Motion Projections
============================================

Projects future price ranges using GBM.

Formula
-------
    S_t = S_0 × exp((μ - 0.5σ²) × t + σ × √t × Z)

Where:
    S_0 = current price
    μ   = drift (momentum-derived)
    σ   = annualized volatility estimate
    t   = time in years
    Z   = standard normal percentile (e.g., ±0.674 for 25th/75th)
"""

import math
from typing import List, Dict, Optional

from market_components.constants import (
    MINUTES_PER_YEAR,
    GBM_DRIFT_SCALING_FACTOR,
    Z_SCORE_25TH,
    Z_SCORE_75TH,
    Z_SCORE_95TH,
)


def project(
    current_price: float,
    momentum: float,
    horizon_minutes: int,
    vol_estimate: float,
) -> dict:
    """Single-horizon GBM projection with percentiles.

    Parameters
    ----------
    current_price  : float
    momentum       : float  — [-1, 1] momentum signal
    horizon_minutes: int    — projection horizon in minutes
    vol_estimate   : float  — annualized volatility (e.g. 0.25)

    Returns
    -------
    {
        "expected": float,         "median": float,
        "p25": float,              "p75": float,
        "p5": float,               "p95": float,
        "horizon_min": int,        "horizon_label": str
    }
    """
    t = horizon_minutes / MINUTES_PER_YEAR
    drift = momentum * GBM_DRIFT_SCALING_FACTOR * 0.1
    sqrt_t = t ** 0.5

    exp_component = (drift - 0.5 * vol_estimate ** 2) * t
    vol_sqrt_t = vol_estimate * sqrt_t

    expected = current_price * math.exp(exp_component)
    median = current_price * math.exp(exp_component)

    def _price_at_z(z: float) -> float:
        return current_price * math.exp(exp_component + vol_sqrt_t * z)

    # Format horizon label
    if horizon_minutes < 1440:
        label = f"{horizon_minutes}min"
    elif horizon_minutes < 43200:
        label = f"{horizon_minutes // 1440}d"
    else:
        label = f"{horizon_minutes // 43200}mth"

    return {
        "expected": round(expected, 4),
        "median": round(median, 4),
        "p25": round(_price_at_z(Z_SCORE_25TH), 4),
        "p75": round(_price_at_z(Z_SCORE_75TH), 4),
        "p5": round(_price_at_z(-Z_SCORE_95TH), 4),
        "p95": round(_price_at_z(Z_SCORE_95TH), 4),
        "horizon_min": horizon_minutes,
        "horizon_label": label,
    }


def multi_horizon(
    current_price: float,
    momentum: float,
    horizons: Optional[List[dict]] = None,
) -> List[dict]:
    """Run GBM across multiple time horizons.

    Parameters
    ----------
    current_price : float
    momentum      : float
    horizons      : list[{"label": str, "min": int, "vol": float}]

    Returns list of projection dicts.
    """
    if horizons is None:
        from market_components.constants import (
            GBM_VOLATILITY_INTRADAY,
            GBM_VOLATILITY_5DAY,
            GBM_VOLATILITY_30DAY,
            INTRADAY_INTERVALS,
            SHORT_TERM_DAYS,
            LONG_TERM_DAYS,
        )
        horizons = [
            {"label": "5min",  "min": 5 * INTRADAY_INTERVALS, "vol": GBM_VOLATILITY_INTRADAY},
            {"label": "5d",    "min": SHORT_TERM_DAYS * 1440,  "vol": GBM_VOLATILITY_5DAY},
            {"label": "30d",   "min": LONG_TERM_DAYS * 1440,   "vol": GBM_VOLATILITY_30DAY},
        ]
    return [project(current_price, momentum, h["min"], h["vol"]) for h in horizons]

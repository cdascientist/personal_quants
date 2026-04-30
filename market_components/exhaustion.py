"""
exhaustion — Z-Score Exhaustion Detection
==========================================

Exhaustion is detected when recent price deltas exceed ±2σ from their mean.

Formula
-------
    z = μ(ΔP) / σ(ΔP)
    exhausted = |z| > EXHAUSTION_Z_THRESHOLD
"""

import statistics
from typing import List

from market_components.constants import EXHAUSTION_Z_THRESHOLD


def from_price_deltas(prices: List[float]) -> dict:
    """Z-score exhaustion for a price series.

    Parameters
    ----------
    prices : list[float]  — ordered close prices, oldest first

    Returns
    -------
    {"exhausted": bool, "z_score": float}
    """
    if len(prices) < 3:
        return {"exhausted": False, "z_score": 0.0}
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    mean_d = sum(deltas) / len(deltas)
    std_d = statistics.stdev(deltas) if len(deltas) > 1 else 0.001
    z = mean_d / std_d if std_d else 0.0
    return {
        "exhausted": abs(z) > EXHAUSTION_Z_THRESHOLD,
        "z_score": round(z, 4),
    }

"""
momentum — Rate-of-Change Momentum
===================================

Formulas
--------
    Historical: M = clamp((avg(ΔP) / σ(ΔP)) × 0.5, -1, 1)
    Intraday:   M = clamp((P - P_open) / P_open / 0.10, -1, 1)

Constants defined in market_components.constants
"""

import statistics


def from_price_series(prices: list) -> float:
    """M = clamp((μ_Δ / σ) × 0.5, -1, 1)

    Parameters
    ----------
    prices : list[float]  — ordered close prices, oldest first

    Returns float in [-1.0, 1.0]
    """
    if len(prices) < 2:
        return 0.0
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    avg_d = sum(deltas) / len(deltas)
    vol = statistics.stdev(deltas) if len(deltas) > 1 else abs(avg_d) * 0.5
    if vol < 0.0001:
        vol = 0.0001
    return max(-1.0, min(1.0, (avg_d / vol) * 0.5))


def intraday(current: float, open_: float) -> float:
    """Intraday momentum from session open.

    M = clamp((P - P_open) / P_open / 0.10, -1, 1)

    Parameters
    ----------
    current : float  — current price
    open_   : float  — session open price

    Returns float in [-1.0, 1.0]
    """
    if open_ <= 0:
        return 0.0
    return max(-1.0, min(1.0, ((current - open_) / open_) / 0.10))

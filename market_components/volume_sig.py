"""
volume_sig — Volume Signal Analysis
====================================

Compares recent average volume against a longer-term baseline.

Formula
-------
    ratio = recent_5_candle_avg_vol / baseline_avg_vol
    "high"     if ratio >= VOL_HIGH
    "elevated" if ratio >= VOL_MED
    "normal"   otherwise
"""

from typing import List, Dict

from market_components.constants import VOL_HIGH, VOL_MED


def compare(candles: List[Dict], avg_volume: float = 0) -> str:
    """Classify recent volume impulse vs baseline.

    Parameters
    ----------
    candles     : list[dict]  — each must have "volume" key
    avg_volume  : float       — long-term average volume (0 = unknown)

    Returns
    -------
    "high" | "elevated" | "normal" | "unknown"
    """
    if len(candles) < 5 or avg_volume == 0:
        return "unknown"
    recent_vol = sum(c[-1]["volume"] for c in [candles[-5:]]) / 5
    intermed = sum(candles[i]["volume"] for i in range(-5, 0))
    recent_vol = intermed / 5
    ratio = recent_vol / avg_volume
    if ratio >= VOL_HIGH:
        return "high"
    if ratio >= VOL_MED:
        return "elevated"
    return "normal"

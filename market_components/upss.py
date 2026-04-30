"""
upss — UPSS Greek-Letter Signal Taxonomy
=========================================

Generates trade-action signals based on market conditions.

Signal Symbols
--------------
    α (alpha)    — buy (strong upward momentum)
    β (beta)     — add to position (moderate continuation)
    γ (gamma)    — collect premium (range-bound / compressing)
    δ (delta)    — sell / take profits (downward / exhaustion)
    Ω (omega+)   — speculative buy (compression breakout imminent)
    ε (epsilon)  — coil / wait (neutral, no clear direction)
    H            — protect / hedge (exhaustion or hedge trigger)
    ρ (rho)      — regime change (volatility expansion)
"""

from typing import List, Dict

from market_components.constants import MOM_HIGH, MOM_MED, UPSS_GAMMA_THRESHOLD


def generate(
    momentum: float,
    trend_bias: str,
    volatility_state: str,
    compression: float,
    is_exhausted: bool,
    is_hedged: bool,
    scalp_viable: bool,
) -> List[Dict]:
    """Generate UPSS signal list from current market conditions.

    Parameters are the same as signals.classify().

    Returns
    -------
    list[{"sym": str, "name": str, "dir": str, "conf": float}]
    """
    signals: List[Dict] = []

    # α — strong confirmation
    if abs(momentum) > MOM_HIGH:
        d = "bull" if momentum > 0 else "bear"
        signals.append({"sym": "α", "name": "alpha", "dir": d, "conf": min(1.0, abs(momentum) * 10)})

    # β — moderate confirmation
    elif abs(momentum) > MOM_MED:
        d = "bull" if momentum > 0 else "bear"
        signals.append({"sym": "β", "name": "beta", "dir": d, "conf": abs(momentum) * 20})

    # γ — compression / range
    if "compressing" in volatility_state:
        signals.append({"sym": "γ", "name": "gamma", "dir": "flat", "conf": 0.7})

    # δ — reversal / exhaustion
    if is_exhausted:
        d = "bull" if momentum < 0 else "bear"
        signals.append({"sym": "δ", "name": "delta", "dir": d, "conf": 0.85})

    # Ω — speculative breakout
    if "expanding" in volatility_state:
        signals.append({"sym": "Ω", "name": "omega", "dir": "flat", "conf": 0.6})

    # ρ — regime change
    if "expanding" in volatility_state and is_exhausted:
        signals.append({"sym": "H", "name": "hedge", "dir": "flat", "conf": 0.85})

    return signals

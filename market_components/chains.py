"""
chains — Active Chain Detection
================================

Detects trade-action chains from UPSS signals.

Chains
------
    PREMIUM_STACK   — gamma + epsilon → collect premium
    ASSIGNMENT      — omega+ + alpha  → assignment risk
    CLT_APPROACH    — price near cumulative liquidation threshold
    SCALP           — immediate scalp opportunity
    FULL_HEDGE      — H + delta → complete protection
"""

from typing import List, Dict

from market_components.constants import CLT_PROXIMITY_PCT


def detect(
    upss_signals: List[Dict],
    current_price: float,
    strike: float,
    cost_basis: float,
    clt_price: float,
    scalp_viable: bool,
) -> List[Dict]:
    """Detect active chains from UPSS signal list.

    Returns
    -------
    list[{"id": str, "signals": list[str], "confidence": float}]
    """
    chains: List[Dict] = []
    syms = [s["sym"] for s in upss_signals]

    # PREMIUM_STACK
    if "γ" in syms and "γ" in syms:
        conf = 0.85
        if "ε" in syms or "β" in syms:
            conf += 0.10
        chains.append({"id": "PREMIUM_STACK", "signals": ["γ", "ε", "γ"], "confidence": min(1.0, conf)})

    # ASSIGNMENT
    if "Ω" in syms and "α" in syms:
        conf = 0.75
        if "β" in syms:
            conf += 0.15
        chains.append({"id": "ASSIGNMENT_CHAIN", "signals": ["Ω", "α", "β"], "confidence": min(1.0, conf)})

    # CLT_APPROACH
    if clt_price > 0 and strike > 0:
        dist = abs(current_price - clt_price)
        threshold = strike * CLT_PROXIMITY_PCT
        if dist < threshold:
            prox = 1.0 - (dist / threshold)
            chains.append({"id": "CLT_APPROACH", "signals": ["H", "δ", "H"], "confidence": round(prox, 2)})

    # SCALP
    if scalp_viable:
        conf = 0.80
        if "ρ" in syms:
            conf += 0.10
        chains.append({"id": "SCALP_IMMEDIATE", "signals": ["ρ", "α", "δ"], "confidence": min(1.0, conf)})

    # FULL_HEDGE
    if "H" in syms and ("δ" in syms or "γ" in syms):
        chains.append({"id": "FULL_HEDGE", "signals": ["H", "δ", "H"], "confidence": 0.90})

    chains.sort(key=lambda c: c["confidence"], reverse=True)
    return chains

"""
signals — Signal Classification & Message Typing
=================================================

Classifies the overall market signal into direction, energy, and message type.

Formulas
--------
    direction = UP if (mom > 0.02 AND trend == up) OR mom > 0.05
              = DOWN if ...
    energy = HIGH / MEDIUM / LOW
    msg_type = composite of direction + energy + exhaustion + hedge + scalp
"""

from market_components.constants import MOM_HIGH, MOM_MED, VOL_HIGH, VOL_MED


def classify(
    momentum: float,
    trend_bias: str,
    volatility_state: str,
    compression: float,
    is_exhausted: bool,
    volume_impulse: float,
    is_hedged: bool,
    scalp_viable: bool,
    scalp_dir: str,
) -> tuple:
    """Return (direction, energy, msg_type).

    Parameters
    ----------
    momentum       : float   — momentum value [-1, 1]
    trend_bias     : str     — "bullish" | "bearish" | "neutral"
    volatility_state : str   — "expanding" | "compressing" | "normal"
    compression    : float   — compression factor [0, 1]
    is_exhausted   : bool
    volume_impulse : float   — recent/avg volume ratio
    is_hedged      : bool
    scalp_viable   : bool
    scalp_dir      : str     — "up" | "down" | ""

    Returns
    -------
    (direction: str, energy: str, msg_type: str)
    """
    # ── Direction ────────────────────────────────────────────
    if momentum > 0.02 and trend_bias == "bullish":
        direction = "UP"
    elif momentum < -0.02 and trend_bias == "bearish":
        direction = "DOWN"
    elif momentum > 0.05:
        direction = "UP"
    elif momentum < -0.05:
        direction = "DOWN"
    else:
        direction = "NEUTRAL"

    # ── Energy ───────────────────────────────────────────────
    mom_high = abs(momentum) > MOM_HIGH
    vol_high = volume_impulse > VOL_HIGH
    mom_med = abs(momentum) > MOM_MED
    vol_med = volume_impulse > VOL_MED

    if mom_high and vol_high:
        energy = "HIGH"
    elif mom_med or vol_med:
        energy = "MEDIUM"
    else:
        energy = "LOW"

    # ── Message Type ─────────────────────────────────────────
    if is_exhausted:
        msg_type = "momentum_exhaustion" if momentum > 0 else "dip_exhaustion"
    elif is_hedged:
        msg_type = "hedge_setup"
    elif scalp_viable:
        msg_type = {"up": "long_scalp", "down": "short_scalp"}.get(
            scalp_dir, "scalp_alert"
        )
    elif compression < 0.3 and volatility_state == "compressing":
        msg_type = "compression_building"
    elif direction == "UP" and energy == "HIGH":
        msg_type = "momentum_surge"
    elif direction == "DOWN" and energy == "HIGH":
        msg_type = "sell_pressure"
    elif direction == "UP" and energy == "MEDIUM":
        msg_type = "steady_climb"
    elif direction == "DOWN" and energy == "MEDIUM":
        msg_type = "gradual_decline"
    else:
        msg_type = "market_check"

    return direction, energy, msg_type

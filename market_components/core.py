"""
core — Pure Algorithmic Market Quants
======================================

Consolidated core calculation engine for VMQ+ market analysis.
No I/O, no network — just math.

Modules consolidated into this file:
  momentum    — rate-of-change momentum
  trend       — higher-highs / lower-lows detection
  volatility  — CV-based state + ATR
  exhaustion  — z-score exhaustion detection
  volume_sig  — volume impulse comparison
  upss        — UPSS Greek-letter signal taxonomy
  gbm         — Geometric Brownian Motion projections
  chains      — active trade chain detection

---
The VMQ+ Reference — for portable market calculations.
├── utils.py       ← data fetching, constants, signal classification
└── core.py        ← you are here (pure algorithmic quant calculations)
"""

import statistics
import math
from typing import List, Dict, Optional

from market_components.utils import (
    MINUTES_PER_YEAR, GBM_DRIFT_SCALING_FACTOR,
    Z_SCORE_25TH, Z_SCORE_75TH, Z_SCORE_95TH,
    EXHAUSTION_Z_THRESHOLD, HIGH_VOL_CV, LOW_VOL_CV,
    MOM_HIGH, MOM_MED, VOL_HIGH, VOL_MED,
    UPSS_GAMMA_THRESHOLD, CLT_PROXIMITY_PCT,
    GBM_VOLATILITY_INTRADAY, GBM_VOLATILITY_5DAY, GBM_VOLATILITY_30DAY,
    INTRADAY_INTERVALS, SHORT_TERM_DAYS, LONG_TERM_DAYS,
)


# ═════════════════════════════════════════════════════════════════════════════
# 1. MOMENTUM
# ═════════════════════════════════════════════════════════════════════════════


def momentum_from_prices(prices: list) -> float:
    """Historical price momentum: clamp((μ_Δ / σ) × 0.5, -1, 1)
    """
    if len(prices) < 2:
        return 0.0
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    avg_d = sum(deltas) / len(deltas)
    vol = statistics.stdev(deltas) if len(deltas) > 1 else abs(avg_d) * 0.5
    if vol < 0.0001:
        vol = 0.0001
    return max(-1.0, min(1.0, (avg_d / vol) * 0.5))


def momentum_intraday(current: float, open_: float) -> float:
    """Intraday momentum: clamp((P - P_open) / P_open / 0.10, -1, 1)
    """
    if open_ <= 0:
        return 0.0
    return max(-1.0, min(1.0, ((current - open_) / open_) / 0.10))


# ═════════════════════════════════════════════════════════════════════════════
# 2. TREND
# ═════════════════════════════════════════════════════════════════════════════


WINDOW_SIZE = 10


def trend_from_candles(candles: List[Dict]) -> dict:
    """Analyse trend bias by counting higher-highs vs lower-lows.

    Returns {"bias": str, "hh": int, "ll": int}
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


# ═════════════════════════════════════════════════════════════════════════════
# 3. VOLATILITY
# ═════════════════════════════════════════════════════════════════════════════


def volatility_state(prices: List[float]) -> dict:
    """CV-based volatility classification: expanding/compressing/normal.

    Returns {"state": str, "cv": float}
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


def atr_from_candles(candles: List[Dict]) -> float:
    """Average True Range over candle set.
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


# ═════════════════════════════════════════════════════════════════════════════
# 4. EXHAUSTION
# ═════════════════════════════════════════════════════════════════════════════


def exhaustion_zscore(prices: List[float]) -> dict:
    """Z-score exhaustion detection: |z| > 2σ = exhausted.

    Returns {"exhausted": bool, "z_score": float}
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


# ═════════════════════════════════════════════════════════════════════════════
# 5. VOLUME SIGNAL
# ═════════════════════════════════════════════════════════════════════════════


def volume_compare(candles: List[Dict], avg_volume: float = 0) -> str:
    """Classify recent volume vs baseline: high / elevated / normal / unknown.
    """
    if len(candles) < 5 or avg_volume == 0:
        return "unknown"
    intermed = sum(candles[i]["volume"] for i in range(-5, 0))
    recent_vol = intermed / 5
    ratio = recent_vol / avg_volume
    if ratio >= VOL_HIGH:
        return "high"
    if ratio >= VOL_MED:
        return "elevated"
    return "normal"


# ═════════════════════════════════════════════════════════════════════════════
# 6. UPSS SIGNAL TAXONOMY
# ═════════════════════════════════════════════════════════════════════════════


def upss_generate(
    momentum: float,
    trend_bias: str,
    volatility_state: str,
    compression: float,
    is_exhausted: bool,
    is_hedged: bool,
    scalp_viable: bool,
) -> List[Dict]:
    """Generate UPSS Greek-letter signals from market conditions.

    Returns list[{"sym": str, "name": str, "dir": str, "conf": float}]
    """
    signals: List[Dict] = []

    # α — strong directional confirmation (MOM > 0.03)
    if abs(momentum) > MOM_HIGH:
        d = "bull" if momentum > 0 else "bear"
        signals.append({
            "sym": "α", "name": "alpha", "dir": d,
            "conf": min(1.0, abs(momentum) * 10),
        })

    # β — moderate directional (MOM > 0.01)
    elif abs(momentum) > MOM_MED:
        d = "bull" if momentum > 0 else "bear"
        signals.append({
            "sym": "β", "name": "beta", "dir": d,
            "conf": abs(momentum) * 20,
        })

    # γ — compression / range-bound
    if "compressing" in volatility_state:
        signals.append({
            "sym": "γ", "name": "gamma", "dir": "flat", "conf": 0.7,
        })

    # δ — exhaustion reversal signal
    if is_exhausted:
        d = "bull" if momentum < 0 else "bear"
        signals.append({
            "sym": "δ", "name": "delta", "dir": d, "conf": 0.85,
        })

    # Ω — volatility expansion (breakout coil)
    if "expanding" in volatility_state:
        signals.append({
            "sym": "Ω", "name": "omega", "dir": "flat", "conf": 0.6,
        })

    # H — hedge / protect (exhaustion + expansion)
    if "expanding" in volatility_state and is_exhausted:
        signals.append({
            "sym": "H", "name": "hedge", "dir": "flat", "conf": 0.85,
        })

    return signals


# ═════════════════════════════════════════════════════════════════════════════
# 7. GBM PRICE PROJECTIONS
# ═════════════════════════════════════════════════════════════════════════════


def gbm_project(
    current_price: float,
    momentum: float,
    horizon_minutes: int,
    vol_estimate: float,
) -> dict:
    """Single-horizon GBM projection with percentiles.

    S_t = S_0 × exp((μ − 0.5σ²) × t + σ × √t × Z)

    Returns dict with expected, median, p25, p75, p5, p95, horizon_min, label.
    """
    t = horizon_minutes / MINUTES_PER_YEAR
    drift = momentum * GBM_DRIFT_SCALING_FACTOR * 0.1
    sqrt_t = t ** 0.5

    exp_component = (drift - 0.5 * vol_estimate ** 2) * t
    vol_sqrt_t = vol_estimate * sqrt_t

    expected = current_price * math.exp(exp_component)
    median_val = current_price * math.exp(exp_component)

    def _at_z(z: float) -> float:
        return current_price * math.exp(exp_component + vol_sqrt_t * z)

    # Horizon label
    if horizon_minutes < 1440:
        label = f"{horizon_minutes}min"
    elif horizon_minutes < 43200:
        label = f"{horizon_minutes // 1440}d"
    else:
        label = f"{horizon_minutes // 43200}mth"

    return {
        "expected": round(expected, 4),
        "median": round(median_val, 4),
        "p25": round(_at_z(Z_SCORE_25TH), 4),
        "p75": round(_at_z(Z_SCORE_75TH), 4),
        "p5": round(_at_z(-Z_SCORE_95TH), 4),
        "p95": round(_at_z(Z_SCORE_95TH), 4),
        "horizon_min": horizon_minutes,
        "horizon_label": label,
    }


def gbm_multi_horizon(
    current_price: float,
    momentum: float,
    horizons: Optional[List[dict]] = None,
) -> List[dict]:
    """GBM across multiple time horizons.

    Default horizons: intraday (~90min), 5-day, 30-day (mth).
    """
    if horizons is None:
        horizons = [
            {"label": "intraday", "min": 5 * INTRADAY_INTERVALS,
             "vol": GBM_VOLATILITY_INTRADAY},
            {"label": "5d", "min": SHORT_TERM_DAYS * 1440,
             "vol": GBM_VOLATILITY_5DAY},
            {"label": "1mth", "min": LONG_TERM_DAYS * 1440,
             "vol": GBM_VOLATILITY_30DAY},
        ]
    return [
        gbm_project(current_price, momentum, h["min"], h["vol"])
        for h in horizons
    ]


# ═════════════════════════════════════════════════════════════════════════════
# 8. CHAIN DETECTION
# ═════════════════════════════════════════════════════════════════════════════


def chains_detect(
    upss_signals: List[Dict],
    current_price: float,
    strike: float,
    cost_basis: float,
    clt_price: float,
    scalp_viable: bool,
) -> List[Dict]:
    """Detect active trading chains from UPSS signals.

    Returns list[{"id": str, "signals": list[str], "confidence": float}]
    """
    chains: List[Dict] = []
    syms = [s["sym"] for s in upss_signals]

    # PREMIUM_STACK — gamma collect premium
    if "γ" in syms:
        conf = 0.85
        if "β" in syms:
            conf += 0.10
        chains.append({
            "id": "PREMIUM_STACK", "signals": ["γ", "β", "γ"],
            "confidence": min(1.0, conf),
        })

    # ASSIGNMENT_CHAIN — omega + alpha
    if "Ω" in syms and "α" in syms:
        conf = 0.75
        if "β" in syms:
            conf += 0.15
        chains.append({
            "id": "ASSIGNMENT_CHAIN", "signals": ["Ω", "α", "β"],
            "confidence": min(1.0, conf),
        })

    # CLT_APPROACH — near liquidation threshold
    if clt_price > 0 and strike > 0:
        dist = abs(current_price - clt_price)
        threshold = strike * CLT_PROXIMITY_PCT
        if dist < threshold:
            prox = 1.0 - (dist / threshold)
            chains.append({
                "id": "CLT_APPROACH", "signals": ["H", "δ", "H"],
                "confidence": round(prox, 2),
            })

    # SCALP_IMMEDIATE
    if scalp_viable:
        conf = 0.80
        if "ρ" in [s["sym"] for s in upss_signals if "ρ" == s["sym"]]:
            conf += 0.10
        chains.append({
            "id": "SCALP_IMMEDIATE", "signals": ["ρ", "α", "δ"],
            "confidence": min(1.0, conf),
        })

    # FULL_HEDGE — H + delta/gamma
    if "H" in syms and ("δ" in syms or "γ" in syms):
        chains.append({
            "id": "FULL_HEDGE", "signals": ["H", "δ", "H"],
            "confidence": 0.90,
        })

    chains.sort(key=lambda c: c["confidence"], reverse=True)
    return chains

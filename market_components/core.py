"""
core — Pure Algorithmic Market Quants
======================================

Sandboxed calculation engine for VMQ+ market analysis.
No I/O, no network — just math. Fully self-contained: import functions
for production alerts, or run directly for sandboxed simulation.

Modules consolidated into this file:
  1  momentum    — rate-of-change momentum (historical + intraday)
  2  trend       — higher-highs / lower-lows bias detection
  3  volatility  — CV-based regime classification + ATR
  4  exhaustion  — z-score exhaustion detection
  5  volume_sig  — volume impulse ratio
  6  upss        — Greek-letter signal taxonomy (alpha beta gamma delta omega H)
  7  gbm         — Geometric Brownian Motion price projections
  8  chains      — active trade chain detection (PREMIUM_STACK, CLT, etc.)

Sandbox (SECTION 9) provides static test data and runnable simulations
that mirror the alert output format.

---
Usage:
    # As a module — production alerts import functions:
    from market_components.core import momentum_from_prices, upss_generate

    # As a sandbox — run directly to see simulated alerts:
    python3 market_components/core.py          # Run ALL tests
    python3 market_components/core.py --quick   # Quick smoke test
    python3 market_components/core.py --symbol BULL_RUN  # Run specific test

---
The VMQ+ Reference — for portable market calculations.
in utils.py  <-- data fetching, constants, signal classification
in core.py   <-- you are here (pure algorithmic quants + sandbox)
"""

import statistics
import math
import sys
import os
from typing import List, Dict, Optional


# [0.0] Add parent dir to sys.path so both direct-run and import-run work
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.dirname(_THIS_DIR)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)


# -- 0. IMPORTS --------------------------------------------------------------
# Constants from utils: tunables that drive threshold checks below.
from market_components.utils import (
    MINUTES_PER_YEAR,
    GBM_DRIFT_SCALING_FACTOR,
    Z_SCORE_25TH,
    Z_SCORE_75TH,
    Z_SCORE_95TH,
    EXHAUSTION_Z_THRESHOLD,
    HIGH_VOL_CV,
    LOW_VOL_CV,
    MOM_HIGH,
    MOM_MED,
    VOL_HIGH,
    VOL_MED,
    CLT_PROXIMITY_PCT,
    GBM_VOLATILITY_INTRADAY,
    GBM_VOLATILITY_5DAY,
    GBM_VOLATILITY_30DAY,
    INTRADAY_INTERVALS,
    SHORT_TERM_DAYS,
    LONG_TERM_DAYS,
)


# ═════════════════════════════════════════════════════════════════════════════
# 1. MOMENTUM — rate-of-change scoring
#    Formula:  M = clamp((mu_Delta / sigma_Delta) x 0.5, -1, +1)
#    where mu_Delta = mean(price_deltas), sigma_Delta = std(price_deltas)
#    Positive M = rising prices, negative M = falling.
# ═════════════════════════════════════════════════════════════════════════════

def momentum_from_prices(prices: list) -> float:
    """
    [1.1] Historical price momentum via mean/std of deltas.
    Input:  prices = [float, ...] at least length 2
    Output: float in [-1.0, +1.0]
    Edge:   returns 0.0 if fewer than 2 prices
    """
    if len(prices) < 2:
        return 0.0
    # [1.1a] Compute price deltas: P_t - P_t-1 for each consecutive pair
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    # [1.1b] Mean delta — direction signal
    avg_d = sum(deltas) / len(deltas)
    # [1.1c] Std delta — volatility normalization factor
    vol = statistics.stdev(deltas) if len(deltas) > 1 else abs(avg_d) * 0.5
    # [1.1d] Floor to prevent division by zero
    if vol < 0.0001:
        vol = 0.0001
    # [1.1e] Clamp to [-1, +1] and scale by 0.5
    return max(-1.0, min(1.0, (avg_d / vol) * 0.5))


def momentum_intraday(current: float, open_: float) -> float:
    """
    [1.2] Intraday momentum relative to open price.
    Formula:  M = clamp((P - P_open) / P_open / 0.10, -1, +1)
    Input:  current=float, open_=float
    Output: float in [-1.0, +1.0]
    Edge:   returns 0.0 if open_ <= 0
    """
    if open_ <= 0:
        return 0.0
    # [1.2a] Normalize by open price, divide by 10pct reference
    return max(-1.0, min(1.0, ((current - open_) / open_) / 0.10))


# ═════════════════════════════════════════════════════════════════════════════
# 2. TREND BIAS — higher-high vs lower-low counting
#    Compares count of HH vs LL over a WINDOW_SIZE lookback.
#    HH = current high > previous high, LL = current low < previous low.
# ═════════════════════════════════════════════════════════════════════════════

WINDOW_SIZE = 10   # [2.0] Lookback window for trend HH/LL counting

def trend_from_candles(candles: List[Dict]) -> dict:
    """
    [2.1] Count higher-highs vs lower-lows in recent candles.
    Input:  candles = [{"high": float, "low": float}, ...]
    Output: {"bias": str, "hh": int, "ll": int}
            bias in ("bullish", "bearish", "neutral")
    Edge:   returns neutral if fewer than 3 candles
    """
    if len(candles) < 3:
        return {"bias": "neutral", "hh": 0, "ll": 0}
    # [2.1a] Take last WINDOW_SIZE candles (or fewer if not enough data)
    recent = candles[-min(WINDOW_SIZE, len(candles)):]
    # [2.1b] Count how many candles had a higher high than prev
    hh = sum(
        1 for i in range(1, len(recent))
        if recent[i]["high"] > recent[i - 1]["high"]
    )
    # [2.1c] Count how many candles had a lower low than prev
    ll = sum(
        1 for i in range(1, len(recent))
        if recent[i]["low"] < recent[i - 1]["low"]
    )
    # [2.1d] Majority vote for bias
    bias = "bullish" if hh > ll else ("bearish" if ll > hh else "neutral")
    return {"bias": bias, "hh": hh, "ll": ll}


# ═════════════════════════════════════════════════════════════════════════════
# 3. VOLATILITY — regime classification + ATR
#    CV = sigma / mu  (coefficient of variation over price window)
#    State:  CV >= HIGH_VOL_CV(0.03) -> "expanding"
#            CV <= LOW_VOL_CV(0.01)  -> "compressing"
#            otherwise               -> "normal"
#    ATR = mean(max(HL, H-PC, L-PC)) across consecutive candles
# ═════════════════════════════════════════════════════════════════════════════

def volatility_state(prices: List[float]) -> dict:
    """
    [3.1] CV-based volatility regime classification.
    Input:  prices = [float, ...] at least length 2
    Output: {"state": str, "cv": float}
    Edge:   returns unknown/CV=0 if fewer than 2 prices
    """
    if len(prices) < 2:
        return {"state": "unknown", "cv": 0.0}
    # [3.1a] Mean and std of price series
    mean_p = sum(prices) / len(prices)
    std_p = statistics.stdev(prices) if len(prices) > 1 else 0.0
    # [3.1b] Coefficient of variation = std / mean
    cv = std_p / mean_p if mean_p else 0.0
    # [3.1c] Classify by CV thresholds
    state = (
        "expanding" if cv >= HIGH_VOL_CV
        else "compressing" if cv <= LOW_VOL_CV
        else "normal"
    )
    return {"state": state, "cv": round(cv, 6)}


def atr_from_candles(candles: List[Dict]) -> float:
    """
    [3.2] Average True Range over candle set.
    Input:  candles = [{"high": float, "low": float, "close": float}, ...]
    Output: float (ATR in price units)
    Edge:   returns 0.0 if fewer than 2 candles
    """
    if len(candles) < 2:
        return 0.0
    # [3.2a] True Range = max(High-Low, High-PrevClose, Low-PrevClose)
    trs = []
    for i in range(1, len(candles)):
        hl = candles[i]["high"] - candles[i]["low"]
        hpc = abs(candles[i]["high"] - candles[i - 1]["close"])
        lpc = abs(candles[i]["low"] - candles[i - 1]["close"])
        trs.append(max(hl, hpc, lpc))
    # [3.2b] ATR = mean of true ranges
    return sum(trs) / len(trs) if trs else 0.0


# ═════════════════════════════════════════════════════════════════════════════
# 4. EXHAUSTION — z-score detection
#    Calculates z-score of price deltas.
#    |z| > EXHAUSTION_Z_THRESHOLD(2.0) = exhausted signal.
#    Positive z = upward exhaustion (sell signal).
#    Negative z = downward exhaustion (buy signal).
# ═════════════════════════════════════════════════════════════════════════════

def exhaustion_zscore(prices: List[float]) -> dict:
    """
    [4.1] Z-score of price deltas for exhaustion detection.
    Input:  prices = [float, ...] at least length 3
    Output: {"exhausted": bool, "z_score": float}
    Edge:   exhausted=false, z=0 if fewer than 3 prices
    """
    if len(prices) < 3:
        return {"exhausted": False, "z_score": 0.0}
    # [4.1a] Compute deltas
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    # [4.1b] Mean and std of deltas
    mean_d = sum(deltas) / len(deltas)
    std_d = statistics.stdev(deltas) if len(deltas) > 1 else 0.001
    # [4.1c] Z-score = mean / std (how many stds from zero?)
    z = mean_d / std_d if std_d else 0.0
    return {
        "exhausted": abs(z) > EXHAUSTION_Z_THRESHOLD,
        "z_score": round(z, 4),
    }


# ═════════════════════════════════════════════════════════════════════════════
# 5. VOLUME SIGNAL — recent vs baseline comparison
#    Ratio = avg(recent 5 candles volume) / baseline avg_volume
#    Threshold: >= VOL_HIGH(1.5)  -> "high"
#               >= VOL_MED(1.2)   -> "elevated"
#               otherwise         -> "normal"
# ═════════════════════════════════════════════════════════════════════════════

def volume_compare(candles: List[Dict], avg_volume: float = 0) -> str:
    """
    [5.1] Classify recent volume relative to baseline.
    Input:  candles = [{"volume": int}, ...] at least 5
            avg_volume = float (typical daily volume)
    Output: str in ("high", "elevated", "normal", "unknown")
    Edge:   returns "unknown" if fewer than 5 candles or avg=0
    """
    if len(candles) < 5 or avg_volume == 0:
        return "unknown"
    # [5.1a] Average volume over last 5 candles
    intermed = sum(candles[i]["volume"] for i in range(-5, 0))
    recent_vol = intermed / 5
    # [5.1b] Ratio of recent avg to baseline avg
    ratio = recent_vol / avg_volume
    # [5.1c] Classify by thresholds
    if ratio >= VOL_HIGH:
        return "high"
    if ratio >= VOL_MED:
        return "elevated"
    return "normal"


# ═════════════════════════════════════════════════════════════════════════════
# 6. UPSS SIGNAL TAXONOMY — Greek-letter market state classification
#    Generates signal symbols from current market conditions.
#      alpha (a)   -- strong directional, |M| > 0.03
#      beta (b)    -- moderate directional, |M| > 0.01
#      gamma (g)   -- compression/range-bound
#      delta (d)   -- exhaustion reversal
#      omega (O)   -- volatility expansion (breakout coil)
#      H (hedge)   -- exhaustion + expansion = protect position
#      rho (r)     -- scalp viability (external signal, passed in)
# ═════════════════════════════════════════════════════════════════════════════

def upss_generate(
    momentum_val: float,
    trend_bias: str,
    vol_state: str,
    compression: float,
    is_exhausted: bool,
    is_hedged: bool,
    scalp_viable: bool,
) -> List[Dict]:
    """
    [6.1] Generate UPSS signals from current market conditions.
    Input:  momentum_val=float, trend_bias=str, vol_state=str,
            compression=float, is_exhausted=bool, is_hedged=bool,
            scalp_viable=bool
    Output: [{"sym": str, "name": str, "dir": str, "conf": float}, ...]
    """
    signals: List[Dict] = []

    # [6.2] alpha -- strong directional confirmation (|M| > MOM_HIGH=0.03)
    if abs(momentum_val) > MOM_HIGH:
        d = "bull" if momentum_val > 0 else "bear"
        signals.append({
            "sym": "α", "name": "alpha", "dir": d,
            "conf": min(1.0, abs(momentum_val) * 10),
        })
    # [6.3] beta -- moderate directional (|M| > MOM_MED=0.01)
    elif abs(momentum_val) > MOM_MED:
        d = "bull" if momentum_val > 0 else "bear"
        signals.append({
            "sym": "β", "name": "beta", "dir": d,
            "conf": abs(momentum_val) * 20,
        })
    # [6.4] gamma -- compression / range-bound
    if "compressing" in vol_state:
        signals.append({
            "sym": "γ", "name": "gamma", "dir": "flat", "conf": 0.7,
        })
    # [6.5] delta -- exhaustion reversal (opposite of momentum direction)
    if is_exhausted:
        d = "bull" if momentum_val < 0 else "bear"
        signals.append({
            "sym": "δ", "name": "delta", "dir": d, "conf": 0.85,
        })
    # [6.6] omega -- volatility expansion (breakout coil)
    if "expanding" in vol_state:
        signals.append({
            "sym": "Ω", "name": "omega", "dir": "flat", "conf": 0.6,
        })
    # [6.7] H -- hedge / protect (simultaneous exhaustion + expansion)
    if "expanding" in vol_state and is_exhausted:
        signals.append({
            "sym": "H", "name": "hedge", "dir": "flat", "conf": 0.85,
        })

    return signals


# ═════════════════════════════════════════════════════════════════════════════
# 7. GBM PRICE PROJECTIONS — Geometric Brownian Motion
#    Formula:  S_t = S_0 x exp((mu - 0.5*sigma^2) x t + sigma x sqrt(t) x Z)
#    where t = horizon_minutes / MINUTES_PER_YEAR(525600)
#          mu = momentum x GBM_DRIFT_SCALING_FACTOR(0.5) x 0.1
#          sigma = volatility estimate (per horizon)
#          Z = z-score for percentile (p5=-1.645, p25=-0.674,
#              p50=0, p75=+0.674, p95=+1.645)
# ═════════════════════════════════════════════════════════════════════════════

def gbm_project(
    current_price: float,
    momentum_val: float,
    horizon_minutes: int,
    vol_estimate: float,
) -> dict:
    """
    [7.1] Single-horizon GBM projection with percentile range.
    Input:  current_price=float, momentum_val=float,
            horizon_minutes=int, vol_estimate=float
    Output: dict with expected, median, p25, p75, p5, p95
    """
    # [7.2] Convert horizon minutes to annualized time fraction
    t = horizon_minutes / MINUTES_PER_YEAR
    # [7.3] Drift term from momentum signal
    drift = momentum_val * GBM_DRIFT_SCALING_FACTOR * 0.1
    sqrt_t = t ** 0.5

    # [7.4] GBM exponent: (mu - 0.5*sigma^2)*t
    exp_component = (drift - 0.5 * vol_estimate ** 2) * t
    # [7.5] Volatility component: sigma * sqrt(t)
    vol_sqrt_t = vol_estimate * sqrt_t

    # [7.6] Expected = median for lognormal with deterministic drift
    expected = current_price * math.exp(exp_component)
    median_val = current_price * math.exp(exp_component)

    # [7.7] Price at a given z-score percentile
    def _at_z(z: float) -> float:
        return current_price * math.exp(exp_component + vol_sqrt_t * z)

    # [7.8] Human-readable horizon label
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
    momentum_val: float,
    horizons: Optional[List[dict]] = None,
) -> List[dict]:
    """
    [7.9] GBM across three default time horizons.
    Input:  current_price=float, momentum_val=float,
            horizons=Optional[List[dict]]
            Each horizon: {"label": str, "min": int, "vol": float}
    Output: [dict, ...]  one gbm_project result per horizon
    Default: intraday (~90min), 5-day, 30-day
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
        gbm_project(current_price, momentum_val, h["min"], h["vol"])
        for h in horizons
    ]


# ═════════════════════════════════════════════════════════════════════════════
# 8. CHAIN DETECTION — active trade chain classification
#    Identifies trading chain patterns from UPSS signals:
#      PREMIUM_STACK    -- gamma + beta = collect premium opportunity
#      ASSIGNMENT_CHAIN -- omega + alpha = directional assignment risk
#      CLT_APPROACH     -- price near liquidation threshold
#      SCALP_IMMEDIATE  -- rho-based scalp opportunity
#      FULL_HEDGE       -- H + delta/gamma = full protection setup
# ═════════════════════════════════════════════════════════════════════════════

def chains_detect(
    upss_signals: List[Dict],
    current_price: float,
    strike: float,
    cost_basis: float,
    clt_price: float,
    scalp_viable: bool,
) -> List[Dict]:
    """
    [8.1] Detect active chain patterns from UPSS signals + position data.
    Input:  upss_signals=[{sym, name, dir, conf}, ...]
            current_price=float, strike=float, cost_basis=float,
            clt_price=float, scalp_viable=bool
    Output: [{"id": str, "signals": [str], "confidence": float}, ...]
            sorted by confidence descending
    """
    chains: List[Dict] = []
    syms = [s["sym"] for s in upss_signals]

    # [8.2] PREMIUM_STACK -- gamma present = collect premium
    if "γ" in syms:
        conf = 0.85
        if "β" in syms:
            conf += 0.10
        chains.append({
            "id": "PREMIUM_STACK", "signals": ["γ", "β", "γ"],
            "confidence": min(1.0, conf),
        })

    # [8.3] ASSIGNMENT_CHAIN -- omega + alpha = directional risk
    if "Ω" in syms and "α" in syms:
        conf = 0.75
        if "β" in syms:
            conf += 0.15
        chains.append({
            "id": "ASSIGNMENT_CHAIN", "signals": ["Ω", "α", "β"],
            "confidence": min(1.0, conf),
        })

    # [8.4] CLT_APPROACH -- price near liquidation threshold
    #       Proximity = 1 - (distance / threshold) where threshold = strike x 10pct
    if clt_price > 0 and strike > 0:
        dist = abs(current_price - clt_price)
        threshold = strike * CLT_PROXIMITY_PCT
        if dist < threshold:
            prox = 1.0 - (dist / threshold)
            chains.append({
                "id": "CLT_APPROACH", "signals": ["H", "δ", "H"],
                "confidence": round(prox, 2),
            })

    # [8.5] SCALP_IMMEDIATE -- rho-based scalp opportunity
    if scalp_viable:
        conf = 0.80
        if "ρ" in [s["sym"] for s in upss_signals if s["sym"] == "ρ"]:
            conf += 0.10
        chains.append({
            "id": "SCALP_IMMEDIATE", "signals": ["ρ", "α", "δ"],
            "confidence": min(1.0, conf),
        })

    # [8.6] FULL_HEDGE -- H with delta or gamma = full protection
    if "H" in syms and ("δ" in syms or "γ" in syms):
        chains.append({
            "id": "FULL_HEDGE", "signals": ["H", "δ", "H"],
            "confidence": 0.90,
        })

    # [8.7] Sort chains by confidence descending
    chains.sort(key=lambda c: c["confidence"], reverse=True)
    return chains


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 9 -- SANDBOX: Static test data + simulation runner
#
# This section is ONLY executed when core.py is run directly (not imported).
# It provides:
#   A. Static test price/candle data for each module
#   B. A simulation runner function that displays alert-like output
#   C. CLI entry points: --all (default), --quick, --symbol <NAME>
#
# Each test function mirrors the output format a production alert would
# generate, allowing you to validate the math without real market data.
# ═════════════════════════════════════════════════════════════════════════════

# [S9.1] Static test data -- 4 scenarios covering all 8 modules ---------------

TEST_DATA = {
    # [S9.1.1] Rising prices -- positive momentum, bullish trend
    "BULL_RUN": {
        "prices": [100.0, 101.5, 103.0, 104.2, 105.8],
        "candles": [
            {"high": 101.5, "low": 99.5, "close": 101.0, "volume": 50000},
            {"high": 103.0, "low": 101.0, "close": 102.5, "volume": 52000},
            {"high": 104.5, "low": 102.0, "close": 103.8, "volume": 48000},
            {"high": 105.0, "low": 103.5, "close": 104.5, "volume": 55000},
            {"high": 106.5, "low": 104.0, "close": 105.8, "volume": 60000},
            {"high": 107.0, "low": 105.5, "close": 106.2, "volume": 58000},
            {"high": 108.0, "low": 106.0, "close": 107.5, "volume": 62000},
        ],
        "current_price": 107.5, "open_price": 100.0,
        "avg_volume": 50000, "strike": 110.0,
        "cost_basis": 105.0, "clt_price": 99.0,
        "desc": "Steady uptrend -- expect +momentum, bullish, no exhaustion",
    },
    # [S9.1.2] Falling prices -- negative momentum, bearish trend
    "BEAR_SLIDE": {
        "prices": [105.0, 103.5, 102.0, 100.5, 99.0],
        "candles": [
            {"high": 105.5, "low": 104.0, "close": 105.0, "volume": 45000},
            {"high": 104.0, "low": 102.5, "close": 103.2, "volume": 47000},
            {"high": 103.0, "low": 101.0, "close": 101.8, "volume": 50000},
            {"high": 102.0, "low": 100.0, "close": 100.5, "volume": 52000},
            {"high": 101.0, "low": 98.5, "close": 99.0, "volume": 55000},
            {"high": 100.0, "low": 98.0, "close": 98.5, "volume": 58000},
            {"high": 99.5, "low": 97.0, "close": 97.8, "volume": 60000},
        ],
        "current_price": 97.8, "open_price": 105.0,
        "avg_volume": 50000, "strike": 95.0,
        "cost_basis": 100.0, "clt_price": 110.0,
        "desc": "Steady downtrend -- expect -momentum, bearish, no exhaustion",
    },
    # [S9.1.3] Choppy / range-bound -- low momentum, neutral trend
    "SIDEWAYS": {
        "prices": [100.0, 100.5, 99.8, 100.2, 100.1],
        "candles": [
            {"high": 101.0, "low": 99.5, "close": 100.5, "volume": 30000},
            {"high": 100.8, "low": 99.3, "close": 99.8, "volume": 28000},
            {"high": 101.2, "low": 99.0, "close": 100.2, "volume": 32000},
            {"high": 100.5, "low": 99.8, "close": 100.1, "volume": 31000},
            {"high": 101.0, "low": 99.5, "close": 100.3, "volume": 29000},
        ],
        "current_price": 100.3, "open_price": 100.0,
        "avg_volume": 30000, "strike": 100.0,
        "cost_basis": 100.0, "clt_price": 90.0,
        "desc": "Range-bound -- expect ~0 momentum, neutral, compressing vol",
    },
    # [S9.1.4] Violent spike then pullback -- high vol, exhaustion
    "VOLATILE_SPIKE": {
        "prices": [100.0, 105.0, 110.0, 108.0, 106.0],
        "candles": [
            {"high": 102.0, "low": 99.0, "close": 100.0, "volume": 40000},
            {"high": 108.0, "low": 101.0, "close": 105.0, "volume": 80000},
            {"high": 115.0, "low": 107.0, "close": 110.0, "volume": 120000},
            {"high": 112.0, "low": 106.0, "close": 108.0, "volume": 90000},
            {"high": 109.0, "low": 104.0, "close": 106.0, "volume": 75000},
            {"high": 107.0, "low": 104.5, "close": 105.0, "volume": 65000},
            {"high": 106.0, "low": 103.0, "close": 104.0, "volume": 60000},
        ],
        "current_price": 104.0, "open_price": 100.0,
        "avg_volume": 40000, "strike": 100.0,
        "cost_basis": 100.0, "clt_price": 95.0,
        "desc": "Sharp spike then pullback -- expect exhaustion, expanding vol",
    },
}


# [S9.2] Simulation runner -- produces alert-like output ----------------------

def run_simulation(name: str, data: dict) -> List[str]:
    """
    [S9.2.1] Run all 8 VMQ+ modules against a static test data set.
    Input:  name=str (test case name), data=dict (from TEST_DATA)
    Output: [str, ...] formatted output lines
    """
    lines = []
    sep = "-" * 52

    # [S9.2.2] Extract data
    prices = data["prices"]
    candles = data["candles"]
    cp = data["current_price"]
    op = data["open_price"]
    avg_vol = data.get("avg_volume", 50000)
    strike = data.get("strike", 0)
    cost = data.get("cost_basis", 0)
    clt = data.get("clt_price", 0)
    desc = data.get("desc", "")

    lines.append("")
    lines.append(f"  +=== VMQ+ SIMULATION: {name} ===+")
    lines.append(f"  |  {desc}")
    lines.append(f"  +{'=' * 48}+")
    lines.append("")

    # [S9.2.3] Module 1 -- Momentum
    m_hist = momentum_from_prices(prices)
    m_day = momentum_intraday(cp, op)
    mom_strength = ("strong" if abs(m_hist) > MOM_HIGH else
                    "moderate" if abs(m_hist) > MOM_MED else "weak")
    lines.append(f"  1. MOMENTUM")
    lines.append(f"     Historical: {m_hist:+.6f}  ({mom_strength})")
    lines.append(f"     Intraday:   {m_day:+.4f}")
    lines.append(f"     Price D:    {cp - prices[0]:+.2f} "
                 f"({(cp - prices[0]) / prices[0] * 100:+.2f}%)")
    lines.append(f"     {sep}")

    # [S9.2.4] Module 2 -- Trend
    trend = trend_from_candles(candles)
    trend_arrow = ("^" if trend["bias"] == "bullish" else
                   "v" if trend["bias"] == "bearish" else ">")
    lines.append(f"  2. TREND")
    lines.append(f"     Bias: {trend['bias'].upper()} {trend_arrow}")
    lines.append(f"     HH: {trend['hh']}  |  LL: {trend['ll']}")
    lines.append(f"     {sep}")

    # [S9.2.5] Module 3 -- Volatility
    vol = volatility_state(prices)
    atr = atr_from_candles(candles)
    vol_icon = ("!" if vol["state"] == "expanding" else
                "=" if vol["state"] == "compressing" else ".")
    lines.append(f"  3. VOLATILITY")
    lines.append(f"     State: {vol['state'].upper()} {vol_icon}")
    lines.append(f"     CV:    {vol['cv']:.6f}")
    lines.append(f"     ATR:   ${atr:.4f}  ({atr / cp * 100:.2f}% of price)")
    lines.append(f"     {sep}")

    # [S9.2.6] Module 4 -- Exhaustion
    exh = exhaustion_zscore(prices)
    exh_icon = "EXHAUSTED" if exh["exhausted"] else "CLEAN"
    lines.append(f"  4. EXHAUSTION")
    lines.append(f"     Status: {exh_icon}")
    lines.append(f"     Z: {exh['z_score']:+.4f}  "
                 f"(threshold: +/- {EXHAUSTION_Z_THRESHOLD})")
    lines.append(f"     {sep}")

    # [S9.2.7] Module 5 -- Volume Signal
    vol_sig = volume_compare(candles, avg_vol)
    lines.append(f"  5. VOLUME")
    lines.append(f"     Signal: {vol_sig.upper()}")
    lines.append(f"     Avg Vol: {avg_vol:,}")
    lines.append(f"     {sep}")

    # [S9.2.8] Module 6 -- UPSS Taxonomy
    upss = upss_generate(
        m_hist, trend["bias"], vol["state"], vol["cv"],
        exh["exhausted"], False, False
    )
    signal_str = ", ".join([f"{s['sym']}:{s['dir']}:{s['conf']:.2f}"
                            for s in upss]) if upss else "(none)"
    lines.append(f"  6. UPSS SIGNALS")
    lines.append(f"     Active: {signal_str}")
    lines.append(f"     {sep}")

    # [S9.2.9] Module 7 -- GBM Projections
    gbms = gbm_multi_horizon(cp, m_hist)
    for g in gbms:
        lines.append(f"  7. GBM ({g['horizon_label']})")
        lines.append(f"     Expected: ${g['expected']:.2f}")
        lines.append(f"     Range:    ${g['p5']:.2f} - ${g['p95']:.2f}")
        lines.append(f"     Median:   ${g['median']:.2f}")
        lines.append(f"     {sep}")

    # [S9.2.10] Module 8 -- Chain Detection
    chin = chains_detect(upss, cp, data["strike"], data["cost_basis"],
                          data["clt_price"], False)
    if chin:
        for c in chin:
            lines.append(f"  8. CHAIN: {c['id']}")
            lines.append(f"     Confidence: {c['confidence']:.2f}")
            lines.append(f"     Signals: {', '.join(c['signals'])}")
    else:
        lines.append(f"  8. CHAINS")
        lines.append(f"     (none active)")

    return lines


# [S9.3] Main entry point -- run from CLI ------------------------------------

def run_tests(symbols: Optional[List[str]] = None) -> None:
    """
    [S9.3.1] Run simulation for specified test cases, or all if none given.
    Input:  symbols=Optional[List[str]] -- list of TEST_DATA keys
    Output: prints to stdout, no return
    """
    if symbols:
        cases = {k: v for k, v in TEST_DATA.items() if k in symbols}
    else:
        cases = TEST_DATA

    if not cases:
        print(f"No matching test cases. Available: {', '.join(TEST_DATA.keys())}")
        return

    for name, data in cases.items():
        lines = run_simulation(name, data)
        for line in lines:
            print(line)
        print("")
        print("=" * 54)
        print("")


def quick_test() -> None:
    """
    [S9.3.2] Quick smoke test -- runs only BULL_RUN and BEAR_SLIDE.
    """
    run_tests(["BULL_RUN", "BEAR_SLIDE"])


if __name__ == "__main__":
    # [S9.4] CLI entry point
    args = sys.argv[1:]
    if "--quick" in args:
        quick_test()
    elif any(a.startswith("--symbol=") for a in args):
        sym = [a.split("=", 1)[1] for a in args if a.startswith("--symbol=")]
        run_tests(sym)
    elif args and args[0].startswith("--"):
        pass
    elif args:
        # Treat lone non-flag arg as symbol name
        sym = [a.upper() for a in args if a.upper() in TEST_DATA]
        if sym:
            run_tests(sym)
        else:
            print(f"Unknown symbol: {args[0]}")
            print(f"Available: {', '.join(TEST_DATA.keys())}")
    else:
        run_tests()

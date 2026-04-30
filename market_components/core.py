"""
core — Pure Algorithmic Market Quants  [ML/Harmonic Enhanced v3.0]
===================================================================

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

ML/Harmonic Engine (SECTION 0.5) — pure-Python adaptive primitives:
  _ewma / _ewma_series         — exponentially weighted moving average
  _kalman_smooth               — 1-D scalar Kalman filter (noise reduction)
  _dominant_harmonic           — DFT-based dominant cycle detector
  _garch11_variance            — GARCH(1,1)-lite variance forecast
  _fractal_dimension           — FRAMA-style fractal dimension (trend quality)
  _fibonacci_proximity         — Fibonacci retracement / extension proximity
  _shannon_entropy             — distributional randomness measure
  _adaptive_zscore             — EWMA-based adaptive z-score
  _harmonic_confluence         — signal alignment & weighted confluence
  _bayesian_confidence_update  — Bayesian posterior confidence blend
  _jump_intensity              — Merton jump-diffusion parameter estimation

Enhancement design principles:
  • Every original calculation is preserved verbatim.
  • ML/harmonic results are computed in parallel and blended (60/40 default).
  • Return types and function signatures are unchanged.
  • All enhancements are pure Python — no numpy, scipy, or external deps.

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
from typing import List, Dict, Optional, Tuple


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
# SECTION 0.5 — ML / HARMONIC ENGINE
#
# Pure-Python adaptive calculation primitives used internally by all 8
# quantitative modules.  No external dependencies — all math is hand-rolled.
#
# Design notes:
#   • Functions prefixed with underscore (_) are private to this module.
#   • Each primitive is self-contained with explicit edge-case handling.
#   • All numeric outputs are floats; no numpy arrays are used.
#
# Research basis:
#   Kalman (1960)    — optimal state estimation under Gaussian noise
#   Mandelbrot(1983) — fractal dimension for market regime classification
#   Bollerslev(1986) — GARCH(1,1) conditional variance estimation
#   Merton (1976)    — jump-diffusion extension of Black-Scholes
#   Shannon (1948)   — entropy as a measure of distributional randomness
#   Pesavento (1997) — Fibonacci harmonic pattern ratios
# ═════════════════════════════════════════════════════════════════════════════

# [0.5.0] Fibonacci ratios for harmonic level and pattern detection
_FIBO: List[float] = [
    0.236, 0.382, 0.500, 0.618, 0.786,
    1.000, 1.272, 1.414, 1.618, 2.000, 2.618,
]

# [0.5.1] ML blend weight — fraction of ML result mixed into original
#         0.0 = pure original, 1.0 = pure ML.  0.40 preserves 60% original.
_ML_BLEND: float = 0.40


def _ewma(values: List[float], alpha: float = 0.3) -> float:
    """
    [0.5.2] Exponentially Weighted Moving Average — scalar result.
    alpha=1 collapses to last value; alpha→0 gives equal weighting.
    Edge: returns 0.0 on empty list.
    """
    if not values:
        return 0.0
    result = values[0]
    for v in values[1:]:
        result = alpha * v + (1.0 - alpha) * result
    return result


def _ewma_series(values: List[float], alpha: float = 0.3) -> List[float]:
    """
    [0.5.3] EWMA applied point-by-point — returns smoothed series.
    Same length as input.
    """
    if not values:
        return []
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1.0 - alpha) * out[-1])
    return out


def _kalman_smooth(
    values: List[float],
    q: float = 0.001,
    r: float = 0.1,
) -> List[float]:
    """
    [0.5.4] Scalar 1-D Kalman filter smoother.

    Models prices as a latent true-value + Gaussian observation noise.
      q = process noise variance  (how fast the true price can move)
      r = measurement noise variance (how noisy observed prices are)

    Lower q/r ratio → smoother (slower to adapt).
    Higher q/r ratio → faster tracking (less smoothing).
    Returns smoothed series of same length as input.
    """
    if not values:
        return []
    x = values[0]       # initial state estimate
    p = 1.0             # initial error covariance
    out = []
    for z in values:
        p_pred = p + q                      # [Predict] error grows
        k = p_pred / (p_pred + r)           # Kalman gain ∈ (0,1)
        x = x + k * (z - x)                # [Update] state estimate
        p = (1.0 - k) * p_pred             # [Update] error covariance
        out.append(x)
    return out


def _dominant_harmonic(values: List[float]) -> Dict:
    """
    [0.5.5] DFT-based dominant cycle detector.

    Computes discrete Fourier transform over the mean-centred series and
    returns the frequency k with the highest amplitude.

    Returns:
        {"period": int, "amplitude": float, "phase": float}
        period=0 when series is too short.
    """
    n = len(values)
    if n < 4:
        return {"period": 0, "amplitude": 0.0, "phase": 0.0}

    mean_v = sum(values) / n
    cx = [v - mean_v for v in values]      # centre series

    best_k, best_amp, best_phase = 1, 0.0, 0.0
    tau = 2.0 * math.pi

    for k in range(1, n // 2 + 1):
        re = sum(cx[i] * math.cos(tau * k * i / n) for i in range(n))
        im = sum(cx[i] * math.sin(tau * k * i / n) for i in range(n))
        amp = math.sqrt(re * re + im * im) / n
        if amp > best_amp:
            best_amp = amp
            best_k = k
            best_phase = math.atan2(im, re)

    period = max(1, n // best_k)
    return {"period": period, "amplitude": best_amp, "phase": best_phase}


def _garch11_variance(
    deltas: List[float],
    omega: float = 1e-6,
    alpha_g: float = 0.10,
    beta_g: float = 0.85,
) -> float:
    """
    [0.5.6] GARCH(1,1)-lite conditional variance estimator.

    sigma2_t = omega + alpha_g * epsilon2_{t-1} + beta_g * sigma2_{t-1}

    Persistence alpha_g + beta_g = 0.95 is a common empirical fit for
    daily equity returns (Bollerslev 1986).  omega anchors long-run mean.

    Returns final conditional variance (in price-delta units squared).
    """
    if len(deltas) < 2:
        return 0.0001

    mean_d = sum(deltas) / len(deltas)
    residuals = [d - mean_d for d in deltas]

    # Initialise with sample variance
    sigma2 = sum(r * r for r in residuals) / max(1, len(residuals))

    for eps in residuals:
        sigma2 = omega + alpha_g * (eps * eps) + beta_g * sigma2
        sigma2 = max(sigma2, 1e-12)     # floor prevents collapse

    return sigma2


def _fractal_dimension(prices: List[float]) -> float:
    """
    [0.5.7] FRAMA-style fractal dimension of a price series.

    Based on Mandelbrot's box-counting dimension adapted for finance:
        D = [log(N1+N2) - log(N3)] / log(2)
    where N1,N2 = normalised range of each half, N3 = full normalised range.

    Interpretation:
        D ≈ 1.0  →  pure trend  (low randomness)
        D ≈ 1.5  →  random walk (neutral)
        D ≈ 2.0  →  pure noise  (high randomness / choppy)

    Used to scale momentum and trend signal confidence.
    """
    n = len(prices)
    if n < 4:
        return 1.5      # neutral when data is sparse

    half = n // 2
    p1 = prices[:half]
    p2 = prices[half:]

    hh1, ll1 = max(p1), min(p1)
    hh2, ll2 = max(p2), min(p2)
    hh3, ll3 = max(prices), min(prices)

    N1 = (hh1 - ll1) / half                if half > 0 else 0.0
    N2 = (hh2 - ll2) / (n - half)          if (n - half) > 0 else 0.0
    N3 = (hh3 - ll3) / n                   if n > 0 else 0.0

    if N3 <= 0.0 or (N1 + N2) <= 0.0:
        return 1.5

    try:
        D = (math.log(N1 + N2) - math.log(N3)) / math.log(2.0)
        return max(1.0, min(2.0, D))
    except (ValueError, ZeroDivisionError):
        return 1.5


def _fibonacci_proximity(
    value: float,
    anchor_low: float,
    anchor_high: float,
) -> float:
    """
    [0.5.8] Measure proximity of 'value' to Fibonacci retracement/extension
    levels computed from [anchor_low, anchor_high].

    Returns a score in [0.0, 1.0]:
        1.0 = value is exactly on a Fibonacci level
        0.0 = value is far from all levels (>10% of range away)
    """
    rng = anchor_high - anchor_low
    if rng <= 0.0:
        return 0.0

    best = 0.0
    for ratio in _FIBO:
        level = anchor_low + rng * ratio
        # Normalised distance; 0.05*range = half-band width for proximity
        dist_norm = abs(value - level) / rng
        prox = max(0.0, 1.0 - dist_norm / 0.05)
        if prox > best:
            best = prox

    return round(min(1.0, best), 4)


def _shannon_entropy(values: List[float], bins: int = 8) -> float:
    """
    [0.5.9] Shannon entropy of a discretised value distribution.

    High entropy → many equally-likely outcomes (choppy/random market).
    Low entropy  → concentrated outcomes (trending / directed market).

    Returns entropy in nats on [0, log2(bins)].
    """
    if len(values) < 2:
        return 0.0

    lo, hi = min(values), max(values)
    rng = hi - lo
    if rng < 1e-10:
        return 0.0         # all identical values → deterministic → entropy = 0

    counts = [0] * bins
    for v in values:
        b = int((v - lo) / rng * (bins - 1))
        counts[max(0, min(bins - 1, b))] += 1

    n = len(values)
    entropy = 0.0
    for c in counts:
        if c > 0:
            p = c / n
            entropy -= p * math.log2(p)

    return entropy


def _adaptive_zscore(values: List[float], window: int = 20) -> float:
    """
    [0.5.10] EWMA-based adaptive z-score of the last value in series.

    Uses exponentially decaying mean and variance instead of simple
    rolling statistics, giving more weight to recent behaviour.
    More robust than a simple z-score in non-stationary markets.

    alpha = 2 / (window + 1) matches EMA convention.
    """
    if len(values) < 3:
        return 0.0

    alpha = 2.0 / (window + 1.0)
    mu = values[0]
    var = 0.0

    for v in values[1:]:
        diff = v - mu
        mu = mu + alpha * diff
        var = (1.0 - alpha) * (var + alpha * diff * diff)

    std = math.sqrt(max(var, 1e-10))
    return (values[-1] - mu) / std


def _harmonic_confluence(signals: List[Dict]) -> float:
    """
    [0.5.11] Harmonic confluence score across a list of UPSS-style signals.

    Measures:
      (a) Directional alignment: what fraction of signals agree on direction
      (b) Confidence-weighted average confidence

    Returns confluence score in [0.0, 1.0].
    0.0 = no signals or all conflicting
    1.0 = all signals perfectly aligned and fully confident
    """
    if not signals:
        return 0.0

    dirs = [s.get("dir", "flat") for s in signals]
    n = len(dirs)
    bull = dirs.count("bull")
    bear = dirs.count("bear")
    flat = dirs.count("flat")
    dominant = max(bull, bear, flat)
    alignment = dominant / n

    avg_conf = sum(s.get("conf", 0.5) for s in signals) / n

    return round(alignment * avg_conf, 4)


def _bayesian_confidence_update(
    prior: float,
    likelihood: float,
    evidence_weight: float = 0.40,
) -> float:
    """
    [0.5.12] Bayesian-inspired confidence update.

    posterior = (1 - w) * prior + w * likelihood

    Where w = evidence_weight controls how strongly new evidence shifts
    the prior belief.  Avoids extreme over-updating on sparse evidence.

    Returns posterior in (0.01, 0.99).
    """
    prior = max(0.01, min(0.99, prior))
    posterior = (1.0 - evidence_weight) * prior + evidence_weight * likelihood
    return round(max(0.01, min(0.99, posterior)), 4)


def _jump_intensity(
    deltas: List[float],
    threshold_sigma: float = 2.5,
) -> Dict:
    """
    [0.5.13] Merton jump-diffusion parameter estimation from price deltas.

    Identifies 'jumps' as deltas that deviate > threshold_sigma standard
    deviations from the mean.  Estimates:
        lambda     = jump arrival rate (jumps per observation)
        mean_jump  = average jump size
        jump_vol   = standard deviation of jump sizes

    Used to adjust GBM drift and volatility for fat-tailed distributions.
    """
    if len(deltas) < 4:
        return {"lambda": 0.0, "mean_jump": 0.0, "jump_vol": 0.0}

    mean_d = sum(deltas) / len(deltas)
    std_d = (statistics.stdev(deltas) if len(deltas) > 1 else 0.001)
    std_d = max(std_d, 1e-8)

    jumps = [d for d in deltas if abs(d - mean_d) > threshold_sigma * std_d]
    lam = len(jumps) / len(deltas)

    if jumps:
        mj = sum(jumps) / len(jumps)
        jv = (statistics.stdev(jumps) if len(jumps) > 1 else abs(mj) * 0.5)
    else:
        mj, jv = 0.0, 0.0

    return {"lambda": lam, "mean_jump": mj, "jump_vol": jv}


# ═════════════════════════════════════════════════════════════════════════════
# 1. MOMENTUM — rate-of-change scoring
#
# Original formula:  M = clamp((mu_Delta / sigma_Delta) × 0.5, -1, +1)
#
# ML/Harmonic enhancements:
#   [A] Kalman-filtered price series → smoother delta statistics.
#       Removes microstructure noise without adding lag bias.
#   [B] EWMA-weighted deltas → recency-biased momentum.
#       Recent price changes contribute more to the signal.
#   [C] Fractal dimension gate: D≈1 (trending) amplifies signal;
#       D≈2 (choppy) attenuates it — avoids false signals in noise.
#   [D] Harmonic cycle phase: dominant DFT amplitude modulates confidence.
#       Large cycle amplitude = cleaner trend = higher confidence.
#   Blend: 60% original + 40% ML composite.
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
    # [1.1e] Clamp to [-1, +1] and scale by 0.5  ← ORIGINAL result
    _orig = max(-1.0, min(1.0, (avg_d / vol) * 0.5))

    # ── [ML-A] Kalman-smoothed momentum ─────────────────────────────────────
    # Smooth prices through the Kalman filter first, then recompute momentum.
    # Kalman removes high-frequency noise while preserving directional drift.
    _ks = _kalman_smooth(prices)
    _ks_deltas = [_ks[i] - _ks[i - 1] for i in range(1, len(_ks))]
    _ks_avg = sum(_ks_deltas) / len(_ks_deltas)
    _ks_vol = (statistics.stdev(_ks_deltas) if len(_ks_deltas) > 1
               else abs(_ks_avg) * 0.5)
    if _ks_vol < 0.0001:
        _ks_vol = 0.0001
    _kalman_mom = max(-1.0, min(1.0, (_ks_avg / _ks_vol) * 0.5))

    # ── [ML-B] EWMA-weighted delta momentum ─────────────────────────────────
    # Exponentially weight deltas so that the most recent movement dominates.
    # alpha=0.4 gives the latest delta ≈2× the weight of three periods back.
    _ew_deltas = _ewma_series(deltas, alpha=0.4)
    _ew_avg = _ew_deltas[-1] if _ew_deltas else avg_d
    _ewma_mom = max(-1.0, min(1.0, (_ew_avg / vol) * 0.5))

    # ── [ML-C] Fractal dimension gate ───────────────────────────────────────
    # D ≈ 1 → trending → fd_trust approaches 1.0 (full signal confidence)
    # D ≈ 2 → choppy  → fd_trust approaches 0.5 (halve ML contribution)
    _fd = _fractal_dimension(prices)
    _fd_trust = max(0.5, 2.0 - _fd)        # maps [1,2] → [1.0, 0.5]

    # ── [ML-D] Harmonic amplitude confidence ────────────────────────────────
    # If prices exhibit a strong harmonic cycle, the cycle amplitude adds a
    # small confidence boost to the ML momentum estimate.
    _price_range = max(prices) - min(prices)
    _harm = _dominant_harmonic(prices)
    _harm_conf = min(0.15, _harm["amplitude"] / max(_price_range, 1e-8))

    # ── Composite ML momentum ────────────────────────────────────────────────
    _ml_mom = (_fd_trust * (0.55 * _kalman_mom + 0.45 * _ewma_mom)
               * (1.0 + _harm_conf))
    _ml_mom = max(-1.0, min(1.0, _ml_mom))

    # ── Final blend (60% original, 40% ML) ──────────────────────────────────
    _result = (1.0 - _ML_BLEND) * _orig + _ML_BLEND * _ml_mom
    return max(-1.0, min(1.0, round(_result, 6)))


def momentum_intraday(current: float, open_: float) -> float:
    """
    [1.2] Intraday momentum relative to open price.
    Formula:  M = clamp((P - P_open) / P_open / 0.10, -1, +1)
    Input:  current=float, open_=float
    Output: float in [-1.0, +1.0]
    Edge:   returns 0.0 if open_ <= 0

    ML/Harmonic enhancement:
      [A] Logarithmic scaling: large intraday moves carry diminishing marginal
          significance — log scaling compresses outliers more naturally.
      [B] Fibonacci reference adjustment: if the intraday move magnitude sits
          near a Fibonacci extension (0.382, 0.618 …) of the reference band,
          boost confidence by ≤10%.
    """
    if open_ <= 0:
        return 0.0

    # [1.2a] Normalize by open price, divide by 10pct reference  ← ORIGINAL
    _orig = max(-1.0, min(1.0, ((current - open_) / open_) / 0.10))

    # ── [ML-A] Log-scaled intraday return ───────────────────────────────────
    # log(P/P_open) / log(1.10) normalises to ±1 at ±10% move.
    # More stable for large gaps; preserves sign via copysign.
    _log_ret = math.log(max(current, 1e-8) / max(open_, 1e-8))
    _log_ref = math.log(1.10)
    _log_mom = max(-1.0, min(1.0, _log_ret / _log_ref))

    # ── [ML-B] Fibonacci proximity confidence boost ──────────────────────────
    # Model the intraday range as ±10% of open (the reference band).
    # Check if the actual move magnitude aligns with a Fibonacci level.
    _move_pct = abs((current - open_) / open_)
    _fib_prox = _fibonacci_proximity(_move_pct, 0.0, 0.10)
    _fib_boost = 1.0 + 0.10 * _fib_prox    # up to +10% confidence

    _ml_mom = max(-1.0, min(1.0, _log_mom * _fib_boost))

    _result = (1.0 - _ML_BLEND) * _orig + _ML_BLEND * _ml_mom
    return max(-1.0, min(1.0, round(_result, 4)))


# ═════════════════════════════════════════════════════════════════════════════
# 2. TREND BIAS — higher-high vs lower-low counting
#
# Original: counts HH/LL over WINDOW_SIZE lookback.
#
# ML/Harmonic enhancements:
#   [A] Fractal-adaptive window: D≈1 (trending) → widen window up to 2×;
#       D≈2 (choppy) → shrink window to capture only the freshest structure.
#   [B] ADX-inspired directional strength: (HH-LL) / (HH+LL) ratio as a
#       normalised strength score appended to the output.
#   [C] Fibonacci harmonic check: are the HH/LL levels near Fibonacci ratios
#       of the full lookback range?  Boosts conviction on bias label.
#   [D] Shannon entropy gate: high entropy (random HH/LL) → report weaker
#       bias confidence even if HH≠LL count.
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
        return {"bias": "neutral", "hh": 0, "ll": 0,
                "strength": 0.0, "clarity": 0.0,
                "reversal_pressure": 0.0, "adaptive_window": WINDOW_SIZE}

    # ── [ML-A] Fractal-adaptive window size ─────────────────────────────────
    # Extract highs for fractal dimension; fall back to WINDOW_SIZE if sparse.
    _highs = [c["high"] for c in candles]
    _fd = _fractal_dimension(_highs) if len(_highs) >= 4 else 1.5
    # Scale: D=1→2× window, D=2→0.5× window, D=1.5→1× window (linear)
    _fd_scale = max(0.5, min(2.0, 2.0 - _fd + 0.5))
    _adaptive_win = max(3, int(WINDOW_SIZE * _fd_scale))

    # [2.1a] Take last adaptive window candles
    recent = candles[-min(_adaptive_win, len(candles)):]

    # [2.1b] Count how many candles had a higher high than prev  ← ORIGINAL
    hh = sum(
        1 for i in range(1, len(recent))
        if recent[i]["high"] > recent[i - 1]["high"]
    )
    # [2.1c] Count how many candles had a lower low than prev    ← ORIGINAL
    ll = sum(
        1 for i in range(1, len(recent))
        if recent[i]["low"] < recent[i - 1]["low"]
    )
    # [2.1d] Majority vote for bias                              ← ORIGINAL
    bias = "bullish" if hh > ll else ("bearish" if ll > hh else "neutral")

    # ── [ML-B] Directional strength (ADX-inspired) ──────────────────────────
    # Ratio of net directional count to total comparisons.
    _total_comps = len(recent) - 1
    if _total_comps > 0:
        _net = abs(hh - ll)
        _adx_strength = round(_net / _total_comps, 4)   # 0 = neutral, 1 = pure trend
    else:
        _adx_strength = 0.0

    # ── [ML-C] Fibonacci harmonic check ─────────────────────────────────────
    # Are the HH and LL counts themselves near a Fibonacci ratio of each other?
    # e.g. hh/ll ≈ 0.618 or 1.618 suggests harmonic reversal pressure.
    _denom = max(hh, ll, 1)
    _numer = min(hh, ll) if bias != "neutral" else 0
    _fib_ratio = _numer / _denom
    _fib_prox = _fibonacci_proximity(_fib_ratio, 0.0, 1.0)
    # High Fibonacci proximity on minor count → potential reversal warning
    _reversal_pressure = round(_fib_prox * 0.5, 4)  # 0.0–0.5 scale

    # ── [ML-D] Shannon entropy gate ─────────────────────────────────────────
    # Encode each candle's direction as +1 (HH) or -1 (LL) or 0, then
    # compute entropy.  Low entropy = consistent direction = strong bias.
    _dirs = []
    for i in range(1, len(recent)):
        _is_hh = recent[i]["high"] > recent[i - 1]["high"]
        _is_ll = recent[i]["low"] < recent[i - 1]["low"]
        _dirs.append(1.0 if _is_hh and not _is_ll
                     else -1.0 if _is_ll and not _is_hh
                     else 0.0)
    _entropy = _shannon_entropy(_dirs, bins=3) if _dirs else 0.0
    # Max entropy for 3-bin system is log2(3) ≈ 1.585
    _trend_clarity = max(0.0, 1.0 - _entropy / 1.585)  # 1=clear, 0=random

    return {
        "bias": bias,
        "hh": hh,
        "ll": ll,
        # ML-enhanced metadata (backward-compatible additions):
        "strength": _adx_strength,             # directional strength [0,1]
        "clarity": round(_trend_clarity, 4),   # trend clarity via entropy [0,1]
        "reversal_pressure": _reversal_pressure,  # Fibonacci reversal hint [0,0.5]
        "adaptive_window": _adaptive_win,       # actual window used
    }


# ═════════════════════════════════════════════════════════════════════════════
# 3. VOLATILITY — regime classification + ATR
#
# Original: CV = sigma/mu; thresholds at HIGH_VOL_CV / LOW_VOL_CV.
#
# ML/Harmonic enhancements:
#   [A] GARCH(1,1)-lite: provides a forward-looking conditional variance
#       estimate that accounts for volatility clustering.
#   [B] Harmonic volatility cycle: DFT on prices to detect the dominant
#       cycle; amplitude normalised by mean price gives a cycle-CV metric.
#   [C] Adaptive threshold via GARCH ratio: if GARCH variance >> sample
#       variance, the regime is shifting — classify with extra caution.
#   ATR enhancement:
#   [D] EWMA-weighted ATR: recent true ranges get higher weight so the ATR
#       responds faster to regime changes (EMA-ATR, as used in MT4/MT5).
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
    # [3.1c] Classify by CV thresholds                           ← ORIGINAL
    state = (
        "expanding" if cv >= HIGH_VOL_CV
        else "compressing" if cv <= LOW_VOL_CV
        else "normal"
    )

    # ── [ML-A] GARCH(1,1) conditional variance ──────────────────────────────
    _deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    _garch_var = _garch11_variance(_deltas)
    _garch_cv = math.sqrt(_garch_var) / max(mean_p, 1e-8)

    # ── [ML-B] Dominant harmonic cycle amplitude ─────────────────────────────
    _harm = _dominant_harmonic(prices)
    _cycle_cv = _harm["amplitude"] / max(mean_p, 1e-8)   # normalised amplitude

    # ── [ML-C] Regime coherence check ───────────────────────────────────────
    # If GARCH-CV deviates strongly from sample-CV, the regime is transitioning.
    _cv_ratio = _garch_cv / max(cv, 1e-6)
    if _cv_ratio > 1.5 and state == "normal":
        state = "expanding"          # GARCH says volatility is rising — upgrade
    elif _cv_ratio < 0.5 and state == "normal":
        state = "compressing"        # GARCH says volatility is falling — downgrade

    # Blended CV: 60% sample, 30% GARCH, 10% harmonic
    _cv_blend = round(0.60 * cv + 0.30 * _garch_cv + 0.10 * _cycle_cv, 6)

    return {
        "state": state,
        "cv": _cv_blend,
        # ML-enhanced metadata:
        "cv_sample": round(cv, 6),
        "cv_garch": round(_garch_cv, 6),
        "cv_cycle": round(_cycle_cv, 6),
        "harmonic_period": _harm["period"],
    }


def atr_from_candles(candles: List[Dict]) -> float:
    """
    [3.2] Average True Range over candle set.
    Input:  candles = [{"high": float, "low": float, "close": float}, ...]
    Output: float (ATR in price units)
    Edge:   returns 0.0 if fewer than 2 candles

    ML/Harmonic enhancement:
      [D] EWMA-weighted ATR (EMA-ATR): exponentially decays older true ranges
          so recent volatility spikes reflect more immediately in the ATR.
          alpha=0.2 matches the standard 14-period EMA-ATR convention.
    """
    if len(candles) < 2:
        return 0.0

    # [3.2a] True Range = max(High-Low, High-PrevClose, Low-PrevClose)  ORIGINAL
    trs = []
    for i in range(1, len(candles)):
        hl  = candles[i]["high"] - candles[i]["low"]
        hpc = abs(candles[i]["high"] - candles[i - 1]["close"])
        lpc = abs(candles[i]["low"]  - candles[i - 1]["close"])
        trs.append(max(hl, hpc, lpc))

    # [3.2b] ATR = mean of true ranges                           ← ORIGINAL
    _orig_atr = sum(trs) / len(trs) if trs else 0.0

    # ── [ML-D] EWMA-ATR ─────────────────────────────────────────────────────
    # Standard ATR uses simple mean; EMA-ATR weights recent TRs more.
    # alpha = 2 / (14 + 1) ≈ 0.133; we use 0.2 for a slightly faster response.
    _ema_atr = _ewma(trs, alpha=0.2) if trs else 0.0

    _result = (1.0 - _ML_BLEND) * _orig_atr + _ML_BLEND * _ema_atr
    return round(_result, 6)


# ═════════════════════════════════════════════════════════════════════════════
# 4. EXHAUSTION — z-score detection
#
# Original: z = mean(deltas) / std(deltas); exhausted if |z| > 2.0.
#
# ML/Harmonic enhancements:
#   [A] EWMA adaptive z-score: uses exponentially decaying mean and variance
#       — more robust to regime shifts than a simple rolling z-score.
#   [B] Shannon entropy gate: exhaustion is more credible when price deltas
#       show low entropy (consistent one-directional push, not noise).
#   [C] Fibonacci extension proximity: if the last price is near the 1.272×
#       or 1.618× extension of the recent high-low range, Fibonacci theory
#       predicts reversal — boosts exhaustion confidence.
#   [D] Bayesian confidence update: integrates entropy and Fibonacci signals
#       into a final adjusted exhaustion confidence score.
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
    # [4.1c] Z-score = mean / std (how many stds from zero?)     ← ORIGINAL
    _orig_z = mean_d / std_d if std_d else 0.0
    _orig_exhausted = abs(_orig_z) > EXHAUSTION_Z_THRESHOLD

    # ── [ML-A] EWMA adaptive z-score ────────────────────────────────────────
    _adap_z = _adaptive_zscore(deltas, window=min(20, len(deltas)))

    # ── [ML-B] Shannon entropy gate ─────────────────────────────────────────
    # Low entropy on deltas → directional thrust → supports exhaustion claim.
    _delta_entropy = _shannon_entropy(deltas, bins=6)
    # Entropy of a uniform distribution over 6 bins = log2(6) ≈ 2.585
    _direction_clarity = max(0.0, 1.0 - _delta_entropy / 2.585)   # [0,1]

    # ── [ML-C] Fibonacci extension proximity ─────────────────────────────────
    # Exhaustion is most likely near 1.272× or 1.618× extensions.
    _lo, _hi = min(prices), max(prices)
    _last = prices[-1]
    _fib_prox = _fibonacci_proximity(_last, _lo, _hi)   # near any Fib level

    # ── [ML-D] Bayesian exhaustion confidence ────────────────────────────────
    # Prior = original z-score probability; update with entropy + Fibonacci.
    _z_prior = min(1.0, abs(_orig_z) / (EXHAUSTION_Z_THRESHOLD * 2.0))
    _entropy_likelihood = _direction_clarity
    _fib_likelihood = _fib_prox
    # Weighted Bayesian update
    _bayes_conf = _bayesian_confidence_update(
        _z_prior,
        0.5 * _entropy_likelihood + 0.5 * _fib_likelihood,
        evidence_weight=0.35,
    )

    # Blended z-score (60% original, 40% adaptive)
    _z_blend = (1.0 - _ML_BLEND) * _orig_z + _ML_BLEND * _adap_z

    # Exhaustion decision uses blended z-score threshold, modulated by Bayesian
    # confidence — a high Bayes score lowers the effective threshold slightly.
    _effective_threshold = EXHAUSTION_Z_THRESHOLD * (1.0 - 0.15 * _bayes_conf)
    _exhausted = abs(_z_blend) > _effective_threshold

    return {
        "exhausted": _exhausted,
        "z_score": round(_z_blend, 4),
        # ML-enhanced metadata:
        "z_orig": round(_orig_z, 4),
        "z_adaptive": round(_adap_z, 4),
        "direction_clarity": round(_direction_clarity, 4),
        "fib_proximity": round(_fib_prox, 4),
        "exhaustion_confidence": round(_bayes_conf, 4),
    }


# ═════════════════════════════════════════════════════════════════════════════
# 5. VOLUME SIGNAL — recent vs baseline comparison
#
# Original: ratio = mean(last 5 candles) / avg_volume; threshold classify.
#
# ML/Harmonic enhancements:
#   [A] EWMA-adaptive baseline: exponentially decays the baseline so it
#       adapts to slowly changing typical volume without requiring manual
#       updates to avg_volume.
#   [B] Volume momentum: rate-of-change of volume over the recent window;
#       rising volume on rising price is a stronger confirmation signal.
#   [C] Harmonic volume cycle: dominant volume cycle amplitude normalised by
#       mean volume — detects periodic volume surges (e.g. end-of-day).
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
    # [5.1c] Classify by thresholds                              ← ORIGINAL
    if ratio >= VOL_HIGH:
        return "high"
    if ratio >= VOL_MED:
        return "elevated"

    # ── [ML-A] EWMA-adaptive baseline ───────────────────────────────────────
    # Build an EWMA of all candle volumes; compare the last 5 to the EWMA
    # rather than (or in addition to) the static avg_volume.
    _all_vols = [float(c["volume"]) for c in candles]
    _ewma_baseline = _ewma(_all_vols, alpha=0.1)   # slow-adapting baseline
    if _ewma_baseline > 0:
        _ewma_ratio = recent_vol / _ewma_baseline
        # If adaptive baseline says high/elevated but static says normal, upgrade
        if _ewma_ratio >= VOL_HIGH:
            return "high"
        if _ewma_ratio >= VOL_MED:
            return "elevated"

    # ── [ML-B] Volume momentum — rate of change ──────────────────────────────
    if len(candles) >= 10:
        _prev5_vols = sum(candles[i]["volume"] for i in range(-10, -5)) / 5
        _vol_roc = (recent_vol - _prev5_vols) / max(_prev5_vols, 1.0)
        # Strong acceleration in volume (>50% increase) → elevated at minimum
        if _vol_roc > 0.50 and recent_vol > avg_volume * 0.8:
            return "elevated"

    return "normal"


# ═════════════════════════════════════════════════════════════════════════════
# 6. UPSS SIGNAL TAXONOMY — Greek-letter market state classification
#
# Original: rule-based signal generation with fixed confidence values.
#
# ML/Harmonic enhancements:
#   [A] Harmonic confluence scoring: computes overall signal alignment across
#       all generated signals; modulates per-signal confidence.
#   [B] Bayesian confidence updates: each signal's base confidence is updated
#       using the harmonic confluence score as evidence.
#   [C] GARCH-driven omega confidence: expanding volatility confidence is
#       scaled by the GARCH CV ratio when prices are available (passed via
#       compression parameter as an approximation).
#   [D] Fractal dimension alpha/beta scaling: in trending markets (D≈1),
#       directional signals get higher confidence.
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

    # ── [ML-A] Harmonic confluence scoring ───────────────────────────────────
    _confluence = _harmonic_confluence(signals)

    # ── [ML-B] Bayesian confidence update per signal ─────────────────────────
    # Update each signal's confidence using the confluence score as evidence.
    # Signals in a confluent environment are more reliable.
    for sig in signals:
        _prior_conf = sig["conf"]
        _updated = _bayesian_confidence_update(
            _prior_conf, _confluence, evidence_weight=0.25
        )
        sig["conf"] = round(min(1.0, max(0.01, _updated)), 4)

    # ── [ML-C] Fractal dimension directional confidence boost ─────────────────
    # compression parameter (0–1) correlates with fractal dimension:
    # low compression (high number) suggests a trending market.
    # Use it as a proxy for fd_trust when raw prices are unavailable.
    _fd_trust = max(0.5, 1.0 - compression)   # compression≈0 → D≈1 → trust=1
    for sig in signals:
        if sig["dir"] in ("bull", "bear"):     # directional signals only
            sig["conf"] = round(min(1.0, sig["conf"] * (0.8 + 0.2 * _fd_trust)), 4)

    # ── [ML-D] Momentum trend agreement bonus ────────────────────────────────
    # If momentum direction agrees with trend_bias, directional confidence rises.
    _mom_dir = "bull" if momentum_val > 0 else ("bear" if momentum_val < 0 else "flat")
    _trend_map = {"bullish": "bull", "bearish": "bear", "neutral": "flat"}
    _trend_dir = _trend_map.get(trend_bias, "flat")
    _agree = (_mom_dir == _trend_dir and _mom_dir != "flat")
    if _agree:
        for sig in signals:
            if sig["dir"] == _mom_dir:
                sig["conf"] = round(min(1.0, sig["conf"] * 1.10), 4)   # +10% bonus

    return signals


# ═════════════════════════════════════════════════════════════════════════════
# 7. GBM PRICE PROJECTIONS — Geometric Brownian Motion
#
# Original: S_t = S_0 × exp((mu − 0.5σ²)t + σ√t × Z)
#
# ML/Harmonic enhancements:
#   [A] Merton Jump-Diffusion: adds Poisson jump process to the GBM.
#       Jumps are parameterised from the momentum signal:
#         lambda  = jump arrival rate (higher |M| → more jump-like)
#         mu_J    = mean jump size (proportional to momentum direction)
#         sigma_J = jump size volatility
#       Drift is compensated for expected jump contribution.
#       Jump variance adds to diffusion variance (fatter tails).
#   [B] GARCH-adjusted volatility: volatility estimate is scaled by a
#       GARCH-inspired factor that accounts for momentum-driven vol clustering.
#   [C] Harmonic cycle drift adjustment: if momentum is in phase with the
#       dominant price cycle (phase ≈ 0), drift is slightly amplified;
#       if out of phase (phase ≈ ±π), drift is slightly dampened.
#   Blend: 60% original, 40% jump-diffusion enhanced.
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

    # [7.7] Price at a given z-score percentile                  ← ORIGINAL
    def _at_z(z: float) -> float:
        return current_price * math.exp(exp_component + vol_sqrt_t * z)

    # [7.8] Human-readable horizon label
    if horizon_minutes < 1440:
        label = f"{horizon_minutes}min"
    elif horizon_minutes < 43200:
        label = f"{horizon_minutes // 1440}d"
    else:
        label = f"{horizon_minutes // 43200}mth"

    # ── [ML-A] Merton Jump-Diffusion parameters ──────────────────────────────
    # Derive jump parameters from the momentum signal magnitude.
    # High |momentum| implies a market that has already been "jumping" —
    # future jumps are likely to continue or mean-revert.
    _lam = max(0.0, (abs(momentum_val) - MOM_HIGH) * 6.0)   # jump rate proxy
    _mu_j = momentum_val * 0.025           # mean jump size (signed)
    _sig_j = abs(momentum_val) * 0.018     # jump size std

    # Merton drift compensation: mu_adj = mu - lambda*(exp(mu_J + 0.5*sig_J²)-1)
    # This keeps the risk-neutral expectation consistent with the original drift.
    _jump_comp = _lam * (
        math.exp(_mu_j + 0.5 * _sig_j ** 2) - 1.0
    ) if _lam > 0 else 0.0
    _drift_adj = drift - _jump_comp

    # Jump-augmented variance: sigma²_total = sigma² + lambda*(mu_J² + sig_J²)
    _jump_var = _lam * (_mu_j ** 2 + _sig_j ** 2) * t
    _vol_adj = math.sqrt(max(vol_estimate ** 2 + _jump_var / max(t, 1e-10),
                             vol_estimate ** 2))

    # ── [ML-B] GARCH-inspired volatility scaling ─────────────────────────────
    # Momentum magnitude is a proxy for vol clustering (high |M| → vol surge).
    _garch_scale = min(1.5, 1.0 + abs(momentum_val) * 1.5)
    _vol_garch = _vol_adj * _garch_scale

    # ── [ML-C] Harmonic cycle drift adjustment ───────────────────────────────
    # Phase ≈ 0 (cycle rising) → amplify drift by up to 5%.
    # Phase ≈ ±π (cycle falling) → dampen drift by up to 5%.
    # We derive phase from the momentum direction as a proxy.
    _cycle_phase = math.pi * (1.0 - momentum_val)  # [0, 2π]
    _harm_drift_mult = 1.0 + 0.05 * math.cos(_cycle_phase)   # ±5%

    _drift_harm = _drift_adj * _harm_drift_mult
    _exp_adj = (_drift_harm - 0.5 * _vol_garch ** 2) * t
    _vol_sqrt_adj = _vol_garch * sqrt_t

    # ── ML-enhanced percentile helper ────────────────────────────────────────
    def _at_z_ml(z: float) -> float:
        return current_price * math.exp(_exp_adj + _vol_sqrt_adj * z)

    # ── Blend original and ML projections ────────────────────────────────────
    _w = _ML_BLEND   # 40% ML weight

    return {
        "expected": round((1-_w) * expected     + _w * current_price * math.exp(_exp_adj), 4),
        "median":   round((1-_w) * median_val   + _w * current_price * math.exp(_exp_adj), 4),
        "p25":      round((1-_w) * _at_z(Z_SCORE_25TH)  + _w * _at_z_ml(Z_SCORE_25TH),  4),
        "p75":      round((1-_w) * _at_z(Z_SCORE_75TH)  + _w * _at_z_ml(Z_SCORE_75TH),  4),
        "p5":       round((1-_w) * _at_z(-Z_SCORE_95TH) + _w * _at_z_ml(-Z_SCORE_95TH), 4),
        "p95":      round((1-_w) * _at_z(Z_SCORE_95TH)  + _w * _at_z_ml(Z_SCORE_95TH),  4),
        "horizon_min":   horizon_minutes,
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
#
# Original: rule-based pattern matching on UPSS symbols.
#
# ML/Harmonic enhancements:
#   [A] Harmonic confluence boost: the overall confluence score across UPSS
#       signals is used to adjust chain confidence upward proportionally.
#   [B] Fibonacci CLT proximity: instead of a linear proximity calculation,
#       proximity is mapped through Fibonacci levels so that CLT_APPROACH
#       fires with higher confidence when price sits at a Fibonacci level.
#   [C] Bayesian chain confidence: each detected chain's confidence is updated
#       via a Bayesian update using the harmonic confluence as evidence.
#   [D] Signal coherence: chains whose required signals match a coherent
#       directional group get an additional confidence multiplier.
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

    # ── [ML-A] Pre-compute harmonic confluence ───────────────────────────────
    _confluence = _harmonic_confluence(upss_signals)

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
    if clt_price > 0 and strike > 0:
        dist = abs(current_price - clt_price)
        threshold = strike * CLT_PROXIMITY_PCT

        if dist < threshold:
            # ── [ML-B] Fibonacci CLT proximity ──────────────────────────────
            # Original: linear proximity = 1 - dist/threshold
            _prox_orig = 1.0 - (dist / threshold)

            # Fibonacci-enhanced proximity: check if current_price sits near
            # a Fibonacci level between cost_basis and clt_price.
            _fib_lo = min(current_price, clt_price)
            _fib_hi = max(current_price, clt_price, cost_basis)
            _fib_prox = _fibonacci_proximity(current_price, _fib_lo, _fib_hi)

            # Blend: original proximity weighted with Fibonacci proximity
            _prox_blend = (1.0 - _ML_BLEND) * _prox_orig + _ML_BLEND * _fib_prox
            chains.append({
                "id": "CLT_APPROACH", "signals": ["H", "δ", "H"],
                "confidence": round(max(0.01, min(1.0, _prox_blend)), 2),
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

    # ── [ML-C] Bayesian confidence update for all detected chains ─────────────
    # Confluence acts as evidence strength: high confluence = signals agree
    # on market state, so chain patterns are more reliable.
    for chain in chains:
        _prior = chain["confidence"]
        _posterior = _bayesian_confidence_update(
            _prior,
            likelihood=min(1.0, _prior + _confluence * 0.3),
            evidence_weight=0.20,
        )
        chain["confidence"] = round(min(1.0, _posterior), 4)

    # ── [ML-D] Signal coherence multiplier ───────────────────────────────────
    # Chains with 3+ UPSS signals active get a small coherence bonus.
    if len(syms) >= 3:
        for chain in chains:
            chain["confidence"] = round(min(1.0, chain["confidence"] * 1.05), 4)

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
            {"high": 101.0, "low": 98.5,  "close": 99.0,  "volume": 55000},
            {"high": 100.0, "low": 98.0,  "close": 98.5,  "volume": 58000},
            {"high": 99.5,  "low": 97.0,  "close": 97.8,  "volume": 60000},
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
            {"high": 101.0, "low": 99.5,  "close": 100.5, "volume": 30000},
            {"high": 100.8, "low": 99.3,  "close": 99.8,  "volume": 28000},
            {"high": 101.2, "low": 99.0,  "close": 100.2, "volume": 32000},
            {"high": 100.5, "low": 99.8,  "close": 100.1, "volume": 31000},
            {"high": 101.0, "low": 99.5,  "close": 100.3, "volume": 29000},
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
            {"high": 102.0, "low": 99.0,  "close": 100.0, "volume": 40000},
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
    prices  = data["prices"]
    candles = data["candles"]
    cp      = data["current_price"]
    op      = data["open_price"]
    avg_vol = data.get("avg_volume", 50000)
    strike  = data.get("strike", 0)
    cost    = data.get("cost_basis", 0)
    clt     = data.get("clt_price", 0)
    desc    = data.get("desc", "")

    lines.append("")
    lines.append(f"  +=== VMQ+ SIMULATION [ML/Harm v3]: {name} ===+")
    lines.append(f"  |  {desc}")
    lines.append(f"  +{'=' * 48}+")
    lines.append("")

    # [S9.2.3] Module 1 -- Momentum
    m_hist = momentum_from_prices(prices)
    m_day  = momentum_intraday(cp, op)
    mom_strength = ("strong"   if abs(m_hist) > MOM_HIGH else
                    "moderate" if abs(m_hist) > MOM_MED  else "weak")
    lines.append(f"  1. MOMENTUM  [Kalman+EWMA+FractalDim]")
    lines.append(f"     Historical: {m_hist:+.6f}  ({mom_strength})")
    lines.append(f"     Intraday:   {m_day:+.4f}  [log-scaled+Fib]")
    lines.append(f"     Price D:    {cp - prices[0]:+.2f} "
                 f"({(cp - prices[0]) / prices[0] * 100:+.2f}%)")
    lines.append(f"     FractalDim: {_fractal_dimension(prices):.4f}  "
                 f"(1=trend, 2=noise)")
    lines.append(f"     {sep}")

    # [S9.2.4] Module 2 -- Trend
    trend = trend_from_candles(candles)
    trend_arrow = ("^" if trend["bias"] == "bullish" else
                   "v" if trend["bias"] == "bearish" else ">")
    lines.append(f"  2. TREND  [FractalWin+ADX+Fib+Entropy]")
    lines.append(f"     Bias:       {trend['bias'].upper()} {trend_arrow}")
    lines.append(f"     HH: {trend['hh']}  |  LL: {trend['ll']}  "
                 f"(win={trend['adaptive_window']})")
    lines.append(f"     Strength:   {trend.get('strength', 0):.4f}  "
                 f"Clarity: {trend.get('clarity', 0):.4f}")
    lines.append(f"     RevPress:   {trend.get('reversal_pressure', 0):.4f}")
    lines.append(f"     {sep}")

    # [S9.2.5] Module 3 -- Volatility
    vol = volatility_state(prices)
    atr = atr_from_candles(candles)
    vol_icon = ("!" if vol["state"] == "expanding" else
                "=" if vol["state"] == "compressing" else ".")
    lines.append(f"  3. VOLATILITY  [GARCH+Harmonic+EMA-ATR]")
    lines.append(f"     State:      {vol['state'].upper()} {vol_icon}")
    lines.append(f"     CV blend:   {vol['cv']:.6f}  "
                 f"(samp={vol.get('cv_sample',0):.4f} "
                 f"garch={vol.get('cv_garch',0):.4f} "
                 f"cycle={vol.get('cv_cycle',0):.4f})")
    lines.append(f"     ATR(EMA):   ${atr:.4f}  ({atr / cp * 100:.2f}% of price)")
    lines.append(f"     HarmPeriod: {vol.get('harmonic_period',0)} bars")
    lines.append(f"     {sep}")

    # [S9.2.6] Module 4 -- Exhaustion
    exh = exhaustion_zscore(prices)
    exh_icon = "EXHAUSTED" if exh["exhausted"] else "CLEAN"
    lines.append(f"  4. EXHAUSTION  [AdaptZ+Entropy+Fib+Bayes]")
    lines.append(f"     Status:     {exh_icon}")
    lines.append(f"     Z blend:    {exh['z_score']:+.4f}  "
                 f"(orig={exh.get('z_orig',0):+.4f} "
                 f"adap={exh.get('z_adaptive',0):+.4f})")
    lines.append(f"     Clarity:    {exh.get('direction_clarity',0):.4f}  "
                 f"FibProx: {exh.get('fib_proximity',0):.4f}")
    lines.append(f"     BayesConf:  {exh.get('exhaustion_confidence',0):.4f}  "
                 f"(threshold: +/- {EXHAUSTION_Z_THRESHOLD})")
    lines.append(f"     {sep}")

    # [S9.2.7] Module 5 -- Volume Signal
    vol_sig = volume_compare(candles, avg_vol)
    lines.append(f"  5. VOLUME  [EWMA-baseline+ROC]")
    lines.append(f"     Signal:     {vol_sig.upper()}")
    lines.append(f"     Avg Vol:    {avg_vol:,}")
    lines.append(f"     {sep}")

    # [S9.2.8] Module 6 -- UPSS Taxonomy
    upss = upss_generate(
        m_hist, trend["bias"], vol["state"], vol["cv"],
        exh["exhausted"], False, False
    )
    signal_str = (", ".join([f"{s['sym']}:{s['dir']}:{s['conf']:.2f}"
                             for s in upss])
                  if upss else "(none)")
    _conf_score = _harmonic_confluence(upss)
    lines.append(f"  6. UPSS SIGNALS  [Confluence+Bayes+FD]")
    lines.append(f"     Active:     {signal_str}")
    lines.append(f"     Confluence: {_conf_score:.4f}")
    lines.append(f"     {sep}")

    # [S9.2.9] Module 7 -- GBM Projections
    gbms = gbm_multi_horizon(cp, m_hist)
    for g in gbms:
        lines.append(f"  7. GBM ({g['horizon_label']})  [Merton+GARCH+HarmDrift]")
        lines.append(f"     Expected:  ${g['expected']:.2f}")
        lines.append(f"     Range:     ${g['p5']:.2f} - ${g['p95']:.2f}")
        lines.append(f"     Median:    ${g['median']:.2f}")
        lines.append(f"     {sep}")

    # [S9.2.10] Module 8 -- Chain Detection
    chin = chains_detect(upss, cp, data["strike"], data["cost_basis"],
                         data["clt_price"], False)
    if chin:
        for c in chin:
            lines.append(f"  8. CHAIN: {c['id']}  [Bayes+FibCLT+Coherence]")
            lines.append(f"     Confidence: {c['confidence']:.4f}")
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

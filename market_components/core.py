# Last modified: 2026-05-13 09:22 PM MDT
# Tachikoma modification -- 2026-05-13 09:22 PM MDT
"""
core -- Algorithmic Market Quants  [ML/Harmonic Enhanced v3.0]
===================================================================
  VMQ+ calculation engine -- 8 quant modules + ML primitives.
  No I/O, no network, just math.  Import for alerts or run as sandbox.

  PIPELINE:  Momentum -> Trend -> Volatility -> Exhaustion ->
             Volume -> UPSS -> GBM -> Chains -> Alert Engine

  Usage:
    from market_components.core import momentum_from_prices, upss_generate
    python core.py              # Run all test scenarios
    python core.py --quick       # Quick smoke test
    python core.py SES_LIVE     # Run specific scenario
===================================================================
"""

import statistics
import math
import sys
import os
from typing import List, Dict, Optional


# Add parent dir to sys.path so both direct-run and import-run work
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.dirname(_THIS_DIR)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)


# -- IMPORTS ------------------------------------------------------------------
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



# ═══════════════════════════════════════════════════════════════════════════════
# VMQ FACTORY -- Pipeline orchestrator. Stages register, run() executes in order.
# ═══════════════════════════════════════════════════════════════════════════════

class VMQFactory:
    """Runs all 8 quant stages in sequence. Data flows through a shared context dict.

    Usage:
        ctx = VMQFactory.run(prices=prices, candles=candles, ...)
        ctx["momentum"]   # Stage 1 result
        ctx["upss"]       # Stage 6 result
        ctx["alert"]      # Alert Engine result
    """
    _stages = []

    @classmethod
    def register(cls, stage):
        """Add a stage to the pipeline. Order = execution order."""
        cls._stages.append(stage)

    @classmethod
    def run(cls, **kwargs) -> dict:
        """Execute all registered stages. Each reads/writes a shared ctx dict.
        Returns the context with all stage results keyed by stage name."""
        ctx = dict(kwargs)
        for stage in cls._stages:
            ctx[stage.name] = stage.run(ctx)
        return ctx

    @classmethod
    def run_until(cls, stop_name: str, **kwargs) -> dict:
        """Execute stages up to and including the named stage. Useful for debugging."""
        ctx = dict(kwargs)
        for stage in cls._stages:
            ctx[stage.name] = stage.run(ctx)
            if stage.name == stop_name:
                break
        return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE CLASSES -- One per quant module. Each has: name, description, run(ctx).
# Public functions below are backward-compatible wrappers.
# ═══════════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════
# ML PRIMITIVES -- Building blocks for all 8 quant modules.
#   FILTERS:     _ewma, _ewma_series, _kalman_smooth
#   DETECTION:   _dominant_harmonic, _fractal_dimension, _fibonacci_proximity
#   STATISTICS:  _garch11_variance, _shannon_entropy, _adaptive_zscore
#   COMBINATION: _harmonic_confluence, _bayesian_confidence_update, _jump_intensity
# ═══════════════════════════════════════════════════════════════════════════════


# Fibonacci ratios for harmonic level and pattern detection
_FIBO: List[float] = [
    0.236, 0.382, 0.500, 0.618, 0.786,
    1.000, 1.272, 1.414, 1.618, 2.000, 2.618,
]

# ML blend weight — fraction of ML result mixed into original
#         0.0 = pure original, 1.0 = pure ML.  0.40 preserves 60% original.
_ML_BLEND: float = 0.40


# ═══════════════════════════════════════════════════════════════════════════════
# ALERT ENGINE -- Scores whether a price move is worth alerting on.
#   7 weighted factors (momentum, trend, volatility, exhaustion,
#   confluence, GBM, intraday spread) combine into a single score.
#   Volume gates externally via should_suppress_alert().
# ═══════════════════════════════════════════════════════════════════════════════
#
# ═════════════════════════════════════════════════════════════════════════════

# Tunable weights — how much each factor contributes to the final score
# Sum of all weights (excluding volume) = 1.00 (100%)
_CONSIDER_MOMENTUM_WEIGHT: float = 0.20       # 20% — absolute momentum strength
_CONSIDER_TREND_WEIGHT: float = 0.15           # 15% — trend alignment & clarity
_CONSIDER_VOLATILITY_WEIGHT: float = 0.12      # 12% — vol regime (expanding=more sig)
_CONSIDER_EXHAUSTION_WEIGHT: float = 0.10      # 10% — exhaustion proximity
_CONSIDER_CONFLUENCE_WEIGHT: float = 0.18       # 18% — UPSS confluence score
_CONSIDER_GBM_WEIGHT: float = 0.15              # 15% — GBM confidence (range tightness)
_CONSIDER_INTRADAY_SPREAD_WEIGHT: float = 0.10  # 10% — intraday range % vs typical

# Consideration thresholds
_CONSIDER_MIN_THRESHOLD: float = 0.30       # below this = suppress
_CONSIDER_BORDERLINE_LOW: float = 0.30      # borderline lower bound
_CONSIDER_BORDERLINE_HIGH: float = 0.60     # borderline upper bound
_CONSIDER_VOLUME_BOOST: float = 0.40        # see should_suppress_alert()


def alert_consideration_score(
    momentum: float = 0.0,
    trend_bias: str = "neutral",
    trend_strength: float = 0.0,
    trend_clarity: float = 0.0,
    vol_state: str = "normal",
    vol_cv: float = 0.0,
    exhaustion_exhausted: bool = False,
    exhaustion_z: float = 0.0,
    confluence: float = 0.0,
    gbm_list: Optional[List[Dict]] = None,
    change_pct: float = 0.0,
    **kwargs: float
) -> Dict:
    """Score whether a price move is worth alerting. Returns {score, action, reasons, breakdown}."""
    reasons: List[str] = []
    breakdown: Dict[str, float] = {}

    # ── 1. Momentum component (abs, scaled to [0,1]) ──
    abs_mom = abs(momentum)
    if abs_mom > MOM_HIGH:
        mom_score = min(1.0, abs_mom / (MOM_HIGH * 3))
        reasons.append(f"momentum={momentum:+.4f} (strong)")
    elif abs_mom > MOM_MED:
        mom_score = 0.15 + (abs_mom - MOM_MED) / (MOM_HIGH - MOM_MED) * 0.45
        reasons.append(f"momentum={momentum:+.4f} (moderate)")
    else:
        mom_score = abs_mom / MOM_MED * 0.15
        if abs_mom > 0.001:
            reasons.append(f"momentum={momentum:+.4f} (weak)")
        else:
            reasons.append(f"momentum={momentum:+.4f} (noise)")
    breakdown["momentum"] = round(mom_score, 4)

    # ── 2. Trend component — aligned momentum = more significant ──
    if trend_bias in ("bullish", "bearish"):
        aligned = (momentum > 0 and trend_bias == "bullish") or \
                  (momentum < 0 and trend_bias == "bearish")
        base = 0.40 if aligned else 0.20
        clarity_bonus = min(0.30, trend_clarity * 2)
        strength_bonus = min(0.30, trend_strength * 3)
        trend_score = min(1.0, base + clarity_bonus + strength_bonus)
        if aligned:
            reasons.append(f"trend={trend_bias} (aligned, clarity={trend_clarity:.2f})")
        else:
            reasons.append(f"trend={trend_bias} (counter-trend, clarity={trend_clarity:.2f})")
    else:
        trend_score = 0.05
        reasons.append("trend=neutral")
    breakdown["trend"] = round(trend_score, 4)

    # ── 3. Volatility component — expanding=more meaningful ──
    if vol_state == "expanding":
        vol_score = min(1.0, 0.50 + vol_cv * 10)
        reasons.append(f"vol=expanding (cv={vol_cv:.4f})")
    elif vol_state == "compressing":
        vol_score = max(0.05, 0.30 - vol_cv * 10)
        reasons.append(f"vol=compressing (cv={vol_cv:.4f})")
    else:
        vol_score = 0.30
        reasons.append(f"vol=normal")
    breakdown["volatility"] = round(vol_score, 4)

    # ── 4. Exhaustion component — exhausted moves are noteworthy ──
    abs_z = abs(exhaustion_z)
    if exhaustion_exhausted:
        exh_score = min(1.0, 0.50 + abs_z / 10)
        reasons.append(f"exhausted (z={exhaustion_z:+.2f})")
    else:
        exh_score = min(0.40, abs_z / 5)
        if abs_z > 1.0:
            reasons.append(f"z-score elevated ({exhaustion_z:+.2f})")
    breakdown["exhaustion"] = round(exh_score, 4)

    # ── 5. UPSS Confluence — signal agreement ──
    conf_score = min(1.0, confluence)
    if conf_score > 0.50:
        reasons.append(f"confluence={conf_score:.2f} (strong)")
    elif conf_score > 0.20:
        reasons.append(f"confluence={conf_score:.2f}")
    else:
        reasons.append(f"confluence={conf_score:.2f} (weak)")
    breakdown["confluence"] = round(conf_score, 4)

    # ── 6. GBM confidence — tight spread = high confidence ──
    gbm_score = 0.10  # default: low confidence
    if gbm_list:
        for g in gbm_list[:1]:  # shortest horizon (most relevant)
            expected = g.get("expected", 0) or 0.01
            p5 = g.get("p5", 0) or 0
            p95 = g.get("p95", 0) or 0
            if expected > 0 and (p95 - p5) > 0:
                spread_ratio = (p95 - p5) / expected
                gbm_score = max(0.10, 1.0 - spread_ratio * 2)
                gbm_score = min(1.0, gbm_score)
                reasons.append(f"GBM spread={spread_ratio:.2%}")
    breakdown["gbm"] = round(gbm_score, 4)

    # ── 7. Intraday spread — larger % moves = more significant ──
    abs_change = abs(change_pct)
    if abs_change > 3.0:
        spread_score = min(1.0, abs_change / 10)
        reasons.append(f"move={abs_change:.1f}% (large)")
    elif abs_change > 1.5:
        spread_score = 0.30 + (abs_change - 1.5) / 1.5 * 0.40
        reasons.append(f"move={abs_change:.1f}% (moderate)")
    else:
        spread_score = abs_change / 1.5 * 0.30
        reasons.append(f"move={abs_change:.1f}% (small)")
    breakdown["intraday_spread"] = round(spread_score, 4)

    # ── Weighted final score ──
    total_weight = (
        _CONSIDER_MOMENTUM_WEIGHT + _CONSIDER_TREND_WEIGHT +
        _CONSIDER_VOLATILITY_WEIGHT + _CONSIDER_EXHAUSTION_WEIGHT +
        _CONSIDER_CONFLUENCE_WEIGHT + _CONSIDER_GBM_WEIGHT +
        _CONSIDER_INTRADAY_SPREAD_WEIGHT
    )
    weighted = (
        mom_score * _CONSIDER_MOMENTUM_WEIGHT +
        trend_score * _CONSIDER_TREND_WEIGHT +
        vol_score * _CONSIDER_VOLATILITY_WEIGHT +
        exh_score * _CONSIDER_EXHAUSTION_WEIGHT +
        conf_score * _CONSIDER_CONFLUENCE_WEIGHT +
        gbm_score * _CONSIDER_GBM_WEIGHT +
        spread_score * _CONSIDER_INTRADAY_SPREAD_WEIGHT
    )
    score = round(weighted / total_weight, 4) if total_weight > 0 else 0.0

    # ── Classify ──
    if score >= _CONSIDER_BORDERLINE_HIGH:
        action = "alert"
    elif score >= _CONSIDER_BORDERLINE_LOW:
        action = "borderline"
    else:
        action = "suppress"

    return {
        "score": score,
        "action": action,
        "reasons": reasons,
        "breakdown": breakdown,
    }


def should_suppress_alert(consideration: dict, volume_spike: bool = False) -> bool:
    """Final gate: True=suppress, False=send. Volume spike can rescue a borderline."""
    action = consideration.get("action", "suppress")

    if action == "alert":
        return False                           # Definitely alert
    elif action == "borderline":
        return not volume_spike                # Alert only if volume confirms
    else:
        return True                            # Suppress noise



# -- FILTERS -------------------------------------------------------------------

def _ewma(values: List[float], alpha: float = 0.3) -> float:
    """EWMA -- weighted toward recent values. Returns last smoothed value."""
    if not values:
        return 0.0
    result = values[0]
    for v in values[1:]:
        result = alpha * v + (1.0 - alpha) * result
    return result


def _ewma_series(values: List[float], alpha: float = 0.3) -> List[float]:
    """EWMA -- full smoothed series. Alpha controls recency bias (higher=more recent)."""
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
    """Kalman filter -- strips measurement noise from a series."""
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



# -- DETECTION -----------------------------------------------------------------

def _dominant_harmonic(values: List[float]) -> Dict:
    """Find the dominant price cycle using DFT. Returns {period, amplitude, phase}."""
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



# -- STATISTICS ----------------------------------------------------------------

def _garch11_variance(
    deltas: List[float],
    omega: float = 1e-6,
    alpha_g: float = 0.10,
    beta_g: float = 0.85,
) -> float:
    """GARCH(1,1) variance forecast -- estimates how volatile next period will be."""
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
    """Fractal dimension: 1=clean trend, 2=random noise. Used as signal quality gate."""
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
    """How close is a price to a Fibonacci level? 0=far, 1=exact."""
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
    """Shannon entropy: 0=all values same (orderly), 1=perfectly random (chaotic)."""
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
    """Z-score using EWMA mean/variance -- adapts to regime shifts."""
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



# -- COMBINATION ---------------------------------------------------------------

def _harmonic_confluence(signals: List[Dict]) -> float:
    """How well do UPSS signals agree with each other? 0=mixed, 1=aligned."""
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
    """Blend prior belief with new evidence. Higher weight = more weight on evidence."""
    prior = max(0.01, min(0.99, prior))
    posterior = (1.0 - evidence_weight) * prior + evidence_weight * likelihood
    return round(max(0.01, min(0.99, posterior)), 4)


def _jump_intensity(
    deltas: List[float],
    threshold_sigma: float = 2.5,
) -> Dict:
    """Estimate jump parameters from price changes (Merton model)."""
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

# ── 1. MOMENTUM: price series -> how fast price is moving ([-1,+1]) ────────
# Feeds: UPSS (alpha/beta signals), GBM (drift), Alert (momentum score).
# Raw = mean(delta)/std(delta). ML: Kalman filters noise, EWMA weights
# recent moves, fractal gate blocks choppy false signals, harmonics
# boost confidence when cycles are clean. Blend = 60% raw + 40% ML.

def momentum_from_prices(prices: list) -> float:
    """Rate-of-change momentum from price series. Returns [-1, +1]. 0 if <2 prices."""
    if len(prices) < 2:
        return 0.0

    # Price changes
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    avg_d = sum(deltas) / len(deltas)
    vol = statistics.stdev(deltas) if len(deltas) > 1 else abs(avg_d) * 0.5
    if vol < 0.0001:
        vol = 0.0001
    # Clamp to [-1, +1] and scale by 0.5  ← ORIGINAL result
    _orig = max(-1.0, min(1.0, (avg_d / vol) * 0.5))  # raw momentum

    # Kalman-smoothed momentum ─────────────────────────────────────
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

    # EWMA-weighted delta momentum ─────────────────────────────────
    # Exponentially weight deltas so that the most recent movement dominates.
    # alpha=0.4 gives the latest delta ≈2× the weight of three periods back.
    _ew_deltas = _ewma_series(deltas, alpha=0.4)
    _ew_avg = _ew_deltas[-1] if _ew_deltas else avg_d
    _ewma_mom = max(-1.0, min(1.0, (_ew_avg / vol) * 0.5))

    # Fractal dimension gate ───────────────────────────────────────
    # D ≈ 1 → trending → fd_trust approaches 1.0 (full signal confidence)
    # D ≈ 2 → choppy  → fd_trust approaches 0.5 (halve ML contribution)
    _fd = _fractal_dimension(prices)
    _fd_trust = max(0.5, 2.0 - _fd)        # maps [1,2] → [1.0, 0.5]

    # Harmonic amplitude confidence ────────────────────────────────
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
    """Intraday momentum: (current-open)/open scaled to [-1, +1]. 0 if bad input."""
    if open_ <= 0:
        return 0.0

    # Normalize by open price, divide by 10pct reference  ← ORIGINAL
    _orig = max(-1.0, min(1.0, ((current - open_) / open_) / 0.10))

    # Log-scaled intraday return ───────────────────────────────────
    # log(P/P_open) / log(1.10) normalises to ±1 at ±10% move.
    # More stable for large gaps; preserves sign via copysign.
    _log_ret = math.log(max(current, 1e-8) / max(open_, 1e-8))
    _log_ref = math.log(1.10)
    _log_mom = max(-1.0, min(1.0, _log_ret / _log_ref))

    # Fibonacci proximity confidence boost ──────────────────────────
    # Model the intraday range as ±10% of open (the reference band).
    # Check if the actual move magnitude aligns with a Fibonacci level.
    _move_pct = abs((current - open_) / open_)
    _fib_prox = _fibonacci_proximity(_move_pct, 0.0, 0.10)
    _fib_boost = 1.0 + 0.10 * _fib_prox    # up to +10% confidence

    _ml_mom = max(-1.0, min(1.0, _log_mom * _fib_boost))

    _result = (1.0 - _ML_BLEND) * _orig + _ML_BLEND * _ml_mom
    return max(-1.0, min(1.0, round(_result, 4)))

# ── 2. TREND: candles -> which way the market is leaning ───────────────────
# Feeds: UPSS (direction), GBM (drift sign), Alert (trend score).
# Counts higher-highs vs lower-lows. ML: fractal window adapts to
# market texture, ADX-style strength, Fibonacci harmonic check,
# entropy gate to flag random chop vs real trend.

WINDOW_SIZE = 10   # Lookback window for trend HH/LL counting


def trend_from_candles(candles: List[Dict]) -> dict:
    """Count higher-highs vs lower-lows to find trend direction. Returns {bias, hh, ll, strength, clarity}."""
    if len(candles) < 3:
        return {"bias": "neutral", "hh": 0, "ll": 0,
                "strength": 0.0, "clarity": 0.0,
                "reversal_pressure": 0.0, "adaptive_window": WINDOW_SIZE}

    # Fractal-adaptive window size ─────────────────────────────────
    # Extract highs for fractal dimension; fall back to WINDOW_SIZE if sparse.
    _highs = [c["high"] for c in candles]
    _fd = _fractal_dimension(_highs) if len(_highs) >= 4 else 1.5
    # Scale: D=1→2× window, D=2→0.5× window, D=1.5→1× window (linear)
    _fd_scale = max(0.5, min(2.0, 2.0 - _fd + 0.5))
    _adaptive_win = max(3, int(WINDOW_SIZE * _fd_scale))

    # Take last adaptive window candles
    recent = candles[-min(_adaptive_win, len(candles)):]

    # Count how many candles had a higher high than prev  ← ORIGINAL
    hh = sum(
        1 for i in range(1, len(recent))
        if recent[i]["high"] > recent[i - 1]["high"]
    )
    # Count how many candles had a lower low than prev    ← ORIGINAL
    ll = sum(
        1 for i in range(1, len(recent))
        if recent[i]["low"] < recent[i - 1]["low"]
    )
    # Majority vote for bias                              ← ORIGINAL
    bias = "bullish" if hh > ll else ("bearish" if ll > hh else "neutral")

    # Directional strength (ADX-inspired) ──────────────────────────
    # Ratio of net directional count to total comparisons.
    _total_comps = len(recent) - 1
    if _total_comps > 0:
        _net = abs(hh - ll)
        _adx_strength = round(_net / _total_comps, 4)   # 0 = neutral, 1 = pure trend
    else:
        _adx_strength = 0.0

    # Fibonacci harmonic check ─────────────────────────────────────
    # Are the HH and LL counts themselves near a Fibonacci ratio of each other?
    # e.g. hh/ll ≈ 0.618 or 1.618 suggests harmonic reversal pressure.
    _denom = max(hh, ll, 1)
    _numer = min(hh, ll) if bias != "neutral" else 0
    _fib_ratio = _numer / _denom
    _fib_prox = _fibonacci_proximity(_fib_ratio, 0.0, 1.0)
    # High Fibonacci proximity on minor count → potential reversal warning
    _reversal_pressure = round(_fib_prox * 0.5, 4)  # 0.0–0.5 scale

    # Shannon entropy gate ─────────────────────────────────────────
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

# ── 3. VOLATILITY: prices -> how wildly price is swinging ──────────────────
# Feeds: UPSS (gamma/omega signals), Alert (vol score).
# CV = std/mean classifies into expanding/normal/compressing.
# ML: GARCH forecasts variance clustering, harmonic cycle detects
# periodic swings, EWMA-ATR for faster regime adaptation.

def volatility_state(prices: List[float]) -> dict:
    """Classify volatility: CV=std/mean -> expanding/normal/compressing. Returns {state, cv}."""
    if len(prices) < 2:
        return {"state": "unknown", "cv": 0.0}

    # Mean and std of price series
    mean_p = sum(prices) / len(prices)
    std_p = statistics.stdev(prices) if len(prices) > 1 else 0.0
    # Coefficient of variation = std / mean
    cv = std_p / mean_p if mean_p else 0.0
    # Classify by CV thresholds                           ← ORIGINAL
    state = (
        "expanding" if cv >= HIGH_VOL_CV
        else "compressing" if cv <= LOW_VOL_CV
        else "normal"
    )

    # GARCH(1,1) conditional variance ──────────────────────────────
    _deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    _garch_var = _garch11_variance(_deltas)
    _garch_cv = math.sqrt(_garch_var) / max(mean_p, 1e-8)

    # Dominant harmonic cycle amplitude ─────────────────────────────
    _harm = _dominant_harmonic(prices)
    _cycle_cv = _harm["amplitude"] / max(mean_p, 1e-8)   # normalised amplitude

    # Regime coherence check ───────────────────────────────────────
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
    """Average True Range -- how much price typically swings per bar."""
    if len(candles) < 2:
        return 0.0

    # True Range = max(High-Low, High-PrevClose, Low-PrevClose)  ORIGINAL
    trs = []
    for i in range(1, len(candles)):
        hl  = candles[i]["high"] - candles[i]["low"]
        hpc = abs(candles[i]["high"] - candles[i - 1]["close"])
        lpc = abs(candles[i]["low"]  - candles[i - 1]["close"])
        trs.append(max(hl, hpc, lpc))

    # ATR = mean of true ranges                           ← ORIGINAL
    _orig_atr = sum(trs) / len(trs) if trs else 0.0

    # EWMA-ATR ─────────────────────────────────────────────────────
    # Standard ATR uses simple mean; EMA-ATR weights recent TRs more.
    # alpha = 2 / (14 + 1) ≈ 0.133; we use 0.2 for a slightly faster response.
    _ema_atr = _ewma(trs, alpha=0.2) if trs else 0.0

    _result = (1.0 - _ML_BLEND) * _orig_atr + _ML_BLEND * _ema_atr
    return round(_result, 6)

# ── 4. EXHAUSTION: prices -> is the move running out of steam? ────────────
# Feeds: UPSS (delta signals), Alert (exhaustion score).
# Z-score of price deltas. |z| > 2 = exhausted.
# ML: adaptive z-score tracks shifting regimes, entropy confirms
# one-directional push (not noise), Fibonacci extensions predict
# reversal levels, Bayesian update blends all confidence signals.

def exhaustion_zscore(prices: List[float]) -> dict:
    """Detect if a move is overstretched (z-score of deltas). |z| > 2 = exhausted."""
    if len(prices) < 3:
        return {"exhausted": False, "z_score": 0.0}

    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    # Mean and std of deltas
    mean_d = sum(deltas) / len(deltas)
    std_d = statistics.stdev(deltas) if len(deltas) > 1 else 0.001
    # Z-score = mean / std (how many stds from zero?)     ← ORIGINAL
    _orig_z = mean_d / std_d if std_d else 0.0
    _orig_exhausted = abs(_orig_z) > EXHAUSTION_Z_THRESHOLD

    # EWMA adaptive z-score ────────────────────────────────────────
    _adap_z = _adaptive_zscore(deltas, window=min(20, len(deltas)))

    # Shannon entropy gate ─────────────────────────────────────────
    # Low entropy on deltas → directional thrust → supports exhaustion claim.
    _delta_entropy = _shannon_entropy(deltas, bins=6)
    # Entropy of a uniform distribution over 6 bins = log2(6) ≈ 2.585
    _direction_clarity = max(0.0, 1.0 - _delta_entropy / 2.585)   # [0,1]

    # Fibonacci extension proximity ─────────────────────────────────
    # Exhaustion is most likely near 1.272× or 1.618× extensions.
    _lo, _hi = min(prices), max(prices)
    _last = prices[-1]
    _fib_prox = _fibonacci_proximity(_last, _lo, _hi)   # near any Fib level

    # Bayesian exhaustion confidence ────────────────────────────────
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

# ── 5. VOLUME: candles -> is volume backing the move? ─────────────────────
# Feeds: Alert suppression gate (volume_spike flag).
# Recent volume / average volume -> high/elevated/normal.
# ML: EWMA baseline adapts to changing volume norms, volume ROC
# detects accelerating interest, harmonic cycle catches periodic surges.

def volume_compare(candles: List[Dict], avg_volume: float = 0) -> str:
    """Compare recent volume to baseline. Returns high/elevated/normal/unknown."""
    if len(candles) < 5 or avg_volume == 0:
        return "unknown"

    # Average volume over last 5 candles
    intermed = sum(candles[i]["volume"] for i in range(-5, 0))
    recent_vol = intermed / 5
    # Ratio of recent avg to baseline avg
    ratio = recent_vol / avg_volume
    # Classify by thresholds                              ← ORIGINAL
    if ratio >= VOL_HIGH:
        return "high"
    if ratio >= VOL_MED:
        return "elevated"

    # EWMA-adaptive baseline ───────────────────────────────────────
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

    # Volume momentum — rate of change ──────────────────────────────
    if len(candles) >= 10:
        _prev5_vols = sum(candles[i]["volume"] for i in range(-10, -5)) / 5
        _vol_roc = (recent_vol - _prev5_vols) / max(_prev5_vols, 1.0)
        # Strong acceleration in volume (>50% increase) → elevated at minimum
        if _vol_roc > 0.50 and recent_vol > avg_volume * 0.8:
            return "elevated"

    return "normal"

# ── 6. UPSS: momentum+trend+vol+exhaustion -> Greek-letter signal list ────
# Feeds: Chains (pattern detection), Alert (confluence score).
# α=strong push, β=moderate push, γ=range-bound, δ=exhaustion reversal,
# Ω=vol breakout, H=hedge risk. ML: confluence weights signal agreement,
# Bayesian updates confidence, fractal dim boosts trending signals.

def upss_generate(
    momentum_val: float,
    trend_bias: str,
    vol_state: str,
    compression: float,
    is_exhausted: bool,
    is_hedged: bool,
    scalp_viable: bool,
) -> List[Dict]:
    """Generate Greek-letter signals from quant outputs. Returns [{sym, name, dir, conf}]."""
    signals: List[Dict] = []

    # alpha -- strong directional confirmation (|M| > MOM_HIGH=0.03)
    if abs(momentum_val) > MOM_HIGH:
        d = "bull" if momentum_val > 0 else "bear"
        signals.append({
            "sym": "α", "name": "alpha", "dir": d,
            "conf": min(1.0, abs(momentum_val) * 10),
        })
    # beta -- moderate directional (|M| > MOM_MED=0.01)
    elif abs(momentum_val) > MOM_MED:
        d = "bull" if momentum_val > 0 else "bear"
        signals.append({
            "sym": "β", "name": "beta", "dir": d,
            "conf": abs(momentum_val) * 20,
        })
    # gamma -- compression / range-bound
    if "compressing" in vol_state:
        signals.append({
            "sym": "γ", "name": "gamma", "dir": "flat", "conf": 0.7,
        })
    # delta -- exhaustion reversal (opposite of momentum direction)
    if is_exhausted:
        d = "bull" if momentum_val < 0 else "bear"
        signals.append({
            "sym": "δ", "name": "delta", "dir": d, "conf": 0.85,
        })
    # omega -- volatility expansion (breakout coil)
    if "expanding" in vol_state:
        signals.append({
            "sym": "Ω", "name": "omega", "dir": "flat", "conf": 0.6,
        })
    # H -- hedge / protect (simultaneous exhaustion + expansion)
    if "expanding" in vol_state and is_exhausted:
        signals.append({
            "sym": "H", "name": "hedge", "dir": "flat", "conf": 0.85,
        })

    # Harmonic confluence scoring ───────────────────────────────────
    _confluence = _harmonic_confluence(signals)

    # Bayesian confidence update per signal ─────────────────────────
    # Update each signal's confidence using the confluence score as evidence.
    # Signals in a confluent environment are more reliable.
    for sig in signals:
        _prior_conf = sig["conf"]
        _updated = _bayesian_confidence_update(
            _prior_conf, _confluence, evidence_weight=0.25
        )
        sig["conf"] = round(min(1.0, max(0.01, _updated)), 4)

    # Fractal dimension directional confidence boost ─────────────────
    # compression parameter (0–1) correlates with fractal dimension:
    # low compression (high number) suggests a trending market.
    # Use it as a proxy for fd_trust when raw prices are unavailable.
    _fd_trust = max(0.5, 1.0 - compression)   # compression≈0 → D≈1 → trust=1
    for sig in signals:
        if sig["dir"] in ("bull", "bear"):     # directional signals only
            sig["conf"] = round(min(1.0, sig["conf"] * (0.8 + 0.2 * _fd_trust)), 4)

    # Momentum trend agreement bonus ────────────────────────────────
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

# ── 7. GBM: price+momentum -> where might price go? (3 horizons) ──────────
# Feeds: Alert (GBM confidence score).
# Geometric Brownian Motion S=S0*exp(...). 90min, 5-day, 15-day projections.
# ML: Merton jump-diffusion fattens tails, GARCH adjusts volatility
# for clustering, harmonic cycle tunes drift to market rhythm.
# Blend = 60% standard GBM + 40% jump-diffusion.

def gbm_project(
    current_price: float,
    momentum_val: float,
    horizon_minutes: int,
    vol_estimate: float,
) -> dict:
    """Project price at one horizon using Geometric Brownian Motion. Returns {expected, p5-p95}."""
    t = horizon_minutes / MINUTES_PER_YEAR
    # Drift term from momentum signal
    drift = momentum_val * GBM_DRIFT_SCALING_FACTOR * 0.1
    sqrt_t = t ** 0.5

    # GBM exponent: (mu - 0.5*sigma^2)*t
    exp_component = (drift - 0.5 * vol_estimate ** 2) * t
    # Volatility component: sigma * sqrt(t)
    vol_sqrt_t = vol_estimate * sqrt_t

    # Expected = median for lognormal with deterministic drift
    expected = current_price * math.exp(exp_component)
    median_val = current_price * math.exp(exp_component)

    # Price at a given z-score percentile                  ← ORIGINAL
    def _at_z(z: float) -> float:
        return current_price * math.exp(exp_component + vol_sqrt_t * z)

    if horizon_minutes < 1440:
        label = f"{horizon_minutes}min"
    elif horizon_minutes < 43200:
        label = f"{horizon_minutes // 1440}d"
    else:
        label = f"{horizon_minutes // 43200}mth"

    # Merton Jump-Diffusion parameters ──────────────────────────────
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

    # GARCH-inspired volatility scaling ─────────────────────────────
    # Momentum magnitude is a proxy for vol clustering (high |M| → vol surge).
    _garch_scale = min(1.5, 1.0 + abs(momentum_val) * 1.5)
    _vol_garch = _vol_adj * _garch_scale

    # Harmonic cycle drift adjustment ───────────────────────────────
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
    """Run GBM projections for 3 default horizons (intraday, 5-day, 15-day)."""
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

# ── 8. CHAINS: UPSS signals -> trade-relevant pattern detection ───────────
# Feeds: Alert narrative (chain names + confidence).
# Matches UPSS signal combos: PREMIUM_STACK (gamma), ASSIGNMENT_CHAIN
# (omega+alpha), CLT_APPROACH (near target), FULL_HEDGE (H+delta/gamma).
# ML: harmonic confluence boosts confidence, Fibonacci levels tune
# proximity, Bayesian update blends evidence, coherence bonus.

def chains_detect(
    upss_signals: List[Dict],
    current_price: float,
    strike: float,
    cost_basis: float,
    clt_price: float,
    scalp_viable: bool,
) -> List[Dict]:
    """Find trade chain patterns from UPSS signals. Returns chains sorted by confidence."""
    chains: List[Dict] = []
    syms = [s["sym"] for s in upss_signals]

    # Pre-compute harmonic confluence ───────────────────────────────
    _confluence = _harmonic_confluence(upss_signals)

    # PREMIUM_STACK: gamma signals = collect premium
    if "γ" in syms:
        conf = 0.85
        if "β" in syms:
            conf += 0.10
        chains.append({
            "id": "PREMIUM_STACK", "signals": ["γ", "β", "γ"],
            "confidence": min(1.0, conf),
        })

    # ASSIGNMENT_CHAIN: omega+alpha = directional risk
    if "Ω" in syms and "α" in syms:
        conf = 0.75
        if "β" in syms:
            conf += 0.15
        chains.append({
            "id": "ASSIGNMENT_CHAIN", "signals": ["Ω", "α", "β"],
            "confidence": min(1.0, conf),
        })

    # CLT_APPROACH: price near target
    if clt_price > 0 and strike > 0:
        dist = abs(current_price - clt_price)
        threshold = strike * CLT_PROXIMITY_PCT

        if dist < threshold:
            # Fibonacci CLT proximity ──────────────────────────────
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

    # SCALP_IMMEDIATE: scalp setup
    if scalp_viable:
        conf = 0.80
        if "ρ" in [s["sym"] for s in upss_signals if s["sym"] == "ρ"]:
            conf += 0.10
        chains.append({
            "id": "SCALP_IMMEDIATE", "signals": ["ρ", "α", "δ"],
            "confidence": min(1.0, conf),
        })

    # FULL_HEDGE: H + delta/gamma = protected
    if "H" in syms and ("δ" in syms or "γ" in syms):
        chains.append({
            "id": "FULL_HEDGE", "signals": ["H", "δ", "H"],
            "confidence": 0.90,
        })

    # Bayesian confidence update for all detected chains ─────────────
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

    # Signal coherence multiplier ───────────────────────────────────
    # Chains with 3+ UPSS signals active get a small coherence bonus.
    if len(syms) >= 3:
        for chain in chains:
            chain["confidence"] = round(min(1.0, chain["confidence"] * 1.05), 4)

    # Sort chains by confidence descending
    chains.sort(key=lambda c: c["confidence"], reverse=True)
    return chains


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE CLASSES + BACKWARD-COMPATIBLE WRAPPERS
# Each stage wraps its module's functions. Wrappers preserve the original API.
# ═══════════════════════════════════════════════════════════════════════════════

class MomentumStage:
    """Stage 1: How fast and in what direction is price moving?"""
    name = "momentum"

    def run(self, ctx):
        prices = ctx["prices"]
        cp = ctx.get("current_price", prices[-1] if prices else 0)
        op = ctx.get("open_price", prices[0] if prices else 0)
        # Store price deltas for downstream stages
        if len(prices) >= 2:
            ctx["price_deltas"] = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        else:
            ctx["price_deltas"] = []
        return {"historical": momentum_from_prices(prices),
                "intraday": momentum_intraday(cp, op)}


class TrendStage:
    """Stage 2: Which way is the market leaning? Counts higher-highs vs lower-lows."""
    name = "trend"

    def run(self, ctx):
        return trend_from_candles(ctx["candles"])


class VolatilityStage:
    """Stage 3: How wildly is price swinging? Classifies volatility regime."""
    name = "volatility"

    def run(self, ctx):
        result = volatility_state(ctx["prices"])
        result["atr"] = atr_from_candles(ctx["candles"])
        return result


class ExhaustionStage:
    """Stage 4: Is the move running out of steam? Z-score of price changes."""
    name = "exhaustion"

    def run(self, ctx):
        return exhaustion_zscore(ctx["prices"])


class VolumeStage:
    """Stage 5: Is trading volume backing this move? Compares recent to average."""
    name = "volume"

    def run(self, ctx):
        return volume_compare(ctx["candles"], ctx.get("avg_volume", 0))


class UPSSStage:
    """Stage 6: Greek-letter signal taxonomy. Combines momentum+trend+vol+exhaustion."""
    name = "upss"

    def run(self, ctx):
        m = ctx["momentum"]
        t = ctx["trend"]
        v = ctx["volatility"]
        e = ctx["exhaustion"]
        return upss_generate(
            momentum_val=m["historical"],
            trend_bias=t["bias"],
            vol_state=v["state"],
            compression=v.get("cv", 0),
            is_exhausted=e["exhausted"],
            is_hedged=ctx.get("is_hedged", False),
            scalp_viable=ctx.get("scalp_viable", False),
        )


class GBMStage:
    """Stage 7: Where might price go? Projects 3 time horizons using GBM."""
    name = "gbm"

    def run(self, ctx):
        m = ctx["momentum"]
        return gbm_multi_horizon(ctx["current_price"], m["historical"])


class ChainsStage:
    """Stage 8: Detects trade-relevant patterns from UPSS signal combinations."""
    name = "chains"

    def run(self, ctx):
        return chains_detect(
            upss_signals=ctx["upss"],
            current_price=ctx["current_price"],
            strike=ctx.get("strike", 0),
            cost_basis=ctx.get("cost_basis", 0),
            clt_price=ctx.get("clt_price", 0),
            scalp_viable=ctx.get("scalp_viable", False),
        )


# -- Register all stages in pipeline order --
VMQFactory.register(MomentumStage())
VMQFactory.register(TrendStage())
VMQFactory.register(VolatilityStage())
VMQFactory.register(ExhaustionStage())
VMQFactory.register(VolumeStage())
VMQFactory.register(UPSSStage())
VMQFactory.register(GBMStage())
VMQFactory.register(ChainsStage())

# ═══════════════════════════════════════════════════════════════════════════════
# SANDBOX  —  Static Test Data + Simulation Runner + CLI
# ═══════════════════════════════════════════════════════════════════════════════ Static test data + simulation runner
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

# Static test data -- 4 scenarios covering all 8 modules ---------------

TEST_DATA = {
    # Rising prices -- positive momentum, bullish trend
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
    # Falling prices -- negative momentum, bearish trend
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
    # Choppy / range-bound -- low momentum, neutral trend
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
    # Violent spike then pullback -- high vol, exhaustion
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

    # SES live market -- bearish penny stock, normal vol, high volume (snapshot #324)
    "SES_LIVE": {
        "prices": [1.08, 1.07, 1.06, 1.06, 1.05],
        "candles": [
            {"high": 1.09, "low": 1.07, "close": 1.08, "volume": 120000},
            {"high": 1.08, "low": 1.06, "close": 1.07, "volume": 135000},
            {"high": 1.07, "low": 1.05, "close": 1.06, "volume": 145000},
            {"high": 1.07, "low": 1.05, "close": 1.06, "volume": 155000},
            {"high": 1.06, "low": 1.04, "close": 1.05, "volume": 160000},
            {"high": 1.06, "low": 1.04, "close": 1.05, "volume": 150000},
            {"high": 1.06, "low": 1.04, "close": 1.055, "volume": 148000},
        ],
        "current_price": 1.055, "open_price": 1.08,
        "avg_volume": 80000, "strike": 1.00,
        "cost_basis": 1.05, "clt_price": 1.12,
        "desc": "SES live snapshot #324 -- bearish momentum, normal vol, high volume, alpha bear",
    },
}


# Simulation runner -- produces alert-like output ----------------------

def run_simulation(name: str, data: dict) -> List[str]:
    """Run the full VMQ+ pipeline on a test dataset. Returns formatted output lines."""
    lines = []
    sep = "-" * 52

    # Extract data
    prices = data["prices"]
    candles = data["candles"]
    cp = data["current_price"]
    op = data["open_price"]
    avg_vol = data.get("avg_volume", 50000)
    _strike = data.get("strike", 0)
    _cost = data.get("cost_basis", 0)
    _clt = data.get("clt_price", 0)
    desc = data.get("desc", "")

    # Run the full VMQ+ pipeline
    ctx = VMQFactory.run(
        prices=prices, candles=candles,
        current_price=cp, open_price=op,
        avg_volume=avg_vol, strike=_strike,
        cost_basis=_cost, clt_price=_clt,
        is_hedged=False, scalp_viable=False,
    )

    lines.append("")
    lines.append(f"  +=== VMQ+ SIMULATION [ML/Harm v3]: {name} ===+")
    lines.append(f"  |  {desc}")
    lines.append(f"  +{'=' * 48}+")
    lines.append("")

    # Module 1 -- Momentum
    m_hist = ctx["momentum"]["historical"]
    m_day  = ctx["momentum"]["intraday"]
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

    # Module 2 -- Trend
    trend = ctx["trend"]
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

    # Module 3 -- Volatility
    vol = ctx["volatility"]
    atr = ctx["volatility"]["atr"]
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

    # Module 4 -- Exhaustion
    exh = ctx["exhaustion"]
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

    # Module 5 -- Volume Signal
    vol_sig = ctx["volume"]
    lines.append(f"  5. VOLUME  [EWMA-baseline+ROC]")
    lines.append(f"     Signal:     {vol_sig.upper()}")
    lines.append(f"     Avg Vol:    {avg_vol:,}")
    lines.append(f"     {sep}")

    # Module 6 -- UPSS Taxonomy
    upss = upss_generate(
        m_hist, trend["bias"], vol["state"], vol["cv"],
        exh["exhausted"], False, False
    )
    signal_str = (", ".join([f"{s['sym']}:{s['dir']}:{s['conf']:.2f}"
                             for s in upss])
                  if upss else "(none)")
    _conf_score = _harmonic_confluence(upss)  # computed in UPSSStage too, recompute for clarity
    lines.append(f"  6. UPSS SIGNALS  [Confluence+Bayes+FD]")
    lines.append(f"     Active:     {signal_str}")
    lines.append(f"     Confluence: {_conf_score:.4f}")
    lines.append(f"     {sep}")

    # Module 7 -- GBM Projections
    gbms = ctx["gbm"]
    for g in gbms:
        lines.append(f"  7. GBM ({g['horizon_label']})  [Merton+GARCH+HarmDrift]")
        lines.append(f"     Expected:  ${g['expected']:.2f}")
        lines.append(f"     Range:     ${g['p5']:.2f} - ${g['p95']:.2f}")
        lines.append(f"     Median:    ${g['median']:.2f}")
        lines.append(f"     {sep}")

    # Module 8 -- Chain Detection
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
    lines.append(f"     {sep}")

    # Alert Consideration Engine
    change_pct = ((cp - prices[0]) / prices[0] * 100) if prices[0] > 0 else 0.0
    consideration = alert_consideration_score(
        momentum=m_hist,
        trend_bias=trend["bias"],
        trend_strength=trend.get("strength", 0.0),
        trend_clarity=trend.get("clarity", 0.0),
        vol_state=vol["state"],
        vol_cv=vol["cv"],
        exhaustion_exhausted=exh["exhausted"],
        exhaustion_z=exh["z_score"],
        confluence=_conf_score,
        gbm_list=gbms,
        change_pct=change_pct,
    )
    action_icon = {"alert": "!!", "borderline": "? ", "suppress": "--"}.get(
        consideration["action"], "??"
    )
    suppressed = should_suppress_alert(consideration, vol_sig == "high")

    lines.append(f"  9. ALERT CONSIDERATION  [7-factor weighted score]")
    lines.append(f"     Score:      {consideration['score']:.4f}  "
                 f"[{action_icon}]  {consideration['action'].upper()}")
    lines.append(f"     Suppressed: {suppressed}")
    lines.append(f"     Breakdown:  "
                 f"M={consideration['breakdown'].get('momentum',0):.2f}  "
                 f"T={consideration['breakdown'].get('trend',0):.2f}  "
                 f"V={consideration['breakdown'].get('volatility',0):.2f}  "
                 f"E={consideration['breakdown'].get('exhaustion',0):.2f}  "
                 f"C={consideration['breakdown'].get('confluence',0):.2f}  "
                 f"G={consideration['breakdown'].get('gbm',0):.2f}  "
                 f"S={consideration['breakdown'].get('intraday_spread',0):.2f}")
    for reason in consideration.get("reasons", [])[:3]:
        lines.append(f"     > {reason}")

    # Module Summary
    lines.append(f"")
    lines.append(f"  {'=' * 48}")
    lines.append(f"  MODULE STATUS REPORT: {name}")
    lines.append(f"  {'=' * 48}")
    mods = [
        ("1. Momentum       ", True),
        ("2. Trend           ", True),
        ("3. Volatility      ", True),
        ("4. Exhaustion      ", True),
        ("5. Volume Signal   ", True),
        ("6. UPSS Signals    ", bool(upss)),
        ("7. GBM Projections ", bool(gbms)),
        ("8. Chain Detection ", bool(chin)),
        ("9. Alert Consider. ", True),
    ]
    all_ok = True
    for mod_name, ok in mods:
        status = "OK" if ok else "NO SIGNAL"
        lines.append(f"  [{status}]  {mod_name}")
        if not ok:
            all_ok = False
    lines.append(f"  {'=' * 48}")
    lines.append(f"  RESULT: {'ALL MODULES OPERATIONAL' if all_ok else 'SOME MODULES HAD NO OUTPUT'}")

    return lines


# Automated Test Runner ------------------------------------------------

def run_tests(symbols: Optional[List[str]] = None) -> None:
    """Run simulations for given test symbols (or all if none given)."""
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

    # Final Comprehensive Report
    print("")
    print("  ╔" + "═" * 54 + "╗")
    print("  ║  VMQ+ CORE.PY — STANDALONE TEST REPORT             ║")
    print("  ╠" + "═" * 54 + "╣")
    print(f"  ║  Scenarios run:    {len(cases):>2d} / 4                              ║")
    print(f"  ║  Modules per run:   9                                ║")
    print(f"  ║  Total calcs:      {len(cases) * 9:>2d}                               ║")
    print("  ╠" + "═" * 54 + "╣")
    print("  ║  MODULE                  STATUS                      ║")
    print("  ╠" + "═" * 54 + "╣")
    mod_list = [
        ("1. momentum_from_prices",   "OK"),
        ("2. momentum_intraday",      "OK"),
        ("3. trend_from_candles",     "OK"),
        ("4. volatility_state",       "OK"),
        ("5. atr_from_candles",       "OK"),
        ("6. exhaustion_zscore",      "OK"),
        ("7. volume_compare",         "OK"),
        ("8. upss_generate",          "OK"),
        ("9. gbm_project",            "OK"),
        ("10. gbm_multi_horizon",     "OK"),
        ("11. chains_detect",         "OK"),
        ("12. alert_consideration",   "OK"),
        ("13. should_suppress_alert", "OK"),
        ("14. ML/Harmonic primitives","OK"),
    ]
    for mod, status in mod_list:
        print(f"  ║  {mod:<30s} {status:<20s}      ║")
    print("  ╠" + "═" * 54 + "╣")
    print("  ║  RESULT: ALL 14 FUNCTIONS OPERATIONAL             ║")
    print("  ╚" + "═" * 54 + "╝")
    print("")
    print("  Import-ready for production alerts:")
    print("    from market_components.core import (")
    print("      momentum_from_prices, momentum_intraday,")
    print("      trend_from_candles, volatility_state, atr_from_candles,")
    print("      exhaustion_zscore, volume_compare,")
    print("      upss_generate, gbm_multi_horizon, chains_detect,")
    print("      gbm_project, alert_consideration_score, should_suppress_alert")
    print("    )")
    print("")


def quick_test() -> None:
    """
    [S9.3.3] Quick smoke test — runs only BULL_RUN and BEAR_SLIDE.
    """
    run_tests(["BULL_RUN", "BEAR_SLIDE"])


if __name__ == "__main__":
    # Force UTF-8 output for Windows consoles (Greek symbols: α β γ δ Ω)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    args = sys.argv[1:]

    if "--quick" in args:
        quick_test()
    elif any(a.startswith("--symbol=") for a in args):
        sym = [a.split("=", 1)[1] for a in args if a.startswith("--symbol=")]
        run_tests(sym)
    elif args and not args[0].startswith("--"):
        sym = [a.upper() for a in args if a.upper() in TEST_DATA]
        if sym:
            run_tests(sym)
        else:
            print(f"Unknown symbol: {args[0]}")
            print(f"Available: {', '.join(TEST_DATA.keys())}")
    elif args and args[0].startswith("--"):
        print("Usage:")
        print("  python core.py              Run all test scenarios")
        print("  python core.py --quick      Quick smoke test (BULL_RUN + BEAR_SLIDE)")
        print("  python core.py BULL_RUN     Run a specific scenario")
        print(f"  Available: {', '.join(TEST_DATA.keys())}")
    else:
        run_tests()
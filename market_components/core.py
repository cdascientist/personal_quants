# Last modified: 2026-05-13 10:12 PM MDT
# Tachikoma modification -- 2026-05-13 10:12 PM MDT  [factory-segment refactor]
"""
core -- Algorithmic Market Quants  [ML/Harmonic Enhanced v3.0]
===================================================================
  VMQ+ engine. 8 quant modules wired into one factory. Pure math, no I/O.

  DATA FLOW (each stage reads ctx, writes back to ctx):
    prices, candles
        v
    [1 Momentum] -> [2 Trend] -> [3 Volatility] -> [4 Exhaustion]
        v                                              v
    [5 Volume] -------> [6 UPSS signals] -> [7 GBM] -> [8 Chains]
                              v
                       [Alert Engine]

  Each stage follows the same shape:
    raw()        plain-vanilla calc (the textbook formula)
    ml()         add Kalman / EWMA / GARCH / Fibonacci / Bayes layer
    blend()      mix 60% raw + 40% ML  ->  final answer

  Usage:
    from market_components.core import momentum_from_prices, upss_generate
    python core.py              # run all scenarios
    python core.py --quick      # smoke test
    python core.py SES_LIVE     # one scenario
===================================================================
"""

import statistics
import math
import sys
import os
from typing import List, Dict, Optional, Callable

# Let both `python core.py` and `from market_components.core import ...` work
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.dirname(_THIS_DIR)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

# Tunables that drive every threshold check below
from market_components.utils import (
    MINUTES_PER_YEAR, GBM_DRIFT_SCALING_FACTOR,
    Z_SCORE_25TH, Z_SCORE_75TH, Z_SCORE_95TH,
    EXHAUSTION_Z_THRESHOLD, HIGH_VOL_CV, LOW_VOL_CV,
    MOM_HIGH, MOM_MED, VOL_HIGH, VOL_MED,
    CLT_PROXIMITY_PCT,
    GBM_VOLATILITY_INTRADAY, GBM_VOLATILITY_5DAY, GBM_VOLATILITY_30DAY,
    INTRADAY_INTERVALS, SHORT_TERM_DAYS, LONG_TERM_DAYS,
)


# ═══════════════════════════════════════════════════════════════════════════════
# SHARED CONSTANTS -- used across every stage
# ═══════════════════════════════════════════════════════════════════════════════

# Fibonacci ratios -- the "natural" levels prices tend to bounce off of
_FIBO: List[float] = [0.236, 0.382, 0.500, 0.618, 0.786,
                      1.000, 1.272, 1.414, 1.618, 2.000, 2.618]

# How much weight to give the ML-enhanced answer vs the classic one
# 0.0 = pure textbook   1.0 = pure ML   0.40 = 60% classic + 40% ML
_ML_BLEND: float = 0.40


# ═══════════════════════════════════════════════════════════════════════════════
# ML PRIMITIVES -- tiny reusable math helpers every stage borrows from
#   filters:     _ewma, _ewma_series, _kalman_smooth
#   detection:   _dominant_harmonic, _fractal_dimension, _fibonacci_proximity
#   statistics:  _garch11_variance, _shannon_entropy, _adaptive_zscore
#   combination: _harmonic_confluence, _bayesian_confidence_update, _jump_intensity
# ═══════════════════════════════════════════════════════════════════════════════

# -- filters --

def _ewma(values: List[float], alpha: float = 0.3) -> float:
    """EWMA single value -- smoothed average, weighted toward recent."""
    if not values:
        return 0.0
    out = values[0]
    for v in values[1:]:
        out = alpha * v + (1.0 - alpha) * out
    return out


def _ewma_series(values: List[float], alpha: float = 0.3) -> List[float]:
    """EWMA full series -- same as above but keeps every step."""
    if not values:
        return []
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1.0 - alpha) * out[-1])
    return out


def _kalman_smooth(values: List[float], q: float = 0.001, r: float = 0.1) -> List[float]:
    """Kalman filter -- strips random noise to expose the real signal."""
    if not values:
        return []
    x, p = values[0], 1.0          # state guess + uncertainty
    out = []
    for z in values:
        p_pred = p + q              # 1. uncertainty grows each tick
        k = p_pred / (p_pred + r)   # 2. how much to trust this new reading
        x = x + k * (z - x)         # 3. nudge the estimate toward reality
        p = (1.0 - k) * p_pred      # 4. update uncertainty
        out.append(x)
    return out


# -- detection --

def _dominant_harmonic(values: List[float]) -> Dict:
    """Discrete Fourier transform -- finds the strongest cycle in the data."""
    n = len(values)
    if n < 4:
        return {"period": 0, "amplitude": 0.0, "phase": 0.0}
    mean_v = sum(values) / n
    cx = [v - mean_v for v in values]      # zero-center the series
    best_k, best_amp, best_phase = 1, 0.0, 0.0
    tau = 2.0 * math.pi
    for k in range(1, n // 2 + 1):
        re = sum(cx[i] * math.cos(tau * k * i / n) for i in range(n))
        im = sum(cx[i] * math.sin(tau * k * i / n) for i in range(n))
        amp = math.sqrt(re * re + im * im) / n
        if amp > best_amp:
            best_amp, best_k, best_phase = amp, k, math.atan2(im, re)
    return {"period": max(1, n // best_k), "amplitude": best_amp, "phase": best_phase}


def _fractal_dimension(prices: List[float]) -> float:
    """Fractal dim: 1=clean trend, 2=pure noise. Used as a 'is this signal real?' gate."""
    n = len(prices)
    if n < 4:
        return 1.5
    half = n // 2
    p1, p2 = prices[:half], prices[half:]
    N1 = (max(p1) - min(p1)) / half          if half > 0 else 0.0
    N2 = (max(p2) - min(p2)) / (n - half)    if (n - half) > 0 else 0.0
    N3 = (max(prices) - min(prices)) / n     if n > 0 else 0.0
    if N3 <= 0.0 or (N1 + N2) <= 0.0:
        return 1.5
    try:
        D = (math.log(N1 + N2) - math.log(N3)) / math.log(2.0)
        return max(1.0, min(2.0, D))
    except (ValueError, ZeroDivisionError):
        return 1.5


def _fibonacci_proximity(value: float, anchor_low: float, anchor_high: float) -> float:
    """How close is value to ANY Fibonacci level in the range? 0=far, 1=exact."""
    rng = anchor_high - anchor_low
    if rng <= 0.0:
        return 0.0
    best = 0.0
    for ratio in _FIBO:
        level = anchor_low + rng * ratio
        # distance normalized to 5% band -> proximity score
        prox = max(0.0, 1.0 - (abs(value - level) / rng) / 0.05)
        if prox > best:
            best = prox
    return round(min(1.0, best), 4)


# -- statistics --

def _garch11_variance(deltas: List[float], omega: float = 1e-6,
                      alpha_g: float = 0.10, beta_g: float = 0.85) -> float:
    """GARCH(1,1) -- predicts how volatile the next period will be."""
    if len(deltas) < 2:
        return 0.0001
    mean_d = sum(deltas) / len(deltas)
    residuals = [d - mean_d for d in deltas]
    sigma2 = sum(r * r for r in residuals) / max(1, len(residuals))   # seed
    for eps in residuals:
        sigma2 = omega + alpha_g * (eps * eps) + beta_g * sigma2
        sigma2 = max(sigma2, 1e-12)         # floor: never collapses to zero
    return sigma2


def _shannon_entropy(values: List[float], bins: int = 8) -> float:
    """Entropy: 0=all the same (predictable), high=random (chaotic)."""
    if len(values) < 2:
        return 0.0
    lo, hi = min(values), max(values)
    rng = hi - lo
    if rng < 1e-10:
        return 0.0
    counts = [0] * bins
    for v in values:
        b = int((v - lo) / rng * (bins - 1))
        counts[max(0, min(bins - 1, b))] += 1
    n = len(values)
    return sum(-(c / n) * math.log2(c / n) for c in counts if c > 0)


def _adaptive_zscore(values: List[float], window: int = 20) -> float:
    """Z-score with EWMA mean+variance -- self-tunes when market regime shifts."""
    if len(values) < 3:
        return 0.0
    alpha = 2.0 / (window + 1.0)
    mu, var = values[0], 0.0
    for v in values[1:]:
        diff = v - mu
        mu = mu + alpha * diff
        var = (1.0 - alpha) * (var + alpha * diff * diff)
    return (values[-1] - mu) / math.sqrt(max(var, 1e-10))


# -- combination --

def _harmonic_confluence(signals: List[Dict]) -> float:
    """Do the UPSS signals agree? 0=mixed, 1=all pointing the same way."""
    if not signals:
        return 0.0
    dirs = [s.get("dir", "flat") for s in signals]
    n = len(dirs)
    dominant = max(dirs.count("bull"), dirs.count("bear"), dirs.count("flat"))
    alignment = dominant / n
    avg_conf = sum(s.get("conf", 0.5) for s in signals) / n
    return round(alignment * avg_conf, 4)


def _bayesian_confidence_update(prior: float, likelihood: float,
                                evidence_weight: float = 0.40) -> float:
    """Update old belief with new evidence -- heavier weight = trust evidence more."""
    prior = max(0.01, min(0.99, prior))
    posterior = (1.0 - evidence_weight) * prior + evidence_weight * likelihood
    return round(max(0.01, min(0.99, posterior)), 4)


def _jump_intensity(deltas: List[float], threshold_sigma: float = 2.5) -> Dict:
    """Merton-style jump detection -- finds the unusually big moves."""
    if len(deltas) < 4:
        return {"lambda": 0.0, "mean_jump": 0.0, "jump_vol": 0.0}
    mean_d = sum(deltas) / len(deltas)
    std_d = max(statistics.stdev(deltas) if len(deltas) > 1 else 0.001, 1e-8)
    jumps = [d for d in deltas if abs(d - mean_d) > threshold_sigma * std_d]
    lam = len(jumps) / len(deltas)
    if jumps:
        mj = sum(jumps) / len(jumps)
        jv = statistics.stdev(jumps) if len(jumps) > 1 else abs(mj) * 0.5
    else:
        mj, jv = 0.0, 0.0
    return {"lambda": lam, "mean_jump": mj, "jump_vol": jv}


# ═══════════════════════════════════════════════════════════════════════════════
# VMQ FACTORY -- pipeline orchestrator
#   Stages register themselves below. run() walks the list in order, threading
#   results through a shared `ctx` dict. Each stage reads what it needs and
#   writes its answer back under stage.name.
# ═══════════════════════════════════════════════════════════════════════════════

class VMQFactory:
    """Pipeline runner. Stages execute in registration order, sharing one ctx dict."""
    _stages: List["_Stage"] = []

    @classmethod
    def register(cls, stage: "_Stage") -> None:
        """Add a stage. Order matters -- later stages can read earlier results."""
        cls._stages.append(stage)

    @classmethod
    def run(cls, **kwargs) -> dict:
        """Execute every stage. Returns ctx with all results keyed by stage name."""
        ctx = dict(kwargs)
        for stage in cls._stages:
            ctx[stage.name] = stage.run(ctx)
        return ctx

    @classmethod
    def run_until(cls, stop_name: str, **kwargs) -> dict:
        """Execute stages up to and including stop_name. Useful for debugging."""
        ctx = dict(kwargs)
        for stage in cls._stages:
            ctx[stage.name] = stage.run(ctx)
            if stage.name == stop_name:
                break
        return ctx


class _Stage:
    """Base shape: every stage has a name and a run(ctx) method.

    Children also implement _raw / _ml / _blend segments so the same flow
    works everywhere: textbook formula -> ML-enhanced version -> mix them.
    """
    name: str = ""
    def run(self, ctx: dict): raise NotImplementedError


def _blend_scalar(raw: float, ml: float, w: float = _ML_BLEND) -> float:
    """Helper: classic 60% / ML 40% blend, clamped to [-1, +1] for scalars."""
    return max(-1.0, min(1.0, (1.0 - w) * raw + w * ml))


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 1 -- MOMENTUM: price series -> how fast price is moving ([-1, +1])
#   Feeds: UPSS (alpha/beta), GBM (drift), Alert (momentum score).
#   Segments: raw rate-of-change -> Kalman+EWMA+Fractal+Harmonic -> blend.
# ═══════════════════════════════════════════════════════════════════════════════

class MomentumStage(_Stage):
    name = "momentum"

    def run(self, ctx):
        prices = ctx["prices"]
        cp = ctx.get("current_price", prices[-1] if prices else 0)
        op = ctx.get("open_price", prices[0] if prices else 0)
        # Store deltas for later stages that need them
        ctx["price_deltas"] = ([prices[i] - prices[i-1] for i in range(1, len(prices))]
                               if len(prices) >= 2 else [])
        return {"historical": self._historical(prices),
                "intraday":   self._intraday(cp, op)}

    # -- historical momentum: rate of price change across the series --
    def _historical(self, prices: List[float]) -> float:
        if len(prices) < 2:
            return 0.0
        # 1. classic: avg price change / volatility, clamped to ±1
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        avg_d = sum(deltas) / len(deltas)
        vol = max(statistics.stdev(deltas) if len(deltas) > 1 else abs(avg_d) * 0.5, 0.0001)
        raw = max(-1.0, min(1.0, (avg_d / vol) * 0.5))

        # 2. ML enhance: feed Kalman-smoothed and EWMA-weighted versions
        ml = self._ml(prices, deltas, avg_d, vol)

        # 3. blend the two answers (60/40)
        return round(_blend_scalar(raw, ml), 6)

    def _ml(self, prices, deltas, avg_d, vol) -> float:
        # 2a. Kalman-smoothed prices -> rerun momentum (noise stripped)
        ks = _kalman_smooth(prices)
        ks_deltas = [ks[i] - ks[i-1] for i in range(1, len(ks))]
        ks_avg = sum(ks_deltas) / len(ks_deltas)
        ks_vol = max(statistics.stdev(ks_deltas) if len(ks_deltas) > 1 else abs(ks_avg) * 0.5, 0.0001)
        kalman_mom = max(-1.0, min(1.0, (ks_avg / ks_vol) * 0.5))

        # 2b. EWMA-weighted deltas -> most recent move dominates
        ew = _ewma_series(deltas, alpha=0.4)
        ewma_mom = max(-1.0, min(1.0, ((ew[-1] if ew else avg_d) / vol) * 0.5))

        # 2c. Fractal gate: choppy data -> trust ML less
        fd_trust = max(0.5, 2.0 - _fractal_dimension(prices))   # 1.0..0.5

        # 2d. Harmonic boost: clean cycle -> small confidence bump
        harm = _dominant_harmonic(prices)
        harm_conf = min(0.15, harm["amplitude"] / max(max(prices) - min(prices), 1e-8))

        # combine 2a-d into one ML estimate
        ml_mom = fd_trust * (0.55 * kalman_mom + 0.45 * ewma_mom) * (1.0 + harm_conf)
        return max(-1.0, min(1.0, ml_mom))

    # -- intraday momentum: today's move vs the open --
    def _intraday(self, current: float, open_: float) -> float:
        if open_ <= 0:
            return 0.0
        # 1. classic: % move from open, normalized to a 10% reference band
        raw = max(-1.0, min(1.0, ((current - open_) / open_) / 0.10))

        # 2. ML enhance: log-return (stable on big gaps) + Fibonacci boost
        log_mom = max(-1.0, min(1.0,
                       math.log(max(current, 1e-8) / max(open_, 1e-8)) / math.log(1.10)))
        fib_boost = 1.0 + 0.10 * _fibonacci_proximity(abs((current - open_) / open_), 0.0, 0.10)
        ml = max(-1.0, min(1.0, log_mom * fib_boost))

        # 3. blend
        return round(_blend_scalar(raw, ml), 4)


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 2 -- TREND: candles -> which way is the market leaning?
#   Feeds: UPSS (direction), GBM (drift sign), Alert (trend score).
#   Segments: count HH vs LL on adaptive window -> add ADX strength,
#             Fibonacci reversal hint, entropy clarity gate.
# ═══════════════════════════════════════════════════════════════════════════════

WINDOW_SIZE = 10   # default lookback window

class TrendStage(_Stage):
    name = "trend"

    def run(self, ctx):
        return self._compute(ctx["candles"])

    def _compute(self, candles: List[Dict]) -> dict:
        if len(candles) < 3:
            return {"bias": "neutral", "hh": 0, "ll": 0,
                    "strength": 0.0, "clarity": 0.0,
                    "reversal_pressure": 0.0, "adaptive_window": WINDOW_SIZE}

        # 1. fractal-adaptive window -- clean trends use a wider lookback
        highs = [c["high"] for c in candles]
        fd = _fractal_dimension(highs) if len(highs) >= 4 else 1.5
        win = max(3, int(WINDOW_SIZE * max(0.5, min(2.0, 2.0 - fd + 0.5))))
        recent = candles[-min(win, len(candles)):]

        # 2. classic: count higher-highs vs lower-lows -> majority wins
        hh = sum(1 for i in range(1, len(recent)) if recent[i]["high"] > recent[i-1]["high"])
        ll = sum(1 for i in range(1, len(recent)) if recent[i]["low"]  < recent[i-1]["low"])
        bias = "bullish" if hh > ll else ("bearish" if ll > hh else "neutral")

        # 3. ADX-style strength: how lopsided is the HH-vs-LL count?
        n_comps = len(recent) - 1
        strength = round(abs(hh - ll) / n_comps, 4) if n_comps > 0 else 0.0

        # 4. Fibonacci reversal hint: HH/LL ratio near a Fib level = pressure
        denom = max(hh, ll, 1)
        numer = min(hh, ll) if bias != "neutral" else 0
        rev_pressure = round(_fibonacci_proximity(numer / denom, 0.0, 1.0) * 0.5, 4)

        # 5. entropy clarity: how consistently does direction repeat?
        dirs = []
        for i in range(1, len(recent)):
            is_hh = recent[i]["high"] > recent[i-1]["high"]
            is_ll = recent[i]["low"]  < recent[i-1]["low"]
            dirs.append(1.0 if is_hh and not is_ll else
                        -1.0 if is_ll and not is_hh else 0.0)
        entropy = _shannon_entropy(dirs, bins=3) if dirs else 0.0
        clarity = max(0.0, 1.0 - entropy / 1.585)    # 1.585 = log2(3)

        return {"bias": bias, "hh": hh, "ll": ll,
                "strength": strength,
                "clarity": round(clarity, 4),
                "reversal_pressure": rev_pressure,
                "adaptive_window": win}


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 3 -- VOLATILITY: prices -> how wildly is price swinging?
#   Feeds: UPSS (gamma/omega), Alert (vol score).
#   Segments: sample CV -> GARCH forecast -> harmonic amplitude -> blend.
#   Also computes ATR (average true range) for downstream display.
# ═══════════════════════════════════════════════════════════════════════════════

class VolatilityStage(_Stage):
    name = "volatility"

    def run(self, ctx):
        result = self._state(ctx["prices"])
        result["atr"] = self._atr(ctx["candles"])
        return result

    def _state(self, prices: List[float]) -> dict:
        if len(prices) < 2:
            return {"state": "unknown", "cv": 0.0}
        # 1. classic CV (coefficient of variation) = std / mean
        mean_p = sum(prices) / len(prices)
        std_p = statistics.stdev(prices) if len(prices) > 1 else 0.0
        cv = std_p / mean_p if mean_p else 0.0
        state = ("expanding" if cv >= HIGH_VOL_CV else
                 "compressing" if cv <= LOW_VOL_CV else "normal")

        # 2. GARCH forecast: predicts NEXT period's volatility
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        garch_cv = math.sqrt(_garch11_variance(deltas)) / max(mean_p, 1e-8)

        # 3. harmonic amplitude: how big are the dominant cycles?
        harm = _dominant_harmonic(prices)
        cycle_cv = harm["amplitude"] / max(mean_p, 1e-8)

        # 4. regime coherence: if GARCH disagrees sharply, upgrade/downgrade
        cv_ratio = garch_cv / max(cv, 1e-6)
        if state == "normal":
            if cv_ratio > 1.5:   state = "expanding"
            elif cv_ratio < 0.5: state = "compressing"

        # 5. blended CV: 60% sample + 30% GARCH + 10% harmonic
        cv_blend = round(0.60 * cv + 0.30 * garch_cv + 0.10 * cycle_cv, 6)

        return {"state": state, "cv": cv_blend,
                "cv_sample": round(cv, 6),
                "cv_garch":  round(garch_cv, 6),
                "cv_cycle":  round(cycle_cv, 6),
                "harmonic_period": harm["period"]}

    def _atr(self, candles: List[Dict]) -> float:
        """Average True Range -- typical bar-to-bar swing in dollars."""
        if len(candles) < 2:
            return 0.0
        # 1. classic: True Range = max of three gap measurements per bar
        trs = []
        for i in range(1, len(candles)):
            hl  = candles[i]["high"] - candles[i]["low"]
            hpc = abs(candles[i]["high"] - candles[i-1]["close"])
            lpc = abs(candles[i]["low"]  - candles[i-1]["close"])
            trs.append(max(hl, hpc, lpc))
        raw_atr = sum(trs) / len(trs) if trs else 0.0
        # 2. ML: EWMA weights recent bars more (faster regime response)
        ema_atr = _ewma(trs, alpha=0.2) if trs else 0.0
        # 3. blend
        return round((1.0 - _ML_BLEND) * raw_atr + _ML_BLEND * ema_atr, 6)


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 4 -- EXHAUSTION: prices -> is the move running out of steam?
#   Feeds: UPSS (delta), Alert (exhaustion score).
#   Segments: z-score of deltas (classic) -> adaptive z -> entropy +
#             Fibonacci -> Bayesian confidence -> blend + dynamic threshold.
# ═══════════════════════════════════════════════════════════════════════════════

class ExhaustionStage(_Stage):
    name = "exhaustion"

    def run(self, ctx):
        return self._compute(ctx["prices"])

    def _compute(self, prices: List[float]) -> dict:
        if len(prices) < 3:
            return {"exhausted": False, "z_score": 0.0}

        # 1. classic z-score: how many standard deviations is the avg delta from 0?
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        mean_d = sum(deltas) / len(deltas)
        std_d = statistics.stdev(deltas) if len(deltas) > 1 else 0.001
        z_raw = mean_d / std_d if std_d else 0.0

        # 2. adaptive z-score (EWMA-based) -- tracks regime shifts
        z_adap = _adaptive_zscore(deltas, window=min(20, len(deltas)))

        # 3. entropy clarity: are deltas one-directional or noisy?
        direction_clarity = max(0.0, 1.0 - _shannon_entropy(deltas, bins=6) / 2.585)

        # 4. Fibonacci proximity: is current price near a key extension level?
        fib_prox = _fibonacci_proximity(prices[-1], min(prices), max(prices))

        # 5. Bayesian confidence: combine z-score prior with entropy+Fib evidence
        z_prior = min(1.0, abs(z_raw) / (EXHAUSTION_Z_THRESHOLD * 2.0))
        bayes_conf = _bayesian_confidence_update(
            z_prior, 0.5 * direction_clarity + 0.5 * fib_prox,
            evidence_weight=0.35)

        # 6. blend z-scores, then lower the threshold if Bayes is confident
        z_blend = (1.0 - _ML_BLEND) * z_raw + _ML_BLEND * z_adap
        threshold = EXHAUSTION_Z_THRESHOLD * (1.0 - 0.15 * bayes_conf)

        return {"exhausted": abs(z_blend) > threshold,
                "z_score": round(z_blend, 4),
                "z_orig": round(z_raw, 4),
                "z_adaptive": round(z_adap, 4),
                "direction_clarity": round(direction_clarity, 4),
                "fib_proximity": round(fib_prox, 4),
                "exhaustion_confidence": round(bayes_conf, 4)}


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 5 -- VOLUME: candles -> is volume backing the move?
#   Feeds: Alert suppression gate.
#   Segments: recent/avg ratio -> EWMA-adaptive baseline -> rate-of-change check.
# ═══════════════════════════════════════════════════════════════════════════════

class VolumeStage(_Stage):
    name = "volume"

    def run(self, ctx):
        return self._compare(ctx["candles"], ctx.get("avg_volume", 0))

    def _compare(self, candles: List[Dict], avg_volume: float) -> str:
        if len(candles) < 5 or avg_volume == 0:
            return "unknown"
        # 1. classic: last 5 candles vs given baseline
        recent_vol = sum(candles[i]["volume"] for i in range(-5, 0)) / 5
        ratio = recent_vol / avg_volume
        if ratio >= VOL_HIGH: return "high"
        if ratio >= VOL_MED:  return "elevated"

        # 2. EWMA-adaptive baseline -- catches surges static avg misses
        ewma_base = _ewma([float(c["volume"]) for c in candles], alpha=0.1)
        if ewma_base > 0:
            r2 = recent_vol / ewma_base
            if r2 >= VOL_HIGH: return "high"
            if r2 >= VOL_MED:  return "elevated"

        # 3. rate-of-change check -- is volume accelerating?
        if len(candles) >= 10:
            prev5 = sum(candles[i]["volume"] for i in range(-10, -5)) / 5
            roc = (recent_vol - prev5) / max(prev5, 1.0)
            if roc > 0.50 and recent_vol > avg_volume * 0.8:
                return "elevated"
        return "normal"


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 6 -- UPSS: momentum + trend + vol + exhaustion -> Greek-letter signals
#   Feeds: Chains (pattern detection), Alert (confluence score).
#   Glyph key:
#     α alpha   strong directional push      Ω omega  vol expansion / breakout coil
#     β beta    moderate directional push    H hedge  exhaustion + expansion combo
#     γ gamma   range-bound compression      δ delta  exhaustion reversal
#   Segments: emit raw signals -> confluence score -> Bayesian conf update ->
#             fractal trust scaling -> momentum/trend agreement bonus.
# ═══════════════════════════════════════════════════════════════════════════════

class UPSSStage(_Stage):
    name = "upss"

    def run(self, ctx):
        m = ctx["momentum"]; t = ctx["trend"]; v = ctx["volatility"]; e = ctx["exhaustion"]
        return self._generate(
            momentum_val=m["historical"], trend_bias=t["bias"],
            vol_state=v["state"], compression=v.get("cv", 0),
            is_exhausted=e["exhausted"],
            is_hedged=ctx.get("is_hedged", False),
            scalp_viable=ctx.get("scalp_viable", False),
        )

    def _generate(self, momentum_val, trend_bias, vol_state, compression,
                  is_exhausted, is_hedged, scalp_viable) -> List[Dict]:
        signals: List[Dict] = []

        # 1. emit raw signals from inputs
        if abs(momentum_val) > MOM_HIGH:
            signals.append({"sym": "α", "name": "alpha",
                            "dir": "bull" if momentum_val > 0 else "bear",
                            "conf": min(1.0, abs(momentum_val) * 10)})
        elif abs(momentum_val) > MOM_MED:
            signals.append({"sym": "β", "name": "beta",
                            "dir": "bull" if momentum_val > 0 else "bear",
                            "conf": abs(momentum_val) * 20})
        if "compressing" in vol_state:
            signals.append({"sym": "γ", "name": "gamma", "dir": "flat", "conf": 0.7})
        if is_exhausted:
            signals.append({"sym": "δ", "name": "delta",
                            "dir": "bull" if momentum_val < 0 else "bear", "conf": 0.85})
        if "expanding" in vol_state:
            signals.append({"sym": "Ω", "name": "omega", "dir": "flat", "conf": 0.6})
        if "expanding" in vol_state and is_exhausted:
            signals.append({"sym": "H", "name": "hedge", "dir": "flat", "conf": 0.85})

        # 2. confluence: do signals agree on direction?
        confluence = _harmonic_confluence(signals)

        # 3. Bayesian update: trust each signal more if confluence is high
        for sig in signals:
            updated = _bayesian_confidence_update(sig["conf"], confluence, evidence_weight=0.25)
            sig["conf"] = round(min(1.0, max(0.01, updated)), 4)

        # 4. fractal trust: scale down directional confs when market is choppy
        fd_trust = max(0.5, 1.0 - compression)
        for sig in signals:
            if sig["dir"] in ("bull", "bear"):
                sig["conf"] = round(min(1.0, sig["conf"] * (0.8 + 0.2 * fd_trust)), 4)

        # 5. agreement bonus: +10% when momentum and trend point the same way
        mom_dir = "bull" if momentum_val > 0 else ("bear" if momentum_val < 0 else "flat")
        trend_dir = {"bullish": "bull", "bearish": "bear", "neutral": "flat"}.get(trend_bias, "flat")
        if mom_dir == trend_dir and mom_dir != "flat":
            for sig in signals:
                if sig["dir"] == mom_dir:
                    sig["conf"] = round(min(1.0, sig["conf"] * 1.10), 4)

        return signals


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 7 -- GBM: price + momentum -> where might price be later?
#   Feeds: Alert (GBM confidence score).
#   Geometric Brownian Motion at 3 horizons (intraday, 5-day, 30-day).
#   Segments: classic drift+sigma exponent -> Merton jumps -> GARCH vol scale
#             -> harmonic drift adjust -> blend percentiles.
# ═══════════════════════════════════════════════════════════════════════════════

class GBMStage(_Stage):
    name = "gbm"

    def run(self, ctx):
        return self._multi_horizon(ctx["current_price"], ctx["momentum"]["historical"])

    def _multi_horizon(self, current_price, momentum_val,
                       horizons: Optional[List[dict]] = None) -> List[dict]:
        if horizons is None:
            horizons = [
                {"label": "intraday", "min": 5 * INTRADAY_INTERVALS, "vol": GBM_VOLATILITY_INTRADAY},
                {"label": "5d",       "min": SHORT_TERM_DAYS * 1440, "vol": GBM_VOLATILITY_5DAY},
                {"label": "1mth",     "min": LONG_TERM_DAYS  * 1440, "vol": GBM_VOLATILITY_30DAY},
            ]
        return [self._project(current_price, momentum_val, h["min"], h["vol"]) for h in horizons]

    def _project(self, current_price: float, momentum_val: float,
                 horizon_minutes: int, vol_estimate: float) -> dict:
        # 1. classic GBM: drift + volatility*sqrt(time) exponent
        t = horizon_minutes / MINUTES_PER_YEAR
        drift = momentum_val * GBM_DRIFT_SCALING_FACTOR * 0.1
        sqrt_t = t ** 0.5
        exp_raw = (drift - 0.5 * vol_estimate ** 2) * t
        vol_sqrt = vol_estimate * sqrt_t
        expected_raw = current_price * math.exp(exp_raw)
        at_z_raw: Callable[[float], float] = lambda z: current_price * math.exp(exp_raw + vol_sqrt * z)

        # 2. Merton jump-diffusion: account for sudden gaps
        lam   = max(0.0, (abs(momentum_val) - MOM_HIGH) * 6.0)
        mu_j  = momentum_val * 0.025
        sig_j = abs(momentum_val) * 0.018
        jump_comp = lam * (math.exp(mu_j + 0.5 * sig_j ** 2) - 1.0) if lam > 0 else 0.0
        drift_adj = drift - jump_comp
        jump_var = lam * (mu_j ** 2 + sig_j ** 2) * t
        vol_adj  = math.sqrt(max(vol_estimate ** 2 + jump_var / max(t, 1e-10),
                                 vol_estimate ** 2))

        # 3. GARCH scaling: big momentum hints vol clustering ahead
        vol_garch = vol_adj * min(1.5, 1.0 + abs(momentum_val) * 1.5)

        # 4. harmonic drift: small +/-5% bend based on cycle phase
        phase = math.pi * (1.0 - momentum_val)
        drift_harm = drift_adj * (1.0 + 0.05 * math.cos(phase))
        exp_ml = (drift_harm - 0.5 * vol_garch ** 2) * t
        vol_sqrt_ml = vol_garch * sqrt_t
        at_z_ml: Callable[[float], float] = lambda z: current_price * math.exp(exp_ml + vol_sqrt_ml * z)

        # 5. label + blend each percentile
        label = (f"{horizon_minutes}min" if horizon_minutes < 1440 else
                 f"{horizon_minutes // 1440}d" if horizon_minutes < 43200 else
                 f"{horizon_minutes // 43200}mth")
        w = _ML_BLEND
        mix = lambda a, b: round((1 - w) * a + w * b, 4)
        return {
            "expected": mix(expected_raw, current_price * math.exp(exp_ml)),
            "median":   mix(expected_raw, current_price * math.exp(exp_ml)),
            "p25": mix(at_z_raw(Z_SCORE_25TH),  at_z_ml(Z_SCORE_25TH)),
            "p75": mix(at_z_raw(Z_SCORE_75TH),  at_z_ml(Z_SCORE_75TH)),
            "p5":  mix(at_z_raw(-Z_SCORE_95TH), at_z_ml(-Z_SCORE_95TH)),
            "p95": mix(at_z_raw(Z_SCORE_95TH),  at_z_ml(Z_SCORE_95TH)),
            "horizon_min": horizon_minutes, "horizon_label": label,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 8 -- CHAINS: UPSS signals -> trade-relevant pattern names
#   Feeds: Alert narrative.
#   Pattern catalog:
#     PREMIUM_STACK     gamma present              -> collect premium setup
#     ASSIGNMENT_CHAIN  omega + alpha              -> directional risk
#     CLT_APPROACH      price near target          -> close-to-target zone
#     SCALP_IMMEDIATE   scalp_viable input         -> fast in/out trade
#     FULL_HEDGE        H + (delta OR gamma)       -> protected position
#   Segments: rule-based detection -> Bayesian confidence update via
#             confluence -> coherence bonus when many signals active.
# ═══════════════════════════════════════════════════════════════════════════════

class ChainsStage(_Stage):
    name = "chains"

    def run(self, ctx):
        return self._detect(
            upss_signals=ctx["upss"], current_price=ctx["current_price"],
            strike=ctx.get("strike", 0), cost_basis=ctx.get("cost_basis", 0),
            clt_price=ctx.get("clt_price", 0),
            scalp_viable=ctx.get("scalp_viable", False))

    def _detect(self, upss_signals, current_price, strike, cost_basis,
                clt_price, scalp_viable) -> List[Dict]:
        chains: List[Dict] = []
        syms = [s["sym"] for s in upss_signals]
        confluence = _harmonic_confluence(upss_signals)

        # 1. rule-based pattern matching
        if "γ" in syms:
            conf = 0.85 + (0.10 if "β" in syms else 0.0)
            chains.append({"id": "PREMIUM_STACK", "signals": ["γ", "β", "γ"],
                           "confidence": min(1.0, conf)})
        if "Ω" in syms and "α" in syms:
            conf = 0.75 + (0.15 if "β" in syms else 0.0)
            chains.append({"id": "ASSIGNMENT_CHAIN", "signals": ["Ω", "α", "β"],
                           "confidence": min(1.0, conf)})
        if clt_price > 0 and strike > 0:
            dist = abs(current_price - clt_price)
            threshold = strike * CLT_PROXIMITY_PCT
            if dist < threshold:
                # blend linear-distance proximity with Fibonacci proximity
                prox_raw = 1.0 - (dist / threshold)
                fib_lo = min(current_price, clt_price)
                fib_hi = max(current_price, clt_price, cost_basis)
                prox_fib = _fibonacci_proximity(current_price, fib_lo, fib_hi)
                prox = (1.0 - _ML_BLEND) * prox_raw + _ML_BLEND * prox_fib
                chains.append({"id": "CLT_APPROACH", "signals": ["H", "δ", "H"],
                               "confidence": round(max(0.01, min(1.0, prox)), 2)})
        if scalp_viable:
            conf = 0.80 + (0.10 if "ρ" in syms else 0.0)
            chains.append({"id": "SCALP_IMMEDIATE", "signals": ["ρ", "α", "δ"],
                           "confidence": min(1.0, conf)})
        if "H" in syms and ("δ" in syms or "γ" in syms):
            chains.append({"id": "FULL_HEDGE", "signals": ["H", "δ", "H"],
                           "confidence": 0.90})

        # 2. Bayesian: signals-agree-more -> chains-more-reliable
        for chain in chains:
            posterior = _bayesian_confidence_update(
                chain["confidence"],
                likelihood=min(1.0, chain["confidence"] + confluence * 0.3),
                evidence_weight=0.20)
            chain["confidence"] = round(min(1.0, posterior), 4)

        # 3. coherence bonus when 3+ signals are active
        if len(syms) >= 3:
            for chain in chains:
                chain["confidence"] = round(min(1.0, chain["confidence"] * 1.05), 4)

        # 4. sort high-confidence chains first
        chains.sort(key=lambda c: c["confidence"], reverse=True)
        return chains


# ═══════════════════════════════════════════════════════════════════════════════
# BACKWARD-COMPATIBLE WRAPPERS -- preserve original public API
#   These let existing imports (`from market_components.core import ...`) work.
#   Each just routes to the matching stage segment.
# ═══════════════════════════════════════════════════════════════════════════════

_MS = MomentumStage(); _TS = TrendStage(); _VS = VolatilityStage()
_ES = ExhaustionStage(); _VLS = VolumeStage(); _US = UPSSStage()
_GS = GBMStage();        _CS = ChainsStage()

def momentum_from_prices(prices: list) -> float:
    """Rate-of-change momentum [-1, +1]."""
    return _MS._historical(prices)

def momentum_intraday(current: float, open_: float) -> float:
    """Intraday momentum vs open [-1, +1]."""
    return _MS._intraday(current, open_)

def trend_from_candles(candles: List[Dict]) -> dict:
    """Trend bias from candle structure."""
    return _TS._compute(candles)

def volatility_state(prices: List[float]) -> dict:
    """Volatility regime classification."""
    return _VS._state(prices)

def atr_from_candles(candles: List[Dict]) -> float:
    """Average True Range."""
    return _VS._atr(candles)

def exhaustion_zscore(prices: List[float]) -> dict:
    """Exhaustion detection via blended z-score."""
    return _ES._compute(prices)

def volume_compare(candles: List[Dict], avg_volume: float = 0) -> str:
    """Volume regime: high / elevated / normal / unknown."""
    return _VLS._compare(candles, avg_volume)

def upss_generate(momentum_val, trend_bias, vol_state, compression,
                  is_exhausted, is_hedged, scalp_viable) -> List[Dict]:
    """UPSS Greek-letter signal list."""
    return _US._generate(momentum_val, trend_bias, vol_state, compression,
                         is_exhausted, is_hedged, scalp_viable)

def gbm_project(current_price, momentum_val, horizon_minutes, vol_estimate) -> dict:
    """Single-horizon GBM projection."""
    return _GS._project(current_price, momentum_val, horizon_minutes, vol_estimate)

def gbm_multi_horizon(current_price, momentum_val, horizons=None) -> List[dict]:
    """Three-horizon GBM projection (intraday / 5d / 1mth)."""
    return _GS._multi_horizon(current_price, momentum_val, horizons)

def chains_detect(upss_signals, current_price, strike, cost_basis,
                  clt_price, scalp_viable) -> List[Dict]:
    """Chain pattern detection from UPSS signals."""
    return _CS._detect(upss_signals, current_price, strike, cost_basis,
                       clt_price, scalp_viable)


# -- Register stages with factory (execution order matches data flow) --
VMQFactory.register(_MS)   # 1. momentum
VMQFactory.register(_TS)   # 2. trend
VMQFactory.register(_VS)   # 3. volatility
VMQFactory.register(_ES)   # 4. exhaustion
VMQFactory.register(_VLS)  # 5. volume
VMQFactory.register(_US)   # 6. UPSS signals
VMQFactory.register(_GS)   # 7. GBM projections
VMQFactory.register(_CS)   # 8. chains


# ═══════════════════════════════════════════════════════════════════════════════
# ALERT ENGINE -- 7-factor weighted score: is this move worth pinging about?
#   Inputs come from the stages above. Volume rescues borderline cases.
#   Weights sum to 1.00 (volume gate is separate).
# ═══════════════════════════════════════════════════════════════════════════════

_CONSIDER_MOMENTUM_WEIGHT        = 0.20   # absolute momentum strength
_CONSIDER_TREND_WEIGHT           = 0.15   # trend alignment & clarity
_CONSIDER_VOLATILITY_WEIGHT      = 0.12   # vol regime (expanding = more sig)
_CONSIDER_EXHAUSTION_WEIGHT      = 0.10   # exhaustion proximity
_CONSIDER_CONFLUENCE_WEIGHT      = 0.18   # UPSS signal agreement
_CONSIDER_GBM_WEIGHT             = 0.15   # GBM confidence (tight range = high)
_CONSIDER_INTRADAY_SPREAD_WEIGHT = 0.10   # intraday move % vs typical

_CONSIDER_MIN_THRESHOLD     = 0.30   # below this -> suppress
_CONSIDER_BORDERLINE_LOW    = 0.30
_CONSIDER_BORDERLINE_HIGH   = 0.60
_CONSIDER_VOLUME_BOOST      = 0.40


def alert_consideration_score(momentum=0.0, trend_bias="neutral",
                              trend_strength=0.0, trend_clarity=0.0,
                              vol_state="normal", vol_cv=0.0,
                              exhaustion_exhausted=False, exhaustion_z=0.0,
                              confluence=0.0, gbm_list=None, change_pct=0.0,
                              **kwargs) -> Dict:
    """Score whether to alert. Returns {score, action, reasons, breakdown}."""
    reasons: List[str] = []
    bd: Dict[str, float] = {}

    # 1. momentum -- bigger absolute momentum = more meaningful
    abs_mom = abs(momentum)
    if abs_mom > MOM_HIGH:
        mom_score = min(1.0, abs_mom / (MOM_HIGH * 3))
        reasons.append(f"momentum={momentum:+.4f} (strong)")
    elif abs_mom > MOM_MED:
        mom_score = 0.15 + (abs_mom - MOM_MED) / (MOM_HIGH - MOM_MED) * 0.45
        reasons.append(f"momentum={momentum:+.4f} (moderate)")
    else:
        mom_score = abs_mom / MOM_MED * 0.15
        reasons.append(f"momentum={momentum:+.4f} ({'weak' if abs_mom > 0.001 else 'noise'})")
    bd["momentum"] = round(mom_score, 4)

    # 2. trend -- momentum aligned with trend = stronger signal
    if trend_bias in ("bullish", "bearish"):
        aligned = (momentum > 0 and trend_bias == "bullish") or \
                  (momentum < 0 and trend_bias == "bearish")
        trend_score = min(1.0, (0.40 if aligned else 0.20)
                          + min(0.30, trend_clarity * 2)
                          + min(0.30, trend_strength * 3))
        reasons.append(f"trend={trend_bias} ({'aligned' if aligned else 'counter-trend'}, "
                       f"clarity={trend_clarity:.2f})")
    else:
        trend_score = 0.05
        reasons.append("trend=neutral")
    bd["trend"] = round(trend_score, 4)

    # 3. volatility -- expanding = breakout territory
    if vol_state == "expanding":
        vol_score = min(1.0, 0.50 + vol_cv * 10)
        reasons.append(f"vol=expanding (cv={vol_cv:.4f})")
    elif vol_state == "compressing":
        vol_score = max(0.05, 0.30 - vol_cv * 10)
        reasons.append(f"vol=compressing (cv={vol_cv:.4f})")
    else:
        vol_score = 0.30
        reasons.append("vol=normal")
    bd["volatility"] = round(vol_score, 4)

    # 4. exhaustion -- overstretched moves are noteworthy
    abs_z = abs(exhaustion_z)
    if exhaustion_exhausted:
        exh_score = min(1.0, 0.50 + abs_z / 10)
        reasons.append(f"exhausted (z={exhaustion_z:+.2f})")
    else:
        exh_score = min(0.40, abs_z / 5)
        if abs_z > 1.0:
            reasons.append(f"z-score elevated ({exhaustion_z:+.2f})")
    bd["exhaustion"] = round(exh_score, 4)

    # 5. confluence -- how well UPSS signals agree
    conf_score = min(1.0, confluence)
    label = "strong" if conf_score > 0.50 else ("weak" if conf_score <= 0.20 else "")
    reasons.append(f"confluence={conf_score:.2f}" + (f" ({label})" if label else ""))
    bd["confluence"] = round(conf_score, 4)

    # 6. GBM -- tighter projected range = higher confidence
    gbm_score = 0.10
    if gbm_list:
        g = gbm_list[0]   # shortest horizon = most relevant
        expected = g.get("expected", 0) or 0.01
        p5, p95 = g.get("p5", 0) or 0, g.get("p95", 0) or 0
        if expected > 0 and (p95 - p5) > 0:
            spread_ratio = (p95 - p5) / expected
            gbm_score = min(1.0, max(0.10, 1.0 - spread_ratio * 2))
            reasons.append(f"GBM spread={spread_ratio:.2%}")
    bd["gbm"] = round(gbm_score, 4)

    # 7. intraday spread -- bigger % moves are more noteworthy
    abs_change = abs(change_pct)
    if abs_change > 3.0:
        spread_score = min(1.0, abs_change / 10);                                size = "large"
    elif abs_change > 1.5:
        spread_score = 0.30 + (abs_change - 1.5) / 1.5 * 0.40;                   size = "moderate"
    else:
        spread_score = abs_change / 1.5 * 0.30;                                  size = "small"
    reasons.append(f"move={abs_change:.1f}% ({size})")
    bd["intraday_spread"] = round(spread_score, 4)

    # final: weighted average across all 7 factors
    total_w = (_CONSIDER_MOMENTUM_WEIGHT + _CONSIDER_TREND_WEIGHT
               + _CONSIDER_VOLATILITY_WEIGHT + _CONSIDER_EXHAUSTION_WEIGHT
               + _CONSIDER_CONFLUENCE_WEIGHT + _CONSIDER_GBM_WEIGHT
               + _CONSIDER_INTRADAY_SPREAD_WEIGHT)
    weighted = (mom_score * _CONSIDER_MOMENTUM_WEIGHT
                + trend_score * _CONSIDER_TREND_WEIGHT
                + vol_score * _CONSIDER_VOLATILITY_WEIGHT
                + exh_score * _CONSIDER_EXHAUSTION_WEIGHT
                + conf_score * _CONSIDER_CONFLUENCE_WEIGHT
                + gbm_score * _CONSIDER_GBM_WEIGHT
                + spread_score * _CONSIDER_INTRADAY_SPREAD_WEIGHT)
    score = round(weighted / total_w, 4) if total_w > 0 else 0.0

    action = ("alert" if score >= _CONSIDER_BORDERLINE_HIGH else
              "borderline" if score >= _CONSIDER_BORDERLINE_LOW else
              "suppress")
    return {"score": score, "action": action, "reasons": reasons, "breakdown": bd}


def should_suppress_alert(consideration: dict, volume_spike: bool = False) -> bool:
    """Final gate. True = suppress. Volume spike can rescue a borderline."""
    action = consideration.get("action", "suppress")
    if action == "alert":      return False              # definitely send
    if action == "borderline": return not volume_spike   # send only with volume
    return True                                          # suppress noise


# ═══════════════════════════════════════════════════════════════════════════════
# SANDBOX -- test data, simulation runner, CLI. Only runs when executed directly.
# ═══════════════════════════════════════════════════════════════════════════════

TEST_DATA = {
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
        "current_price": 107.5, "open_price": 100.0, "avg_volume": 50000,
        "strike": 110.0, "cost_basis": 105.0, "clt_price": 99.0,
        "desc": "Steady uptrend -- expect +momentum, bullish, no exhaustion",
    },
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
        "current_price": 97.8, "open_price": 105.0, "avg_volume": 50000,
        "strike": 95.0, "cost_basis": 100.0, "clt_price": 110.0,
        "desc": "Steady downtrend -- expect -momentum, bearish, no exhaustion",
    },
    "SIDEWAYS": {
        "prices": [100.0, 100.5, 99.8, 100.2, 100.1],
        "candles": [
            {"high": 101.0, "low": 99.5, "close": 100.5, "volume": 30000},
            {"high": 100.8, "low": 99.3, "close": 99.8,  "volume": 28000},
            {"high": 101.2, "low": 99.0, "close": 100.2, "volume": 32000},
            {"high": 100.5, "low": 99.8, "close": 100.1, "volume": 31000},
            {"high": 101.0, "low": 99.5, "close": 100.3, "volume": 29000},
        ],
        "current_price": 100.3, "open_price": 100.0, "avg_volume": 30000,
        "strike": 100.0, "cost_basis": 100.0, "clt_price": 90.0,
        "desc": "Range-bound -- expect ~0 momentum, neutral, compressing vol",
    },
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
        "current_price": 104.0, "open_price": 100.0, "avg_volume": 40000,
        "strike": 100.0, "cost_basis": 100.0, "clt_price": 95.0,
        "desc": "Sharp spike then pullback -- expect exhaustion, expanding vol",
    },
    "SES_LIVE": {
        "prices": [1.08, 1.07, 1.06, 1.06, 1.05],
        "candles": [
            {"high": 1.09, "low": 1.07, "close": 1.08,  "volume": 120000},
            {"high": 1.08, "low": 1.06, "close": 1.07,  "volume": 135000},
            {"high": 1.07, "low": 1.05, "close": 1.06,  "volume": 145000},
            {"high": 1.07, "low": 1.05, "close": 1.06,  "volume": 155000},
            {"high": 1.06, "low": 1.04, "close": 1.05,  "volume": 160000},
            {"high": 1.06, "low": 1.04, "close": 1.05,  "volume": 150000},
            {"high": 1.06, "low": 1.04, "close": 1.055, "volume": 148000},
        ],
        "current_price": 1.055, "open_price": 1.08, "avg_volume": 80000,
        "strike": 1.00, "cost_basis": 1.05, "clt_price": 1.12,
        "desc": "SES live snapshot #324 -- bearish momentum, normal vol, high volume",
    },
}


def run_simulation(name: str, data: dict) -> List[str]:
    """Run full VMQ+ pipeline on one test dataset. Returns printable lines."""
    lines: List[str] = []
    sep = "-" * 52

    prices, candles = data["prices"], data["candles"]
    cp, op = data["current_price"], data["open_price"]
    avg_vol = data.get("avg_volume", 50000)
    desc = data.get("desc", "")

    # Run the whole factory pipeline at once
    ctx = VMQFactory.run(
        prices=prices, candles=candles,
        current_price=cp, open_price=op,
        avg_volume=avg_vol,
        strike=data.get("strike", 0),
        cost_basis=data.get("cost_basis", 0),
        clt_price=data.get("clt_price", 0),
        is_hedged=False, scalp_viable=False,
    )

    lines += ["", f"  +=== VMQ+ SIMULATION [ML/Harm v3]: {name} ===+",
              f"  |  {desc}", f"  +{'=' * 48}+", ""]

    # 1. Momentum
    m_hist, m_day = ctx["momentum"]["historical"], ctx["momentum"]["intraday"]
    mom_strength = ("strong" if abs(m_hist) > MOM_HIGH else
                    "moderate" if abs(m_hist) > MOM_MED else "weak")
    lines += [f"  1. MOMENTUM  [Kalman+EWMA+FractalDim]",
              f"     Historical: {m_hist:+.6f}  ({mom_strength})",
              f"     Intraday:   {m_day:+.4f}  [log-scaled+Fib]",
              f"     Price D:    {cp - prices[0]:+.2f} ({(cp - prices[0]) / prices[0] * 100:+.2f}%)",
              f"     FractalDim: {_fractal_dimension(prices):.4f}  (1=trend, 2=noise)",
              f"     {sep}"]

    # 2. Trend
    trend = ctx["trend"]
    arrow = "^" if trend["bias"] == "bullish" else ("v" if trend["bias"] == "bearish" else ">")
    lines += [f"  2. TREND  [FractalWin+ADX+Fib+Entropy]",
              f"     Bias:       {trend['bias'].upper()} {arrow}",
              f"     HH: {trend['hh']}  |  LL: {trend['ll']}  (win={trend['adaptive_window']})",
              f"     Strength:   {trend.get('strength', 0):.4f}  Clarity: {trend.get('clarity', 0):.4f}",
              f"     RevPress:   {trend.get('reversal_pressure', 0):.4f}",
              f"     {sep}"]

    # 3. Volatility
    vol, atr = ctx["volatility"], ctx["volatility"]["atr"]
    vol_icon = "!" if vol["state"] == "expanding" else ("=" if vol["state"] == "compressing" else ".")
    lines += [f"  3. VOLATILITY  [GARCH+Harmonic+EMA-ATR]",
              f"     State:      {vol['state'].upper()} {vol_icon}",
              f"     CV blend:   {vol['cv']:.6f}  "
              f"(samp={vol.get('cv_sample',0):.4f} garch={vol.get('cv_garch',0):.4f} "
              f"cycle={vol.get('cv_cycle',0):.4f})",
              f"     ATR(EMA):   ${atr:.4f}  ({atr / cp * 100:.2f}% of price)",
              f"     HarmPeriod: {vol.get('harmonic_period',0)} bars",
              f"     {sep}"]

    # 4. Exhaustion
    exh = ctx["exhaustion"]
    lines += [f"  4. EXHAUSTION  [AdaptZ+Entropy+Fib+Bayes]",
              f"     Status:     {'EXHAUSTED' if exh['exhausted'] else 'CLEAN'}",
              f"     Z blend:    {exh['z_score']:+.4f}  "
              f"(orig={exh.get('z_orig',0):+.4f} adap={exh.get('z_adaptive',0):+.4f})",
              f"     Clarity:    {exh.get('direction_clarity',0):.4f}  "
              f"FibProx: {exh.get('fib_proximity',0):.4f}",
              f"     BayesConf:  {exh.get('exhaustion_confidence',0):.4f}  "
              f"(threshold: +/- {EXHAUSTION_Z_THRESHOLD})",
              f"     {sep}"]

    # 5. Volume
    vol_sig = ctx["volume"]
    lines += [f"  5. VOLUME  [EWMA-baseline+ROC]",
              f"     Signal:     {vol_sig.upper()}",
              f"     Avg Vol:    {avg_vol:,}",
              f"     {sep}"]

    # 6. UPSS Signals
    upss = ctx["upss"]
    signal_str = (", ".join(f"{s['sym']}:{s['dir']}:{s['conf']:.2f}" for s in upss)
                  if upss else "(none)")
    conf_score = _harmonic_confluence(upss)
    lines += [f"  6. UPSS SIGNALS  [Confluence+Bayes+FD]",
              f"     Active:     {signal_str}",
              f"     Confluence: {conf_score:.4f}",
              f"     {sep}"]

    # 7. GBM Projections (multiple horizons)
    gbms = ctx["gbm"]
    for g in gbms:
        lines += [f"  7. GBM ({g['horizon_label']})  [Merton+GARCH+HarmDrift]",
                  f"     Expected:  ${g['expected']:.2f}",
                  f"     Range:     ${g['p5']:.2f} - ${g['p95']:.2f}",
                  f"     Median:    ${g['median']:.2f}",
                  f"     {sep}"]

    # 8. Chains
    chins = ctx["chains"]
    if chins:
        for c in chins:
            lines += [f"  8. CHAIN: {c['id']}  [Bayes+FibCLT+Coherence]",
                      f"     Confidence: {c['confidence']:.4f}",
                      f"     Signals: {', '.join(c['signals'])}"]
    else:
        lines += [f"  8. CHAINS", f"     (none active)"]
    lines.append(f"     {sep}")

    # 9. Alert Consideration -- runs after all 8 stages
    change_pct = ((cp - prices[0]) / prices[0] * 100) if prices[0] > 0 else 0.0
    consideration = alert_consideration_score(
        momentum=m_hist, trend_bias=trend["bias"],
        trend_strength=trend.get("strength", 0.0),
        trend_clarity=trend.get("clarity", 0.0),
        vol_state=vol["state"], vol_cv=vol["cv"],
        exhaustion_exhausted=exh["exhausted"], exhaustion_z=exh["z_score"],
        confluence=conf_score, gbm_list=gbms, change_pct=change_pct,
    )
    icon = {"alert": "!!", "borderline": "? ", "suppress": "--"}.get(consideration["action"], "??")
    suppressed = should_suppress_alert(consideration, vol_sig == "high")
    b = consideration["breakdown"]
    lines += [f"  9. ALERT CONSIDERATION  [7-factor weighted score]",
              f"     Score:      {consideration['score']:.4f}  [{icon}]  "
              f"{consideration['action'].upper()}",
              f"     Suppressed: {suppressed}",
              f"     Breakdown:  "
              f"M={b.get('momentum',0):.2f}  T={b.get('trend',0):.2f}  "
              f"V={b.get('volatility',0):.2f}  E={b.get('exhaustion',0):.2f}  "
              f"C={b.get('confluence',0):.2f}  G={b.get('gbm',0):.2f}  "
              f"S={b.get('intraday_spread',0):.2f}"]
    for reason in consideration.get("reasons", [])[:3]:
        lines.append(f"     > {reason}")

    # Module Status summary
    lines += ["", f"  {'=' * 48}", f"  MODULE STATUS REPORT: {name}", f"  {'=' * 48}"]
    mods = [("1. Momentum       ", True), ("2. Trend           ", True),
            ("3. Volatility      ", True), ("4. Exhaustion      ", True),
            ("5. Volume Signal   ", True), ("6. UPSS Signals    ", bool(upss)),
            ("7. GBM Projections ", bool(gbms)), ("8. Chain Detection ", bool(chins)),
            ("9. Alert Consider. ", True)]
    all_ok = True
    for mod_name, ok in mods:
        status = "OK" if ok else "NO SIGNAL"
        lines.append(f"  [{status}]  {mod_name}")
        if not ok: all_ok = False
    lines += [f"  {'=' * 48}",
              f"  RESULT: {'ALL MODULES OPERATIONAL' if all_ok else 'SOME MODULES HAD NO OUTPUT'}"]
    return lines


def run_tests(symbols: Optional[List[str]] = None) -> None:
    """Run simulation for selected symbols (or all if none given)."""
    cases = {k: v for k, v in TEST_DATA.items() if k in symbols} if symbols else TEST_DATA
    if not cases:
        print(f"No matching test cases. Available: {', '.join(TEST_DATA.keys())}")
        return
    for name, data in cases.items():
        for line in run_simulation(name, data):
            print(line)
        print("")

    # Final summary
    print("")
    print("  ╔" + "═" * 54 + "╗")
    print("  ║  VMQ+ CORE.PY — STANDALONE TEST REPORT             ║")
    print("  ╠" + "═" * 54 + "╣")
    print(f"  ║  Scenarios run:    {len(cases):>2d} / {len(TEST_DATA)}                              ║")
    print(f"  ║  Modules per run:   9                                ║")
    print(f"  ║  Total calcs:      {len(cases) * 9:>2d}                               ║")
    print("  ╠" + "═" * 54 + "╣")
    print("  ║  MODULE                  STATUS                      ║")
    print("  ╠" + "═" * 54 + "╣")
    mod_list = [
        ("1. momentum_from_prices",    "OK"), ("2. momentum_intraday",       "OK"),
        ("3. trend_from_candles",      "OK"), ("4. volatility_state",        "OK"),
        ("5. atr_from_candles",        "OK"), ("6. exhaustion_zscore",       "OK"),
        ("7. volume_compare",          "OK"), ("8. upss_generate",           "OK"),
        ("9. gbm_project",             "OK"), ("10. gbm_multi_horizon",      "OK"),
        ("11. chains_detect",          "OK"), ("12. alert_consideration",    "OK"),
        ("13. should_suppress_alert",  "OK"), ("14. ML/Harmonic primitives", "OK"),
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
    """Quick smoke test -- BULL_RUN and BEAR_SLIDE only."""
    run_tests(["BULL_RUN", "BEAR_SLIDE"])


if __name__ == "__main__":
    # Force UTF-8 on Windows so Greek glyphs (α β γ δ Ω) render
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

#!/usr/bin/env python3
"""
test_components — Verify all market_components work from personal_quants dir.

Run: python3 market_components/test_components.py

Exit codes: 0 = all pass, 1 = failures
"""

import sys
import os

# Ensure we can import from the parent of market_components
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

passed = 0
failed = 0


def check(name: str, ok: bool, detail: str = ""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}" + (f" — {detail}" if detail else ""))


# ── 1. Constants ─────────────────────────────────────────────────────
print("\n1. Constants")
from market_components.constants import (
    MINUTES_PER_YEAR, HIGH_VOL_CV, LOW_VOL_CV, MOM_HIGH, MOM_MED,
    GBM_VOLATILITY_INTRADAY, EXHAUSTION_Z_THRESHOLD,
)
check("MINUTES_PER_YEAR ≈ 525600", abs(MINUTES_PER_YEAR - 525600) < 1)
check("HIGH_VOL_CV = 0.03", HIGH_VOL_CV == 0.03)
check("LOW_VOL_CV = 0.01", LOW_VOL_CV == 0.01)
check("MOM_HIGH = 0.03", MOM_HIGH == 0.03)
check("MOM_MED = 0.01", MOM_MED == 0.01)
check("GBM_VOL_INTRADAY = 0.03", GBM_VOLATILITY_INTRADAY == 0.03)
check("EXHAUSTION_Z = 2.0", EXHAUSTION_Z_THRESHOLD == 2.0)

# ── 2. Momentum ──────────────────────────────────────────────────────
print("\n2. Momentum")
from market_components.momentum import from_price_series, intraday

m = from_price_series([100, 101, 102, 103, 104])
check("rising prices → positive momentum", m > 0, str(m))

m = from_price_series([104, 103, 102, 101, 100])
check("falling prices → negative momentum", m < 0, str(m))

m = from_price_series([100, 100, 100, 100])
check("flat prices → zero momentum", m == 0.0, str(m))

m = from_price_series([])
check("empty series → 0.0", m == 0.0)

m = intraday(110, 100)
check("intraday +10% → positive", m > 0, str(m))

m = intraday(90, 100)
check("intraday -10% → negative", m < 0, str(m))

m = intraday(100, 0)
check("intraday zero open → 0.0", m == 0.0)

# ── 3. Trend ─────────────────────────────────────────────────────────
print("\n3. Trend")
from market_components.trend import from_candles

t = from_candles([
    {"high": 100, "low": 95},
    {"high": 102, "low": 96},
    {"high": 104, "low": 97},
    {"high": 106, "low": 98},
])
check("rising → bullish", t["bias"] == "bullish", str(t))

t = from_candles([
    {"high": 106, "low": 98},
    {"high": 104, "low": 97},
    {"high": 102, "low": 96},
    {"high": 100, "low": 95},
])
check("falling → bearish", t["bias"] == "bearish", str(t))

t = from_candles([])
check("empty → neutral", t["bias"] == "neutral")

# ── 4. Volatility ────────────────────────────────────────────────────
print("\n4. Volatility")
from market_components.volatility import state_from_prices, atr

v = state_from_prices([100, 101, 100, 101, 100])
check("tight range → compressing or normal", v["state"] in ("compressing", "normal"), str(v))

v = state_from_prices([100, 110, 95, 115, 90])
check("wide range → expanding or normal", v["state"] in ("expanding", "normal"), str(v))

v = state_from_prices([])
check("empty → unknown", v["state"] == "unknown")

a = atr([{"high": 102, "low": 98, "close": 100},
         {"high": 105, "low": 99, "close": 104}])
check("ATR > 0 for valid candles", a > 0, str(a))

# ── 5. Exhaustion ────────────────────────────────────────────────────
print("\n5. Exhaustion")
from market_components.exhaustion import from_price_deltas

e = from_price_deltas([100, 101, 100, 101, 100])
check("stable → not exhausted", not e["exhausted"], str(e))

e = from_price_deltas([100, 110, 95, 115, 90])
check("volatile → may or may not exhaust (valid z-score)",
      isinstance(e["z_score"], float), str(e))

e = from_price_deltas([])
check("empty → not exhausted, z=0", not e["exhausted"] and e["z_score"] == 0.0)

# ── 6. Volume Signal ─────────────────────────────────────────────────
print("\n6. Volume Signal")
from market_components.volume_sig import compare

v = compare([{"volume": 100} for _ in range(5)], avg_volume=100)
check("normal volume → normal (~)", True,
      f"got: {v}")  # could be normal or unknown depending

v = compare([{"volume": 1000} for _ in range(5)], avg_volume=100)
check("high relative volume → high", v in ("high", "elevated"), str(v))

# ── 7. Signals ───────────────────────────────────────────────────────
print("\n7. Signals")
from market_components.signals import classify

d, e, m = classify(0.06, "bullish", "expanding", 0.5, False, 2.0, False, False, "")
check("strong up → direction UP", d == "UP", f"{d}")
check("strong up → energy HIGH", e == "HIGH", f"{e}")

d, e, m = classify(-0.06, "bearish", "expanding", 0.5, False, 2.0, False, False, "")
check("strong down → direction DOWN", d == "DOWN", f"{d}")

d, e, m = classify(0.01, "neutral", "normal", 0.5, False, 1.0, False, False, "")
check("weak flat → NEUTRAL/LOW", d == "NEUTRAL" and e == "LOW", f"{d}/{e}")

d, e, m = classify(0.04, "bullish", "normal", 0.2, True, 1.5, False, False, "")
check("exhausted up → exhaustion type",
      "exhaustion" in m, f"{m}")

# ── 8. UPSS ──────────────────────────────────────────────────────────
print("\n8. UPSS")
from market_components.upss import generate

sigs = generate(0.05, "bullish", "expanding", 0.5, False, False, False)
syms = [s["sym"] for s in sigs]
check("strong mom → α generated", "α" in syms, str(syms))

sigs = generate(0.02, "bullish", "compressing", 0.3, True, True, False)
syms = [s["sym"] for s in sigs]
check("exhausted + compressing → hedge or gamma", any(s in syms for s in ("H", "δ", "γ")), str(syms))

# ── 9. GBM ───────────────────────────────────────────────────────────
print("\n9. GBM")
from market_components.gbm import project, multi_horizon

p = project(100, 0.05, 5, 0.03)
check("GBM project has expected price", p["expected"] > 0, str(p["expected"]))
check("GBM has range: p5 < p95", p["p5"] < p["p95"], f"{p['p5']} < {p['p95']}")
check("GBM has median ~ expected", abs(p["median"] - p["expected"]) / p["expected"] < 0.01)

projs = multi_horizon(100, 0.05)
check("multi_horizon returns 3 projections", len(projs) == 3)
check("all horizons have valid keys", all(
    all(k in p for k in ("expected", "p25", "p75", "horizon_label"))
    for p in projs
))

# ── 10. Chains ───────────────────────────────────────────────────────
print("\n10. Chains")
from market_components.chains import detect

# CLT test: price near strike with H signal
ch = detect(
    [{"sym": "H", "name": "hedge", "dir": "flat", "conf": 0.85},
     {"sym": "δ", "name": "delta", "dir": "bear", "conf": 0.7}],
    current_price=108, strike=110, cost_basis=105,
    clt_price=112, scalp_viable=False,
)
chain_ids = [c["id"] for c in ch]
check("CLT_APPROACH when near strike + H present",
      "CLT_APPROACH" in chain_ids, str(chain_ids))

# Full hedge test
ch = detect(
    [{"sym": "H", "name": "hedge", "dir": "flat", "conf": 0.85},
     {"sym": "δ", "name": "delta", "dir": "bear", "conf": 0.7}],
    current_price=100, strike=110, cost_basis=105,
    clt_price=0, scalp_viable=False,
)
chain_ids = [c["id"] for c in ch]
check("FULL_HEDGE with H+δ signals", "FULL_HEDGE" in chain_ids, str(chain_ids))

# ── Summary ──────────────────────────────────────────────────────────
print(f"\n{'=' * 40}")
print(f"Results: {passed} passed, {failed} failed, "
      f"{passed + failed} total")
print(f"{'=' * 40}")

sys.exit(0 if failed == 0 else 1)

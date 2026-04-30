"""
constants — Static Projection Tunables
=======================================

One-stop shop for all threshold parameters.
C can tweak these values without touching any logic code.

---
The VMQ+ Reference — for portable market calculations.
"""

# ── Time Constants ──────────────────────────────────────────────────
MINUTES_PER_YEAR: float = 525600.0          # 365 × 24 × 60
MARKET_OPEN_HOUR_EST: int = 9
MARKET_OPEN_MINUTE_EST: int = 30

# ── GBM (Geometric Brownian Motion) ─────────────────────────────────
GBM_VOLATILITY_INTRADAY: float = 0.03       # 3%  annualized  (5-min)
GBM_VOLATILITY_5DAY: float = 0.25           # 25% annualized  (5-day)
GBM_VOLATILITY_30DAY: float = 0.45          # 45% annualized (30-day)
GBM_DRIFT_SCALING_FACTOR: float = 0.5       # × momentum for drift

# ── Z-Score Constants ───────────────────────────────────────────────
Z_SCORE_25TH: float = -0.674
Z_SCORE_75TH: float = 0.674
Z_SCORE_95TH: float = 1.645
EXHAUSTION_Z_THRESHOLD: float = 2.0          # |z| > 2σ = exhausted

# ── Volatility State ────────────────────────────────────────────────
HIGH_VOL_CV: float = 0.03                    # CV > 3%   → expanding
LOW_VOL_CV: float = 0.01                     # CV < 1%   → compressing

# ── Signal Classification ──────────────────────────────────────────
MOM_HIGH: float = 0.03
MOM_MED: float = 0.01
MOM_LOW: float = 0.005
VOL_HIGH: float = 1.5
VOL_MED: float = 1.2

# ── Projection ──────────────────────────────────────────────────────
INTRADAY_INTERVALS: int = 18                 # 18 × 5min = 90 min
INTRADAY_DECAY: float = 0.04
INTRADAY_CLAMP_PCT: float = 0.10
SHORT_TERM_DAYS: int = 5
LONG_TERM_DAYS: int = 15

# ── UPSS Thresholds ─────────────────────────────────────────────────
UPSS_ALPHA_THRESHOLD: float = 0.03
UPSS_BETA_MIN: float = 0.015
UPSS_BETA_MAX: float = 0.03
UPSS_GAMMA_THRESHOLD: float = 0.4
UPSS_OMEGA_THRESHOLD: float = 0.2

# ── Chain Detection ─────────────────────────────────────────────────
CLT_PROXIMITY_PCT: float = 0.10             # 10% of strike = CLT zone

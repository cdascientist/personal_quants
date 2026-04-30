"""
utils — Market Utilities
=========================

Consolidated utility functions for market analysis:
constants, data fetching, exchange rates, signal classification.

---
The VMQ+ Reference — for portable market calculations.
├── utils.py      ← you are here (helpers, fetching, classification)
└── core.py       ← pure algorithmic quants (momentum, trend, vol, etc.)
"""

# ═════════════════════════════════════════════════════════════════════════════
# SECTION A — Constants & Tunables
# ═════════════════════════════════════════════════════════════════════════════

# ── Time ────────────────────────────────────────────────────────────
MINUTES_PER_YEAR: float = 525600.0          # 365 × 24 × 60
MARKET_OPEN_HOUR_EST: int = 9
MARKET_OPEN_MINUTE_EST: int = 30

# ── GBM Volatility Estimates ────────────────────────────────────────
GBM_VOLATILITY_INTRADAY: float = 0.03       # 3%  annualized  (5-min)
GBM_VOLATILITY_5DAY: float = 0.25           # 25% annualized  (5-day)
GBM_VOLATILITY_30DAY: float = 0.45          # 45% annualized (30-day)
GBM_DRIFT_SCALING_FACTOR: float = 0.5       # × momentum for drift

# ── Z-Score Thresholds ──────────────────────────────────────────────
Z_SCORE_25TH: float = -0.674
Z_SCORE_75TH: float = 0.674
Z_SCORE_95TH: float = 1.645
EXHAUSTION_Z_THRESHOLD: float = 2.0          # |z| > 2σ = exhausted

# ── Volatility State ────────────────────────────────────────────────
HIGH_VOL_CV: float = 0.03                    # CV > 3%   → expanding
LOW_VOL_CV: float = 0.01                     # CV < 1%   → compressing

# ── Momentum Signal Classification ──────────────────────────────────
MOM_HIGH: float = 0.03
MOM_MED: float = 0.01
MOM_LOW: float = 0.005
VOL_HIGH: float = 1.5
VOL_MED: float = 1.2

# ── Projection Horizons ─────────────────────────────────────────────
INTRADAY_INTERVALS: int = 18                 # 18 × 5min = 90 min
INTRADAY_DECAY: float = 0.04
INTRADAY_CLAMP_PCT: float = 0.10
SHORT_TERM_DAYS: int = 5
LONG_TERM_DAYS: int = 15

# ── UPSS ────────────────────────────────────────────────────────────
UPSS_ALPHA_THRESHOLD: float = 0.03
UPSS_BETA_MIN: float = 0.015
UPSS_BETA_MAX: float = 0.03
UPSS_GAMMA_THRESHOLD: float = 0.4
UPSS_OMEGA_THRESHOLD: float = 0.2

# ── Chain Detection ─────────────────────────────────────────────────
CLT_PROXIMITY_PCT: float = 0.10             # 10% of strike = CLT zone


# ═════════════════════════════════════════════════════════════════════════════
# SECTION B — Market Data Fetching
# ═════════════════════════════════════════════════════════════════════════════

import os
import requests


class MarketClosedError(Exception):
    """Raised when API returns zero-price (market closed / holiday)."""
    pass


def quote_finnhub(ticker: str) -> dict:
    """Fetch live quote from Finnhub API.

    Returns
    -------
    {
        "current_price": float, "open": float, "high": float,
        "low": float, "prev_close": float,
        "dollar_change": float, "percent_change": float
    }

    Raises MarketClosedError if current_price == 0.
    """
    key = os.environ.get("FINNHUB_API_KEY", "")
    r = requests.get(
        f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={key}",
        timeout=10,
    )
    j = r.json()
    c = j.get("c", 0.0)
    if c == 0.0:
        raise MarketClosedError(f"{ticker}: current_price=0 (market closed)")
    o = j.get("o", c)
    pc = j.get("pc", c)
    return {
        "current_price": c,
        "open": o,
        "high": j.get("h", c),
        "low": j.get("l", c),
        "prev_close": pc,
        "dollar_change": c - pc,
        "percent_change": ((c - pc) / pc * 100) if pc else 0.0,
    }


def fundamentals_finnhub(ticker: str) -> dict:
    """Fetch fundamental metrics (P/E, 52w, market cap)."""
    key = os.environ.get("FINNHUB_API_KEY", "")
    r = requests.get(
        f"https://finnhub.io/api/v1/stock/metric?symbol={ticker}"
        f"&metric=all&token={key}",
        timeout=10,
    )
    m = r.json().get("metric", {})
    return {
        "market_cap": m.get("marketCapitalization", 0),
        "pe_ratio": m.get("peBasicExclExtraTTM", 0),
        "high_52w": m.get("52WeekHigh", 0),
        "low_52w": m.get("52WeekLow", 0),
    }


def profile_finnhub(ticker: str) -> dict:
    """Fetch company profile (name, industry, exchange)."""
    key = os.environ.get("FINNHUB_API_KEY", "")
    r = requests.get(
        f"https://finnhub.io/api/v1/stock/profile2?symbol={ticker}&token={key}",
        timeout=10,
    )
    j = r.json()
    return {
        "name": j.get("name", ""),
        "industry": j.get("finnhubIndustry", ""),
        "exchange": j.get("exchange", ""),
    }


def candles_finnhub(
    ticker: str, resolution: str = "5", days: int = 1
) -> list:
    """Fetch historical OHLCV candles from Finnhub.

    Parameters
    ----------
    ticker : str
    resolution : str  — "1", "5", "15", "30", "60", "D", "W", "M"
    days : int        — lookback in calendar days

    Returns list of dicts with keys: time, open, high, low, close, volume
    """
    from datetime import datetime, timezone
    key = os.environ.get("FINNHUB_API_KEY", "")
    to_ts = int(datetime.now(timezone.utc).timestamp())
    fr_ts = to_ts - days * 86400
    r = requests.get(
        f"https://finnhub.io/api/v1/stock/candle"
        f"?symbol={ticker}&resolution={resolution}"
        f"&from={fr_ts}&to={to_ts}&token={key}",
        timeout=10,
    )
    j = r.json()
    if j.get("s") != "ok":
        return []
    candles = []
    for i in range(len(j.get("t", []))):
        candles.append({
            "time": j["t"][i],
            "open": j["o"][i],
            "high": j["h"][i],
            "low": j["l"][i],
            "close": j["c"][i],
            "volume": j["v"][i],
        })
    return candles


def price_twelvedata(ticker: str) -> float:
    """Quick real-time price from Twelve Data."""
    key = os.environ.get("TWELVEDATA_API_KEY", "")
    r = requests.get(
        f"https://api.twelvedata.com/price?symbol={ticker}&apikey={key}",
        timeout=10,
    )
    return float(r.json().get("price", 0))


def candles_twelvedata(
    ticker: str, interval: str = "5min", outputsize: int = 100
) -> list:
    """Fetch time-series candles from Twelve Data.

    Parameters
    ----------
    ticker : str
    interval : str   — "1min", "5min", "15min", "1day", "1week"
    outputsize : int

    Returns list of dicts with keys: datetime, open, high, low, close, volume
    """
    key = os.environ.get("TWELVEDATA_API_KEY", "")
    r = requests.get(
        f"https://api.twelvedata.com/time_series"
        f"?symbol={ticker}&interval={interval}"
        f"&outputsize={outputsize}&apikey={key}",
        timeout=10,
    )
    j = r.json()
    values = j.get("values", [])
    return [
        {
            "datetime": v["datetime"],
            "open": float(v["open"]),
            "high": float(v["high"]),
            "low": float(v["low"]),
            "close": float(v["close"]),
            "volume": int(v.get("volume", 0)),
        }
        for v in values
    ]


def exchange_rate(pair: str = "AUD/USD") -> float:
    """Get forex exchange rate from Twelve Data."""
    key = os.environ.get("TWELVEDATA_API_KEY", "")
    r = requests.get(
        f"https://api.twelvedata.com/exchange_rate"
        f"?symbol={pair}&apikey={key}",
        timeout=10,
    )
    return float(r.json().get("rate", 1.0))


def aud_usd() -> float:
    """Shorthand for AUD/USD rate."""
    return exchange_rate("AUD/USD")


# ═════════════════════════════════════════════════════════════════════════════
# SECTION C — Signal Classification
# ═════════════════════════════════════════════════════════════════════════════


def classify_signal(
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
    """Classify overall market signal: (direction, energy, msg_type).

    Parameters
    ----------
    momentum         : float  — [-1, 1]
    trend_bias       : str    — "bullish" | "bearish" | "neutral"
    volatility_state : str    — "expanding" | "compressing" | "normal"
    compression      : float  — compression factor [0, 1]
    is_exhausted     : bool
    volume_impulse   : float  — recent/avg volume ratio
    is_hedged        : bool
    scalp_viable     : bool
    scalp_dir        : str    — "up" | "down" | ""

    Returns
    -------
    (direction: str, energy: str, msg_type: str)
    """
    # Direction
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

    # Energy
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

    # Message type
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

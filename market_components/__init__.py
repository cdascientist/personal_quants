"""
market_components — Portable VMQ+ Market Analysis
===================================================

Two-file consolidated structure:
    utils.py — Data fetching, constants, exchange rates, signal classification
    core.py  — Pure algorithmic quants: momentum, trend, volatility, etc.

Backward-compatible module aliases are installed so old import patterns
still work (e.g. `from market_components.momentum import from_price_series`).

Usage:
    from market_components.utils import quote_finnhub, classify_signal
    from market_components.core import momentum_from_prices, upss_generate
"""
__version__ = "2.0.0"

import sys
import types


# ═══════════════════════════════════════════════════════════════════════
# Helper: create a synthetic module from a dict of attributes
# ═══════════════════════════════════════════════════════════════════════

def _make_alias(name: str, attrs: dict) -> types.ModuleType:
    """Create a synthetic module with given attributes and install in sys.modules."""
    mod = types.ModuleType(f"market_components.{name}")
    mod.__package__ = "market_components"
    mod.__path__ = []  # marker that this is a namespace-like module
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[f"market_components.{name}"] = mod
    return mod


# ── New consolidated imports ──────────────────────────────────────────
from market_components import utils
from market_components import core

# ═══════════════════════════════════════════════════════════════════════
# Backward-compatible module aliases
# ═══════════════════════════════════════════════════════════════════════

# ── constants ────────────────────────────────────────────────────
_make_alias("constants", {
    k: v for k, v in vars(utils).items()
    if k.isupper() and not k.startswith("_")
})

# ── datafetch ────────────────────────────────────────────────────
_make_alias("datafetch", {
    "MarketClosedError": utils.MarketClosedError,
    "quote_finnhub": utils.quote_finnhub,
    "fundamentals_finnhub": utils.fundamentals_finnhub,
    "profile_finnhub": utils.profile_finnhub,
    "candles_finnhub": utils.candles_finnhub,
    "price_twelvedata": utils.price_twelvedata,
    "candles_twelvedata": utils.candles_twelvedata,
    "exchange_rate": utils.exchange_rate,
})

# ── fx ───────────────────────────────────────────────────────────
_make_alias("fx", {
    "rate": utils.exchange_rate,
    "aud_usd": utils.aud_usd,
})

# ── signals ──────────────────────────────────────────────────────
_make_alias("signals", {
    "classify": utils.classify_signal,
})

# ── momentum ─────────────────────────────────────────────────────
_make_alias("momentum", {
    "from_price_series": core.momentum_from_prices,
    "intraday": core.momentum_intraday,
})

# ── trend ────────────────────────────────────────────────────────
_make_alias("trend", {
    "WINDOW_SIZE": core.WINDOW_SIZE,
    "from_candles": core.trend_from_candles,
})

# ── volatility ───────────────────────────────────────────────────
_make_alias("volatility", {
    "state_from_prices": core.volatility_state,
    "atr": core.atr_from_candles,
})

# ── exhaustion ───────────────────────────────────────────────────
_make_alias("exhaustion", {
    "from_price_deltas": core.exhaustion_zscore,
})

# ── volume_sig ───────────────────────────────────────────────────
_make_alias("volume_sig", {
    "compare": core.volume_compare,
})

# ── upss ─────────────────────────────────────────────────────────
_make_alias("upss", {
    "generate": core.upss_generate,
})

# ── gbm ──────────────────────────────────────────────────────────
_make_alias("gbm", {
    "project": core.gbm_project,
    "multi_horizon": core.gbm_multi_horizon,
})

# ── chains ───────────────────────────────────────────────────────
_make_alias("chains", {
    "detect": core.chains_detect,
})

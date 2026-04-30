"""
market_components — Portable VMQ+ Market Analysis Components
=============================================================

Standalone Python modules for market data analysis.
Each module is self-contained and importable from any location.

Usage:
    from market_components import momentum, trend, volatility, ...
    from market_components.constants import *

Components:
    constants     — Static projection thresholds and parameters
    datafetch     — API data fetching (Finnhub, Twelve Data)
    momentum      — Rate-of-change momentum calculations
    trend         — Trend bias detection (higher highs/lower lows)
    volatility    — Volatility state, CV, ATR calculations
    exhaustion    — Z-score exhaustion detection
    volume_sig    — Volume signal analysis
    signals       — Signal classification and message typing
    upss          — UPSS Greek-letter signal taxonomy
    gbm           — Geometric Brownian Motion projections
    chains        — Active chain detection
    fx            — Exchange rate utilities
"""
__version__ = "1.0.0"

from market_components import constants
from market_components import datafetch
from market_components import momentum
from market_components import trend
from market_components import volatility
from market_components import exhaustion
from market_components import volume_sig
from market_components import signals
from market_components import upss
from market_components import gbm
from market_components import chains
from market_components import fx

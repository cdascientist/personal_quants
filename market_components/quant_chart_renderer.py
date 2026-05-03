"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    QUANT ALERT CHART RENDERER                               ║
║                    quant_chart_renderer.py                                  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  PURPOSE                                                                    ║
║  Replaces the current chart generation in the alert system.                 ║
║  Produces three separate PNG images (24H, 36H, 15D) for any ticker.        ║
║  Each PNG is attached individually to the SendInBlue alert email.           ║
║  The alert text body is never modified — only attachments are added.        ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  AGENT INSTRUCTIONS — READ THIS FIRST                                       ║
║                                                                             ║
║  1. Install prerequisites (see INSTALLATION section below)                  ║
║  2. Import render_all_charts from this file                                 ║
║  3. Call it with your ticker, candle data, and price info                   ║
║  4. Receive three PNG byte buffers back                                     ║
║  5. Base64-encode each buffer and attach to SendInBlue email                ║
║  6. Do NOT merge the three images. Do NOT change the alert text.            ║
║                                                                             ║
║  The ticker is arbitrary. This works for any symbol your data pipeline      ║
║  already provides. Replace "SES" in your calling code with the live ticker. ║
╚══════════════════════════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INSTALLATION — run these commands before anything else
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step 1 — Python packages:

    pip install pyppeteer numpy

Step 2 — Chromium (pyppeteer downloads it automatically on first run):

    python -c "import asyncio; from pyppeteer import launch; asyncio.run(launch(headless=True).then(lambda b: b.close()))"

    Or trigger the download explicitly:

    python -m pyppeteer fetch

Step 3 — On Linux servers (SSH/headless) you may need these system packages:

    sudo apt-get install -y \
        ca-certificates fonts-liberation libappindicator3-1 libasound2 \
        libatk-bridge2.0-0 libatk1.0-0 libc6 libcairo2 libcups2 libdbus-1-3 \
        libexpat1 libfontconfig1 libgbm1 libgcc1 libglib2.0-0 libgtk-3-0 \
        libnspr4 libnss3 libpango-1.0-0 libpangocairo-1.0-0 libstdc++6 \
        libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 libxdamage1 \
        libxext6 libxfixes3 libxi6 libxrandr2 libxrender1 libxss1 libxtst6 \
        lsb-release wget xdg-utils

Step 4 — If running inside Docker or a sandboxed environment add this flag:

    In render_chart() below, args already includes --no-sandbox.
    No extra config needed.

Step 5 — Verify the full pipeline works:

    python quant_chart_renderer.py

    This runs the built-in test and writes three PNG files to disk:
    TICKER_24H_TIMESTAMP.png, TICKER_36H_TIMESTAMP.png, TICKER_15D_TIMESTAMP.png
    Open them and confirm the charts look correct before deploying.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW TO INTEGRATE INTO THE EXISTING ALERT SYSTEM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Your existing alert code looks roughly like this:

    # Existing code
    send_alert(ticker, alert_text)

Replace it with:

    import asyncio, base64
    from quant_chart_renderer import render_all_charts
    from datetime import datetime, timezone

    # Your existing data variables (already available in your pipeline):
    #   ticker          — string e.g. "SES", "AAPL", "BTC-USD"
    #   candles_5m      — list of last 50+ 5-minute candles
    #   candles_15m     — list of last 44+ 15-minute candles
    #   candles_daily   — list of last 30+ daily candles
    #   current_price   — float, live price
    #   prev_close      — float, prior day close
    #   net_move_pct    — float, percentage change (negative = red)

    chart_24h, chart_36h, chart_15d = asyncio.run(render_all_charts(
        ticker        = ticker,
        candles_5m    = candles_5m,
        candles_15m   = candles_15m,
        candles_daily = candles_daily,
        current_price = current_price,
        prev_close    = prev_close,
        net_move_pct  = net_move_pct,
    ))

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    attachments = [
        {"content": base64.b64encode(chart_24h).decode(),
         "name": f"{ticker}_24H_{ts}.png", "type": "image/png"},
        {"content": base64.b64encode(chart_36h).decode(),
         "name": f"{ticker}_36H_{ts}.png", "type": "image/png"},
        {"content": base64.b64encode(chart_15d).decode(),
         "name": f"{ticker}_15D_{ts}.png", "type": "image/png"},
    ]

    # Pass attachments into your existing SendInBlue call.
    # The alert_text body is NOT modified. Only attachments are appended.
    send_alert(ticker, alert_text, extra_attachments=attachments)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CANDLE DATA FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Each candle must be a dict with these keys:

    {
        "o": float,   # open price
        "h": float,   # high price
        "l": float,   # low price
        "c": float,   # close price
        "v": float,   # volume (any unit — internally normalized)
    }

Candles must be ordered oldest-first. The last element is the most recent.
Minimum counts required:  5m: 50 candles,  15m: 44 candles,  daily: 30 candles.
Extra candles are fine — the renderer takes only what it needs from the end.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VISUAL SPEC SUMMARY — what these charts look like
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

3D perspective chart tilted at a viewing angle. Three world axes:
  X = time (left = oldest, right = newest/future)
  Y = price (up = higher)
  Z = volume (depth into screen)

LEFT HALF  — historical candles shown as glowing glass spheres. Sphere
  radius scales with volume. A smooth trend line connects all closes.
  Volume is shown as depth bars on the floor (Z axis).

CENTER — a translucent RED plane marks the NOW boundary, always at the
  horizontal midpoint of the chart. A glowing anchor dot marks where
  all predictions originate.

RIGHT HALF — 12 GBM simulation paths bloom outward from the NOW anchor.
  Paths are colored in graded pinks (faint outer, bright inner).
  A white median line runs through the center of the fan with glowing
  ring markers at each step. Price labels on the median line are
  staggered at different heights so they never overlap. Each label has
  a different shade of pink to distinguish different forecast moments.

LEFT PANEL — legend showing visual key, price range, GBM forecast
  terminals (HIGH, LOW, MED), and axis key.
"""

# ─────────────────────────────────────────────────────────────────────────────
# IMPORTS
# ─────────────────────────────────────────────────────────────────────────────
import asyncio
import math
import json
import base64
import random
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — CANVAS CONSTANTS
# These define the output image dimensions. Do not change.
# ─────────────────────────────────────────────────────────────────────────────
CANVAS_W      = 1400   # canvas pixel width
CANVAS_H      = 800    # canvas pixel height
DEVICE_SCALE  = 2      # Puppeteer deviceScaleFactor — output is 2800×1600 physical pixels
HDR_H         = 48     # header bar height in pixels
LEG_W         = 240    # left legend panel width in pixels

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — 3D PROJECTION CONSTANTS
#
# The chart uses a custom software 3D projection — no WebGL, no Three.js.
# All projection math runs in Canvas 2D using these exact values.
#
# World space coordinate ranges:
#   X axis: 0–400  (time dimension — history 0–200, predictions 200–400)
#   Y axis: 0–172  (price dimension — bottom to top)
#   Z axis: 0–148  (volume dimension — depth into screen)
#
# The NOW divider sits at world X = 200, always exactly at the horizontal
# midpoint of the canvas, regardless of clock time.
# ─────────────────────────────────────────────────────────────────────────────
PROJ_AY  = 0.38    # horizontal rotation angle in radians — tilts the X axis toward viewer from left
PROJ_AX  = 0.19    # vertical tilt angle in radians — makes the floor plane visible from above
PROJ_FOV = 980     # perspective field-of-view distance — higher = flatter perspective
PROJ_ZM  = 2.257   # zoom multiplier applied after projection — fills the canvas
PROJ_SCX = 470     # screen anchor X — horizontal center of the projected scene in pixels
PROJ_SCY = 540     # screen anchor Y — vertical anchor of the projected scene in pixels
WORLD_X  = 400     # world X maximum
WORLD_Y  = 172     # world Y maximum (price range maps into this)
WORLD_Z  = 148     # world Z maximum (volume maps into this)
NOW_X    = 200     # world X position of the NOW divider (always center)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — PER-CHART CONFIGURATION
#
# All three charts share the same visual system but differ in time scale,
# candle interval, GBM parameters, and label formats.
# ─────────────────────────────────────────────────────────────────────────────
CHART_CONFIGS = {
    "24H": {
        "label":        "{ticker} · 24H",   # {ticker} replaced at render time
        "badge":        "1 of 3",
        "n_candles":    50,                  # number of historical candles to display
        "candle_min":   5,                   # candle interval in minutes
        "n_steps":      20,                  # number of GBM prediction steps
        "step_min":     30,                  # each GBM step represents this many minutes
        "gbm_sigma":    0.0038,              # per-step volatility (scaled to 5-min interval)
        "gbm_mu":       -0.0001,             # per-step drift
        "n_paths":      12,                  # GBM simulation paths — always 12
        "vol_fmt":      "K",                 # volume label format: K=thousands
        "scope_line1":  "12h history  |  12h forecast",
        "scope_line2":  "5-min candles  ·  30-min GBM",
    },
    "36H": {
        "label":        "{ticker} · 36H",
        "badge":        "2 of 3",
        "n_candles":    44,
        "candle_min":   15,
        "n_steps":      18,
        "step_min":     60,
        "gbm_sigma":    0.0065,
        "gbm_mu":       -0.00014,
        "n_paths":      12,
        "vol_fmt":      "K",
        "scope_line1":  "18h history  |  18h forecast",
        "scope_line2":  "15-min candles  ·  1-hr GBM",
    },
    "15D": {
        "label":        "{ticker} · 15D",
        "badge":        "3 of 3",
        "n_candles":    30,
        "candle_min":   1440,                # 1 trading day
        "n_steps":      14,
        "step_min":     1440,
        "gbm_sigma":    0.026,
        "gbm_mu":       -0.0004,
        "n_paths":      12,
        "vol_fmt":      "M",                 # M=millions
        "scope_line1":  "~7 days history  |  ~8 days forecast",
        "scope_line2":  "Daily candles  ·  1-day GBM",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 — PINK SPECTRUM
#
# Each labeled point on the white median line gets a different shade of pink.
# This lets you visually distinguish forecast values at different time steps.
# Colors cycle by labelIndex % 6 where labelIndex counts only labeled points.
# Labeled points = every step where (stepIndex % 2 == 0) OR stepIndex == last.
# The last/MED point always uses white (SPECTRUM_MED_BORDER).
# ─────────────────────────────────────────────────────────────────────────────
PINK_SPECTRUM = [
    {"border": "rgba(255,220,240,0.95)", "glow": "rgba(255,220,240,0.7)", "name": "P1"},
    {"border": "rgba(255,170,215,0.95)", "glow": "rgba(255,170,215,0.7)", "name": "P2"},
    {"border": "rgba(255,110,185,0.95)", "glow": "rgba(255,110,185,0.7)", "name": "P3"},
    {"border": "rgba(255,60,155,0.95)",  "glow": "rgba(255,60,155,0.7)",  "name": "P4"},
    {"border": "rgba(255,140,200,0.95)", "glow": "rgba(255,140,200,0.7)", "name": "P5"},
    {"border": "rgba(200,80,180,0.95)",  "glow": "rgba(200,80,180,0.7)",  "name": "P6"},
]
SPECTRUM_MED_BORDER = "rgba(255,255,255,0.96)"  # MED terminal label always white

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 — STAGGER OFFSETS FOR PROJECTION LABELS
#
# Vertical pixel offset from each marker center to the label center.
# Negative = label appears above the marker.
# Cycles by labelIndex % 6. The last/MED label always uses OFFSET_LAST.
# This ensures no two adjacent labels overlap each other.
# ─────────────────────────────────────────────────────────────────────────────
LABEL_OFFSETS = [-130, -72, -105, -52, -145, -80]
OFFSET_LAST   = -65

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6 — GBM SIMULATION
# ─────────────────────────────────────────────────────────────────────────────
def run_gbm(
    last_close: float,
    n_steps:    int,
    n_paths:    int,
    sigma:      float,
    mu:         float,
) -> List[List[float]]:
    """
    Geometric Brownian Motion path generator.

    Parameters
    ----------
    last_close : float  — anchor price (last historical close). All paths start here.
    n_steps    : int    — number of future time steps to simulate
    n_paths    : int    — number of paths (always 12 per the visual spec)
    sigma      : float  — per-step standard deviation (already scaled to candle interval)
    mu         : float  — per-step drift (negative = slight bearish bias)

    Returns
    -------
    List of n_paths lists. Each list has n_steps+1 floats.
    Index 0 of every path = last_close (the bloom origin anchor).
    Sorted ASCENDING by terminal value: index 0 = lowest path, index 11 = highest.

    Formula per step:
        price[t] = price[t-1] * exp(mu + sigma * N(0,1))

    Price is clamped to a minimum of last_close * 0.52 to prevent
    negative or degenerate paths from breaking the chart scale.
    """
    floor = last_close * 0.52
    rng = np.random.default_rng()
    paths = []
    for _ in range(n_paths):
        path = [last_close]
        price = last_close
        for _ in range(n_steps):
            price = price * math.exp(mu + sigma * float(rng.standard_normal()))
            price = max(floor, price)
            path.append(round(price, 6))
        paths.append(path)
    # Sort ascending by terminal (last) value
    paths.sort(key=lambda p: p[-1])
    return paths


def compute_median(paths: List[List[float]]) -> List[float]:
    """
    Per-step median of all 12 paths.
    With 12 paths (indices 0–11), median = average of sorted[5] and sorted[6].
    Returns list of length n_steps+1 (same as each path).
    """
    n = len(paths[0])
    result = []
    for i in range(n):
        vals = sorted(p[i] for p in paths)
        result.append((vals[5] + vals[6]) / 2.0)
    return result

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 7 — AXIS LABEL GENERATORS
# ─────────────────────────────────────────────────────────────────────────────
_DAY_ABBR = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]
_MON_ABBR = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

def build_x_labels(
    chart_key:  str,
    n_candles:  int,
    candle_min: int,
    n_steps:    int,
    step_min:   int,
    now_ts:     float,
) -> List[str]:
    """
    Generate 7 x-axis tick labels for world X positions: 0, 67, 134, 200, 267, 334, 400.
    Position 200 always = "NOW".
    Positions < 200 = historical timestamps formatted per chart scale.
    Positions > 200 = forecast offsets e.g. "+1h", "+2d".
    """
    labels = []
    interval_ms = candle_min * 60 * 1000
    step_ms     = step_min * 60 * 1000
    for tick_wx in [0, 67, 134, 200, 267, 334, 400]:
        if tick_wx == 200:
            labels.append("NOW")
        elif tick_wx < 200:
            frac = tick_wx / 200.0
            idx  = round(frac * (n_candles - 1))
            offset_ms = (n_candles - 1 - idx) * interval_ms
            ts = datetime.fromtimestamp((now_ts * 1000 - offset_ms) / 1000, tz=timezone.utc)
            if chart_key == "24H":
                labels.append(f"{ts.hour:02d}:{ts.minute:02d}")
            elif chart_key == "36H":
                labels.append(f"{_DAY_ABBR[ts.weekday()]} {ts.hour:02d}h")
            else:  # 15D
                labels.append(f"{_MON_ABBR[ts.month-1]} {ts.day}")
        else:
            frac    = (tick_wx - 200) / 200.0
            step_i  = round(frac * (n_steps - 1))
            if chart_key == "24H":
                labels.append(f"+{step_i * step_min / 60:.1f}h")
            elif chart_key == "36H":
                labels.append(f"+{step_i}h")
            else:  # 15D
                labels.append(f"+{step_i}d")
    return labels


def build_z_labels(vol_fmt: str, max_vol: float) -> List[str]:
    """
    Generate 5 volume axis tick labels for world Z positions: 0, 37, 74, 111, 148.
    """
    labels = []
    for wz in [0, 37, 74, 111, 148]:
        v = (wz / 148.0) * max_vol
        if vol_fmt == "M":
            labels.append(f"{v/1_000_000:.1f}M")
        else:
            labels.append(f"{round(v/1000)}K")
    return labels

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 8 — CONFIG BUILDER
# Assembles the JSON payload injected into the JS chart template.
# ─────────────────────────────────────────────────────────────────────────────
def build_config(
    chart_key:     str,
    ticker:        str,
    candles:       List[Dict],
    current_price: float,
    net_move_pct:  float,
    now_ts:        float,
) -> Dict:
    """
    Build the complete config dict for one chart.
    Runs GBM, computes median, builds all axis labels.
    Returns a dict that is JSON-serialized and injected into the JS template.
    """
    cfg     = CHART_CONFIGS[chart_key]
    n_take  = cfg["n_candles"]
    candles = candles[-n_take:]  # take only the most recent n_candles

    paths   = run_gbm(
        last_close = candles[-1]["c"],
        n_steps    = cfg["n_steps"],
        n_paths    = cfg["n_paths"],
        sigma      = cfg["gbm_sigma"],
        mu         = cfg["gbm_mu"],
    )
    med     = compute_median(paths)
    max_vol = max(c["v"] for c in candles)

    return {
        "label":        cfg["label"].replace("{ticker}", ticker),
        "badge":        cfg["badge"],
        "hl":           cfg["scope_line1"],
        "sl":           cfg["scope_line2"],
        "candles":      candles,
        "paths":        paths,
        "med":          med,
        "lc":           candles[-1]["c"],
        "currentPrice": current_price,
        "deltaPct":     abs(net_move_pct),
        "deltaSign":    1 if net_move_pct >= 0 else -1,
        "xLabels":      build_x_labels(
                            chart_key, len(candles), cfg["candle_min"],
                            cfg["n_steps"], cfg["step_min"], now_ts),
        "zLabels":      build_z_labels(cfg["vol_fmt"], max_vol),
        "spectrum":     PINK_SPECTRUM,
        "offsets":      LABEL_OFFSETS,
        "offsetLast":   OFFSET_LAST,
        "specMedBorder":SPECTRUM_MED_BORDER,
    }

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 9 — JAVASCRIPT CANVAS DRAWING ENGINE
#
# This is the complete chart renderer. It runs inside a headless Chromium page.
# Python builds the CONFIG object and injects it at __CONFIG__.
# The JS draws every layer in the correct order onto an HTML5 Canvas.
#
# DRAW LAYER ORDER — do not change this order:
#  1.  Background solid fill + left edge gradient + center ambient glow
#  2.  Floor grid: vertical lines (time slices) + horizontal lines (volume slices)
#  3.  Back wall grid lines
#  4.  Volume floor bars (Z depth bars per candle)
#  5.  Sphere drop lines from price to floor
#  6.  Historical trend line through all close prices
#  7.  Historical spheres sorted far-to-near (4-layer glass sphere effect)
#  8.  Red NOW plane: outer glow + fill + dashed border + NOW label
#  9.  Bloom origin anchor: red halo + white ring + white core dot
#  10. Prediction envelope fill polygon
#  11. 12 prediction path polylines (outer/faint rank drawn first)
#  12. Median polyline
#  13. Staggered connector lines from label positions down to markers
#  14. Median marker rings at every prediction step
#  15. Pink-spectrum price labels on every-other median step (staggered heights)
#  16. Per-path terminal rings at final step of each path
#  17. Median terminal triple ring (largest marker on chart)
#  18. Terminal labels: HIGH (shifted up), LOW (shifted down), MED (centered)
#  19. Y-axis price labels — LARGE 17px bold
#  20. Three axis arrows + tick marks + labels (X=time, Y=price, Z=volume)
#  21. Legend panel
#  22. Header bar — ALWAYS DRAWN LAST
# ─────────────────────────────────────────────────────────────────────────────
_JS_TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#06080f;overflow:hidden;">
<canvas id="c"></canvas>
<script>
const CFG=__CONFIG__;
const CW=1400,CH=800,HDR=48,LEG=240;
const AY=0.38,AX=0.19,FOV=980,ZM=2.257,SCX=470,SCY=540;
const WX=400,WY=172,WZ=148,NX=200;
const cAY=Math.cos(AY),sAY=Math.sin(AY),cAX=Math.cos(AX),sAX=Math.sin(AX);
const c=document.getElementById('c'),ctx=c.getContext('2d');
c.width=CW;c.height=CH;

/* ── Projection: world(wx,wy,wz) → screen{x,y,d} ── */
function p3(wx,wy,wz){
  const x1=wx*cAY-wz*sAY,z1=wx*sAY+wz*cAY;
  const y2=wy*cAX-z1*sAX,z2=wy*sAX+z1*cAX;
  const s=FOV/(FOV+z2);
  return{x:SCX+x1*s*ZM,y:SCY-y2*s*ZM,d:z2};
}

/* ── Rounded rect path helper ── */
function rr(x,y,w,h,r){
  ctx.beginPath();ctx.moveTo(x+r,y);ctx.lineTo(x+w-r,y);
  ctx.quadraticCurveTo(x+w,y,x+w,y+r);ctx.lineTo(x+w,y+h-r);
  ctx.quadraticCurveTo(x+w,y+h,x+w-r,y+h);ctx.lineTo(x+r,y+h);
  ctx.quadraticCurveTo(x,y+h,x,y+h-r);ctx.lineTo(x,y+r);
  ctx.quadraticCurveTo(x,y,x+r,y);ctx.closePath();
}

/* ── Projection label — 20px bold, 44px pill, pink-spectrum border ── */
function projLabel(px,py,txt,spec,isMed){
  ctx.save();ctx.font='bold 20px monospace';
  const tw=ctx.measureText(txt).width,pw=tw+28,ph=44,pr=9;
  const bx=px-pw/2,by=py-ph/2;
  ctx.fillStyle='rgba(0,0,8,0.98)';rr(bx,by,pw,ph,pr);ctx.fill();
  ctx.shadowColor=isMed?'rgba(255,255,255,0.9)':spec.glow;
  ctx.shadowBlur=14;ctx.strokeStyle=isMed?CFG.specMedBorder:spec.border;
  ctx.lineWidth=2.8;rr(bx,by,pw,ph,pr);ctx.stroke();ctx.shadowBlur=0;
  ctx.fillStyle='#ffffff';ctx.textAlign='center';ctx.fillText(txt,px,py+7);
  if(!isMed){ctx.fillStyle=spec.border;ctx.beginPath();ctx.arc(bx+pw-8,by+8,5,0,Math.PI*2);ctx.fill();}
  ctx.restore();
}

/* ── Terminal label — 20px bold, 44px pill, offset sideways ── */
function termLabel(px,py,txt,col,yOff){
  ctx.save();ctx.font='bold 20px monospace';
  const tw=ctx.measureText(txt).width,pw=tw+28,ph=44,pr=9;
  const bx=px+10,by=(py+yOff)-ph/2;
  ctx.fillStyle='rgba(0,0,8,0.98)';rr(bx,by,pw,ph,pr);ctx.fill();
  ctx.shadowColor=col;ctx.shadowBlur=12;ctx.strokeStyle=col;ctx.lineWidth=2.8;
  rr(bx,by,pw,ph,pr);ctx.stroke();ctx.shadowBlur=0;
  ctx.fillStyle='#ffffff';ctx.textAlign='left';ctx.fillText(txt,bx+14,py+yOff+7);
  ctx.restore();
}

/* ── Axis label pill — big=true uses 17px (Y price axis), else 13px ── */
function axLabel(px,py,txt,col,align,big){
  ctx.save();
  const fs=big?17:13,ph=big?32:26,pad=big?10:8,pr=big?7:6,lw=big?1.8:1.3;
  ctx.font=`bold ${fs}px monospace`;
  const tw=ctx.measureText(txt).width,pw=tw+pad*2;
  const bx=align==='right'?px-pw-3:align==='center'?px-pw/2:px+4,by=py-ph/2;
  ctx.fillStyle=big?'rgba(0,0,8,0.96)':'rgba(0,0,8,0.95)';
  rr(bx,by,pw,ph,pr);ctx.fill();
  ctx.strokeStyle=col.replace(/[\d.]+\)$/,'0.55)');ctx.lineWidth=lw;
  rr(bx,by,pw,ph,pr);ctx.stroke();
  ctx.fillStyle=col;ctx.textAlign='left';ctx.fillText(txt,bx+pad,py+(big?6:5));
  ctx.restore();
}

/* ── Arrow: line + filled triangle arrowhead ── */
function arrow(a,b,col){
  ctx.strokeStyle=col;ctx.lineWidth=2.5;
  ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();
  const ang=Math.atan2(b.y-a.y,b.x-a.x);
  ctx.fillStyle=col;ctx.beginPath();ctx.moveTo(b.x,b.y);
  ctx.lineTo(b.x-15*Math.cos(ang-0.36),b.y-15*Math.sin(ang-0.36));
  ctx.lineTo(b.x-15*Math.cos(ang+0.36),b.y-15*Math.sin(ang+0.36));
  ctx.closePath();ctx.fill();
}

/* ── Unpack data ── */
const candles=CFG.candles,paths=CFG.paths,med=CFG.med,lc=CFG.lc;
const bot=paths[0],top=paths[paths.length-1];
const allP=[...candles.map(c=>c.c),...paths.flat()];
const mn=Math.min(...allP)*0.995,mx=Math.max(...allP)*1.005,PR=mx-mn;
const mxV=Math.max(...candles.map(c=>c.v));
const avV=candles.reduce((s,c)=>s+c.v,0)/candles.length;
const wT=i=>(i/(candles.length-1))*NX;
const wF=(i,n)=>NX+(i/(n-1))*(WX-NX);
const wPr=p2=>((p2-mn)/PR)*WY;
const wVl=v=>(v/mxV)*WZ;
const lvz=wVl(candles[candles.length-1].v);
const SPEC=CFG.spectrum,OFF=CFG.offsets,OFFL=CFG.offsetLast;

/* ══════════════════════════════════════════════════════════════
   LAYER 1 — BACKGROUND
══════════════════════════════════════════════════════════════ */
ctx.fillStyle='#06080f';ctx.fillRect(0,0,CW,CH);
const eg=ctx.createLinearGradient(0,0,34,0);
eg.addColorStop(0,'rgba(80,150,255,0.07)');eg.addColorStop(1,'rgba(0,0,0,0)');
ctx.fillStyle=eg;ctx.fillRect(0,0,34,CH);
const bg=ctx.createRadialGradient(CW*.55,CH*.5,80,CW*.5,CH*.5,CW*.7);
bg.addColorStop(0,'rgba(18,28,66,0.18)');bg.addColorStop(1,'rgba(0,0,0,0)');
ctx.fillStyle=bg;ctx.fillRect(0,0,CW,CH);

/* ══════════════════════════════════════════════════════════════
   LAYER 2 — FLOOR GRID
   Vertical lines (time slices). NOW column is red.
══════════════════════════════════════════════════════════════ */
ctx.setLineDash([]);
[0,67,134,NX,267,334,WX].forEach(fx=>{
  const a=p3(fx,0,0),b=p3(fx,0,WZ),isN=fx===NX;
  ctx.strokeStyle=isN?'rgba(255,60,60,0.35)':'rgba(255,255,255,0.055)';
  ctx.setLineDash(isN?[3,4]:[]);ctx.lineWidth=isN?1.4:0.55;
  ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();
});ctx.setLineDash([]);
/* Horizontal floor lines (volume/depth slices) */
[0,37,74,111,WZ].forEach(fz=>{
  const a=p3(0,0,fz),b=p3(WX,0,fz);
  ctx.strokeStyle='rgba(255,255,255,0.04)';ctx.lineWidth=0.5;
  ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();
});

/* ══════════════════════════════════════════════════════════════
   LAYER 3 — BACK WALL GRID
══════════════════════════════════════════════════════════════ */
ctx.setLineDash([2,8]);
[0,43,86,129,WY].forEach(wy=>{
  const a=p3(0,wy,0),b=p3(WX,wy,0);
  ctx.strokeStyle='rgba(255,255,255,0.03)';ctx.lineWidth=0.5;
  ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();
});ctx.setLineDash([]);

/* ══════════════════════════════════════════════════════════════
   LAYER 4 — VOLUME FLOOR BARS (Z depth per candle)
   Spike candles (vol > 2× avg) shown in red.
══════════════════════════════════════════════════════════════ */
candles.forEach((cn,i)=>{
  const bk=p3(wT(i),0,0),fr=p3(wT(i),0,wVl(cn.v));
  ctx.strokeStyle=cn.v>avV*2?'rgba(255,80,80,0.38)':'rgba(80,160,255,0.22)';
  ctx.lineWidth=2.8;ctx.beginPath();ctx.moveTo(bk.x,bk.y);ctx.lineTo(fr.x,fr.y);ctx.stroke();
});

/* ══════════════════════════════════════════════════════════════
   LAYER 5 — DROP LINES (sphere to floor)
══════════════════════════════════════════════════════════════ */
candles.forEach((cn,i)=>{
  const sp=p3(wT(i),wPr(cn.c),wVl(cn.v)),fl=p3(wT(i),0,wVl(cn.v));
  ctx.strokeStyle='rgba(80,160,255,0.07)';ctx.lineWidth=0.8;
  ctx.beginPath();ctx.moveTo(sp.x,sp.y);ctx.lineTo(fl.x,fl.y);ctx.stroke();
});

/* ══════════════════════════════════════════════════════════════
   LAYER 6 — HISTORICAL TREND LINE
   Smooth line through all historical close prices in 3D.
   Position = (wT(i), wPr(close), wVl(vol)) so it twists with volume.
══════════════════════════════════════════════════════════════ */
ctx.shadowColor='rgba(100,200,255,0.3)';ctx.shadowBlur=7;
ctx.strokeStyle='rgba(255,255,255,0.52)';ctx.lineWidth=2;ctx.beginPath();
candles.forEach((cn,i)=>{const pt=p3(wT(i),wPr(cn.c),wVl(cn.v));i===0?ctx.moveTo(pt.x,pt.y):ctx.lineTo(pt.x,pt.y);});
ctx.stroke();ctx.shadowBlur=0;

/* ══════════════════════════════════════════════════════════════
   LAYER 7 — HISTORICAL SPHERES (depth-sorted, 4 rendering layers)
   radius = 8 + (vol/maxVol) * 20   — range 8px to 28px
   Sort by projection depth d DESCENDING so nearer spheres paint on top.
══════════════════════════════════════════════════════════════ */
candles.map((cn,i)=>({...p3(wT(i),wPr(cn.c),wVl(cn.v)),r:8+(cn.v/mxV)*20,spike:cn.v>avV*2}))
.sort((a,b)=>b.d-a.d)
.forEach(({x,y,r,spike})=>{
  /* 7a — ground shadow ellipse */
  ctx.fillStyle='rgba(0,4,18,0.45)';ctx.beginPath();
  ctx.ellipse(x+r*.18,y+r*.75,r*.9,r*.26,0,0,Math.PI*2);ctx.fill();
  /* 7b — body: radial gradient from bright aqua center to dark blue edge */
  const g=ctx.createRadialGradient(x-r*.3,y-r*.36,r*.04,x,y,r);
  g.addColorStop(0,'rgba(190,242,255,0.98)');g.addColorStop(.2,'rgba(85,192,255,0.92)');
  g.addColorStop(.56,'rgba(22,94,215,0.74)');g.addColorStop(1,'rgba(4,16,80,0.22)');
  ctx.fillStyle=g;ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();
  /* 7c — rim highlight */
  ctx.strokeStyle='rgba(148,222,255,0.4)';ctx.lineWidth=0.9;
  ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.stroke();
  /* 7d — specular gloss (upper-left hot spot) */
  const gs=ctx.createRadialGradient(x-r*.33,y-r*.4,0,x-r*.18,y-r*.22,r*.54);
  gs.addColorStop(0,'rgba(255,255,255,0.74)');gs.addColorStop(.4,'rgba(255,255,255,0.14)');gs.addColorStop(1,'rgba(255,255,255,0)');
  ctx.fillStyle=gs;ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();
  /* 7e — VOL spike flag above the sphere */
  if(spike){
    ctx.strokeStyle='rgba(255,80,80,0.52)';ctx.lineWidth=1.2;
    ctx.beginPath();ctx.moveTo(x,y-r-2);ctx.lineTo(x,y-r-16);ctx.stroke();
    ctx.fillStyle='rgba(255,80,80,0.84)';ctx.fillRect(x+1,y-r-30,30,14);
    ctx.fillStyle='#fff';ctx.font='bold 9px monospace';ctx.textAlign='left';
    ctx.fillText('VOL',x+5,y-r-19);
  }
});

/* ══════════════════════════════════════════════════════════════
   LAYER 8 — RED NOW PLANE
   Translucent red vertical plane at world X = NOW_X = 200.
   Four corners: (200,172,0), (200,172,148), (200,0,148), (200,0,0)
══════════════════════════════════════════════════════════════ */
const nBL=p3(NX,0,0),nBF=p3(NX,0,WZ),nTF=p3(NX,WY,WZ),nTL=p3(NX,WY,0);
const nowPoly=()=>{ctx.beginPath();ctx.moveTo(nTL.x,nTL.y);ctx.lineTo(nTF.x,nTF.y);ctx.lineTo(nBF.x,nBF.y);ctx.lineTo(nBL.x,nBL.y);ctx.closePath();};
/* outer red glow */
ctx.shadowColor='rgba(255,40,40,0.4)';ctx.shadowBlur=28;ctx.fillStyle='rgba(220,30,30,0.07)';nowPoly();ctx.fill();ctx.shadowBlur=0;
/* main fill */
ctx.fillStyle='rgba(255,50,50,0.06)';nowPoly();ctx.fill();
/* dashed red border */
ctx.strokeStyle='rgba(255,70,70,0.5)';ctx.lineWidth=1.5;ctx.setLineDash([3,5]);nowPoly();ctx.stroke();ctx.setLineDash([]);
/* NOW label above the plane */
const nLp=p3(NX,WY+26,WZ*.5);axLabel(nLp.x,nLp.y,'◈ NOW','rgba(255,120,120,0.97)','center',false);

/* ══════════════════════════════════════════════════════════════
   LAYER 9 — BLOOM ORIGIN ANCHOR
   Three concentric rings at p3(200, wPr(lastClose), lvz).
   This is the exact pixel where all 12 GBM paths begin.
══════════════════════════════════════════════════════════════ */
const bl=p3(NX,wPr(lc),lvz);
ctx.shadowColor='rgba(255,80,80,0.5)';ctx.shadowBlur=22;
ctx.strokeStyle='rgba(255,80,80,0.18)';ctx.lineWidth=7;ctx.beginPath();ctx.arc(bl.x,bl.y,22,0,Math.PI*2);ctx.stroke();ctx.shadowBlur=0;
ctx.strokeStyle='rgba(255,255,255,0.76)';ctx.lineWidth=2.6;ctx.beginPath();ctx.arc(bl.x,bl.y,12,0,Math.PI*2);ctx.stroke();
ctx.fillStyle='rgba(255,255,255,0.99)';ctx.beginPath();ctx.arc(bl.x,bl.y,6.5,0,Math.PI*2);ctx.fill();

/* ══════════════════════════════════════════════════════════════
   LAYER 10 — PREDICTION ENVELOPE FILL
   Polygon from top path to bottom path — faint pink fog.
══════════════════════════════════════════════════════════════ */
ctx.fillStyle='rgba(255,100,180,0.055)';ctx.beginPath();
top.forEach((v,i)=>{const pt=p3(wF(i,top.length),wPr(v),lvz);i===0?ctx.moveTo(pt.x,pt.y):ctx.lineTo(pt.x,pt.y);});
for(let i=bot.length-1;i>=0;i--){const pt=p3(wF(i,bot.length),wPr(bot[i]),lvz);ctx.lineTo(pt.x,pt.y);}
ctx.closePath();ctx.fill();

/* ══════════════════════════════════════════════════════════════
   LAYER 11 — PREDICTION PATHS
   12 polylines. rank = min(pathIndex, 11-pathIndex): 0=outer faint, 5=inner bright.
   Draw outermost (rank 0) first so inner paths paint on top.
══════════════════════════════════════════════════════════════ */
const pC=['rgba(255,60,140,0.14)','rgba(255,82,162,0.22)','rgba(255,102,182,0.32)',
          'rgba(255,122,197,0.43)','rgba(255,148,212,0.55)','rgba(255,172,228,0.72)'];
paths.forEach((path,pi)=>{
  ctx.strokeStyle=pC[Math.min(pi,paths.length-1-pi)];ctx.lineWidth=1.4;
  ctx.beginPath();path.forEach((v,i)=>{const pt=p3(wF(i,path.length),wPr(v),lvz);i===0?ctx.moveTo(pt.x,pt.y):ctx.lineTo(pt.x,pt.y);});
  ctx.stroke();
});

/* ══════════════════════════════════════════════════════════════
   LAYER 12 — MEDIAN LINE
   White polyline connecting the per-step median of all 12 paths.
══════════════════════════════════════════════════════════════ */
ctx.shadowColor='rgba(255,255,255,0.32)';ctx.shadowBlur=13;
ctx.strokeStyle='rgba(255,255,255,0.96)';ctx.lineWidth=3;ctx.beginPath();
med.forEach((v,i)=>{const pt=p3(wF(i,med.length),wPr(v),lvz);i===0?ctx.moveTo(pt.x,pt.y):ctx.lineTo(pt.x,pt.y);});
ctx.stroke();ctx.shadowBlur=0;

/* Build labeled points: every even-indexed step + always the last step */
const labeled=[];
med.forEach((v,i)=>{
  if(i%2===0||i===med.length-1)
    labeled.push({pt:p3(wF(i,med.length),wPr(v),lvz),v,isLast:i===med.length-1,li:labeled.length});
});

/* ══════════════════════════════════════════════════════════════
   LAYER 13 — CONNECTOR LINES (drawn before markers so they sit behind)
   Dashed line from label center down to the marker ring.
   Anchor dot where connector meets marker.
══════════════════════════════════════════════════════════════ */
labeled.forEach(({pt,isLast,li})=>{
  const spec=SPEC[li%6],off=isLast?OFFL:OFF[li%6],ly=pt.y+off;
  ctx.strokeStyle=isLast?'rgba(255,255,255,0.32)':spec.glow.replace('0.7)','0.35)');
  ctx.lineWidth=1.3;ctx.setLineDash([4,5]);
  ctx.beginPath();ctx.moveTo(pt.x,pt.y-15);ctx.lineTo(pt.x,ly+22);ctx.stroke();ctx.setLineDash([]);
  ctx.fillStyle=isLast?'rgba(255,255,255,0.55)':spec.border;
  ctx.beginPath();ctx.arc(pt.x,ly+22,4,0,Math.PI*2);ctx.fill();
});

/* ══════════════════════════════════════════════════════════════
   LAYER 14 — MEDIAN MARKER RINGS at every step
   3 concentric rings: outer halo, mid ring, glowing core.
══════════════════════════════════════════════════════════════ */
med.forEach((v,i)=>{
  const pt=p3(wF(i,med.length),wPr(v),lvz);
  ctx.strokeStyle='rgba(255,255,255,0.07)';ctx.lineWidth=8;ctx.beginPath();ctx.arc(pt.x,pt.y,21,0,Math.PI*2);ctx.stroke();
  ctx.strokeStyle='rgba(255,255,255,0.6)';ctx.lineWidth=2.4;ctx.beginPath();ctx.arc(pt.x,pt.y,12,0,Math.PI*2);ctx.stroke();
  const dg=ctx.createRadialGradient(pt.x-2,pt.y-2,0,pt.x,pt.y,6.5);
  dg.addColorStop(0,'rgba(255,255,255,1)');dg.addColorStop(.5,'rgba(210,240,255,0.96)');dg.addColorStop(1,'rgba(130,200,255,0.82)');
  ctx.fillStyle=dg;ctx.beginPath();ctx.arc(pt.x,pt.y,6.5,0,Math.PI*2);ctx.fill();
});

/* ══════════════════════════════════════════════════════════════
   LAYER 15 — STAGGERED PINK-SPECTRUM PRICE LABELS
   Each labeled point gets a different pink shade + staggered height.
   Small colored dot in top-right corner of each pill = spectrum indicator.
══════════════════════════════════════════════════════════════ */
labeled.forEach(({pt,v,isLast,li})=>{
  const spec=SPEC[li%6],off=isLast?OFFL:OFF[li%6];
  projLabel(pt.x,pt.y+off,(isLast?'MED ':'')+'$'+v.toFixed(3),spec,isLast);
});

/* ══════════════════════════════════════════════════════════════
   LAYER 16 — PER-PATH TERMINAL RINGS
   One ring at the last step of each of the 12 paths.
   Color grades from faint (outer paths) to brighter pink (inner paths).
══════════════════════════════════════════════════════════════ */
paths.forEach((path,pi)=>{
  const pt=p3(wF(path.length-1,path.length),wPr(path[path.length-1]),lvz);
  const d=Math.min(pi,paths.length-1-pi);
  ctx.strokeStyle=`rgba(255,${128+d*12},${172+d*9},${(.22+d*.06).toFixed(2)})`;
  ctx.lineWidth=2;ctx.beginPath();ctx.arc(pt.x,pt.y,8,0,Math.PI*2);ctx.stroke();
});

/* ══════════════════════════════════════════════════════════════
   LAYER 17 — MEDIAN TERMINAL TRIPLE RING
   The largest and most prominent marker on the chart.
   3 rings: outer halo (r=30), mid ring (r=18), solid core (r=8).
══════════════════════════════════════════════════════════════ */
const tmPt=p3(wF(med.length-1,med.length),wPr(med[med.length-1]),lvz);
ctx.shadowColor='rgba(255,255,255,0.55)';ctx.shadowBlur=20;
ctx.strokeStyle='rgba(255,255,255,0.11)';ctx.lineWidth=9;ctx.beginPath();ctx.arc(tmPt.x,tmPt.y,30,0,Math.PI*2);ctx.stroke();ctx.shadowBlur=0;
ctx.strokeStyle='rgba(255,255,255,0.7)';ctx.lineWidth=3;ctx.beginPath();ctx.arc(tmPt.x,tmPt.y,18,0,Math.PI*2);ctx.stroke();
ctx.fillStyle='rgba(255,255,255,1)';ctx.beginPath();ctx.arc(tmPt.x,tmPt.y,8,0,Math.PI*2);ctx.fill();

/* ══════════════════════════════════════════════════════════════
   LAYER 18 — TERMINAL PRICE LABELS
   HIGH shifted 32px UP from terminal ring center.
   LOW shifted 32px DOWN from terminal ring center.
   MED centered at terminal ring, placed to the right.
══════════════════════════════════════════════════════════════ */
const tTpt=p3(wF(top.length-1,top.length),wPr(top[top.length-1]),lvz);
const tBpt=p3(wF(bot.length-1,bot.length),wPr(bot[bot.length-1]),lvz);
termLabel(tTpt.x,tTpt.y,'▲ $'+top[top.length-1].toFixed(3),'rgba(255,148,212,0.95)',-32);
termLabel(tBpt.x,tBpt.y,'▼ $'+bot[bot.length-1].toFixed(3),'rgba(255,148,212,0.95)',+32);
termLabel(tmPt.x,tmPt.y,'MED $'+med[med.length-1].toFixed(3),'rgba(255,255,255,0.95)',0);

/* ══════════════════════════════════════════════════════════════
   LAYER 19 — Y AXIS PRICE LABELS  (LARGE — bold 17px)
   5 tick marks at world Y: 0, 43, 86, 129, 172.
   Green colored pills, right-aligned on the left side of the scene.
══════════════════════════════════════════════════════════════ */
[0,43,86,129,WY].forEach(wy=>{
  const t=p3(0,wy,0);
  axLabel(t.x-8,t.y,'$'+(mn+wy/WY*PR).toFixed(3),'rgba(90,230,140,0.97)','right',true);
});

/* ══════════════════════════════════════════════════════════════
   LAYER 20 — THREE AXES
   X=time (blue), Y=price (green), Z=volume (amber).
   Each has an arrowhead + tick marks + dark-pill labels.
   X tick labels color: history=blue, NOW=red, future=pink.
══════════════════════════════════════════════════════════════ */
const O=p3(0,0,0),Ax=p3(450,0,0),Ay=p3(0,214,0),Az=p3(0,0,204);
arrow(O,Ax,'rgba(80,162,255,0.9)');
ctx.fillStyle='rgba(80,162,255,0.99)';ctx.font='bold 14px monospace';ctx.textAlign='left';ctx.fillText('TIME →',Ax.x+11,Ax.y+5);
/* X ticks */
[0,67,134,NX,267,334,WX].forEach((wx,ti)=>{
  if(!wx)return;
  const t=p3(wx,0,0),te=p3(wx,-16,0),lp=p3(wx,-44,0);
  ctx.strokeStyle='rgba(80,162,255,0.45)';ctx.lineWidth=1.2;
  ctx.beginPath();ctx.moveTo(t.x,t.y);ctx.lineTo(te.x,te.y);ctx.stroke();
  const col=wx===NX?'rgba(255,120,120,0.97)':wx>NX?'rgba(255,148,212,0.96)':'rgba(90,162,255,0.96)';
  axLabel(lp.x,lp.y,CFG.xLabels[ti===0?0:ti-0]||'',col,'center',false);
});
/* Correct X label indexing — 7 positions, skip index 0 tick mark but include label */
[0,67,134,NX,267,334,WX].forEach((wx,ti)=>{
  const lp=p3(wx,-44,0);
  const col=wx===NX?'rgba(255,120,120,0.97)':wx>NX?'rgba(255,148,212,0.96)':'rgba(90,162,255,0.96)';
  if(CFG.xLabels[ti])axLabel(lp.x,lp.y,CFG.xLabels[ti],col,'center',false);
});
/* Y axis */
arrow(O,Ay,'rgba(80,225,130,0.9)');
ctx.fillStyle='rgba(80,225,130,0.99)';ctx.font='bold 14px monospace';ctx.textAlign='right';ctx.fillText('PRICE',Ay.x-9,Ay.y-13);
/* Z axis */
arrow(O,Az,'rgba(255,178,55,0.9)');
ctx.fillStyle='rgba(255,178,55,0.99)';ctx.font='bold 14px monospace';ctx.textAlign='right';ctx.fillText('VOLUME',Az.x-8,Az.y+5);
[0,37,74,111,WZ].forEach((wz,zi)=>{
  const t=p3(0,0,wz),te=p3(-16,0,wz);
  ctx.strokeStyle='rgba(255,178,55,0.45)';ctx.lineWidth=1.2;
  ctx.beginPath();ctx.moveTo(t.x,t.y);ctx.lineTo(te.x,te.y);ctx.stroke();
  if(CFG.zLabels[zi])axLabel(te.x-5,t.y,CFG.zLabels[zi],'rgba(255,178,55,0.97)','right',false);
});
ctx.fillStyle='rgba(255,255,255,0.8)';ctx.beginPath();ctx.arc(O.x,O.y,5,0,Math.PI*2);ctx.fill();

/* ══════════════════════════════════════════════════════════════
   LAYER 21 — LEFT LEGEND PANEL
══════════════════════════════════════════════════════════════ */
const lx=8,ly=HDR+8,lw=LEG-16,lh=CH-HDR-16;
ctx.fillStyle='rgba(0,0,8,0.93)';ctx.beginPath();ctx.roundRect(lx,ly,lw,lh,10);ctx.fill();
ctx.strokeStyle='rgba(255,255,255,0.16)';ctx.lineWidth=1.5;ctx.beginPath();ctx.roundRect(lx,ly,lw,lh,10);ctx.stroke();
const px=lx+16;let cy=ly+24;
const ldiv=()=>{ctx.strokeStyle='rgba(255,255,255,0.12)';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(lx+8,cy);ctx.lineTo(lx+lw-8,cy);ctx.stroke();cy+=14;};
const lhd=t=>{ctx.fillStyle='rgba(255,255,255,0.38)';ctx.font='bold 11px monospace';ctx.textAlign='left';ctx.fillText(t,px,cy);cy+=16;};
const lfp=(lbl,val,col)=>{
  ctx.fillStyle='rgba(255,255,255,0.5)';ctx.font='bold 11px monospace';ctx.fillText(lbl,px,cy);cy+=14;
  ctx.fillStyle='rgba(0,0,8,0.95)';ctx.beginPath();ctx.roundRect(px,cy,lw-28,28,6);ctx.fill();
  ctx.strokeStyle=col.replace(/[\d.]+\)$/,'0.6)');ctx.lineWidth=1.8;ctx.beginPath();ctx.roundRect(px,cy,lw-28,28,6);ctx.stroke();
  ctx.fillStyle=col;ctx.font='bold 15px monospace';ctx.fillText('$'+val.toFixed(3),px+10,cy+20);cy+=38;
};
const llr=(fn,lbl)=>{fn(px+2,cy-2);ctx.fillStyle='rgba(255,255,255,0.9)';ctx.font='bold 13px monospace';ctx.textAlign='left';ctx.fillText(lbl,px+28,cy+5);cy+=26;};
/* Ticker and scope */
ctx.fillStyle='#fff';ctx.font='bold 20px monospace';ctx.textAlign='left';ctx.fillText(CFG.label.split('·')[0].trim(),px,cy);
ctx.fillStyle='rgba(255,255,255,0.42)';ctx.font='11px monospace';ctx.fillText('  '+CFG.badge,px+52,cy);cy+=22;
ctx.fillStyle='rgba(255,255,255,0.72)';ctx.font='12px monospace';ctx.fillText(CFG.hl,px,cy);cy+=18;
ctx.fillStyle='rgba(255,255,255,0.5)';ctx.font='11px monospace';ctx.fillText(CFG.sl,px,cy);cy+=24;
/* Visual key */
ldiv();lhd('VISUAL KEY');
llr((x,y)=>{const rg=ctx.createRadialGradient(x+10,y,1,x+10,y,10);rg.addColorStop(0,'rgba(190,242,255,0.95)');rg.addColorStop(.5,'rgba(80,180,255,0.8)');rg.addColorStop(1,'rgba(20,80,200,0.3)');ctx.fillStyle=rg;ctx.beginPath();ctx.arc(x+10,y,10,0,Math.PI*2);ctx.fill();},'Price Spheres');
llr((x,y)=>{ctx.strokeStyle='rgba(255,255,255,0.65)';ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+22,y);ctx.stroke();},'Trend Line');
llr((x,y)=>{ctx.fillStyle='rgba(80,160,255,0.4)';ctx.fillRect(x,y-8,22,14);},'Volume (Z)');
llr((x,y)=>{['rgba(255,172,228,0.75)','rgba(255,122,197,0.5)','rgba(255,80,160,0.3)'].forEach((cl,fi)=>{ctx.strokeStyle=cl;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+22,y+[-8,0,8][fi]);ctx.stroke();});},'12 GBM Paths');
llr((x,y)=>{ctx.strokeStyle='rgba(255,255,255,0.6)';ctx.lineWidth=2.2;ctx.beginPath();ctx.arc(x+10,y,9,0,Math.PI*2);ctx.stroke();ctx.fillStyle='rgba(255,255,255,0.98)';ctx.beginPath();ctx.arc(x+10,y,4.5,0,Math.PI*2);ctx.fill();},'Median Path');
llr((x,y)=>{ctx.fillStyle='rgba(255,50,50,0.08)';ctx.fillRect(x,y-10,22,18);ctx.strokeStyle='rgba(255,70,70,0.55)';ctx.lineWidth=1.5;ctx.setLineDash([3,4]);ctx.strokeRect(x,y-10,22,18);ctx.setLineDash([]);},'NOW Plane (red)');
/* Spectrum swatches */
cy+=4;lhd('LABEL SPECTRUM');
SPEC.forEach((sp,si)=>{
  ctx.fillStyle='rgba(0,0,8,0.9)';ctx.beginPath();ctx.roundRect(px+si*34,cy,28,18,4);ctx.fill();
  ctx.strokeStyle=sp.border;ctx.lineWidth=1.5;ctx.beginPath();ctx.roundRect(px+si*34,cy,28,18,4);ctx.stroke();
  ctx.fillStyle=sp.border;ctx.font='bold 8px monospace';ctx.textAlign='center';
  ctx.fillText(sp.name,px+si*34+14,cy+12);
});cy+=28;
/* Price range */
cy+=4;ldiv();lhd('PRICE RANGE');
ctx.fillStyle='rgba(90,230,140,0.97)';ctx.font='bold 14px monospace';
ctx.fillText('HIGH  $'+mx.toFixed(3),px,cy);cy+=20;ctx.fillText('LOW   $'+mn.toFixed(3),px,cy);cy+=24;
/* Forecast */
ldiv();lhd('GBM FORECAST');
lfp('Median',med[med.length-1],'rgba(255,255,255,0.97)');
lfp('High ▲',top[top.length-1],'rgba(255,168,218,0.97)');
lfp('Low  ▼',bot[bot.length-1],'rgba(255,168,218,0.97)');
/* Axes */
cy+=4;ldiv();lhd('AXES');
[['X   TIME →','rgba(80,162,255,0.97)'],['Y   PRICE ↑','rgba(90,230,140,0.97)'],['Z   VOLUME →','rgba(255,178,55,0.97)']].forEach(([t,cl])=>{
  ctx.fillStyle=cl;ctx.font='bold 13px monospace';ctx.fillText(t,px,cy);cy+=20;
});
ctx.fillStyle='rgba(255,255,255,0.2)';ctx.font='10px monospace';ctx.fillText('TwelveData · Finnhub',px,CH-14);

/* ══════════════════════════════════════════════════════════════
   LAYER 22 — HEADER BAR  (ALWAYS DRAWN LAST)
══════════════════════════════════════════════════════════════ */
ctx.fillStyle='rgba(0,0,8,0.9)';ctx.fillRect(0,0,CW,HDR);
ctx.strokeStyle='rgba(255,255,255,0.1)';ctx.lineWidth=1;
ctx.beginPath();ctx.moveTo(0,HDR);ctx.lineTo(CW,HDR);ctx.stroke();
ctx.fillStyle='rgba(255,255,255,0.5)';ctx.font='12px monospace';ctx.textAlign='left';
ctx.fillText(CFG.label+'  ·  3D        X: TIME    Y: PRICE    Z: VOLUME',LEG+14,30);
ctx.fillStyle='#ffffff';ctx.font='bold 18px monospace';ctx.textAlign='right';
ctx.fillText('$'+CFG.currentPrice.toFixed(3),CW-120,30);
ctx.fillStyle=CFG.deltaSign>=0?'#00ffaa':'#ff4466';ctx.font='bold 14px monospace';
ctx.fillText((CFG.deltaSign>=0?'+':'')+CFG.deltaPct.toFixed(2)+'%',CW-6,30);
ctx.fillStyle='rgba(255,255,255,0.08)';ctx.beginPath();ctx.roundRect(CW-78,8,30,26,13);ctx.fill();
ctx.strokeStyle='rgba(255,255,255,0.25)';ctx.lineWidth=1;ctx.beginPath();ctx.roundRect(CW-78,8,30,26,13);ctx.stroke();
ctx.fillStyle='rgba(255,255,255,0.65)';ctx.font='bold 9px monospace';ctx.textAlign='center';
ctx.fillText(CFG.badge,CW-63,25);

window.__chartReady=true;
</script></body></html>"""

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 10 — PUPPETEER RENDERER
# Renders one HTML page to PNG bytes. One browser page per chart.
# ─────────────────────────────────────────────────────────────────────────────
async def _render_one(config: Dict) -> bytes:
    """
    Inject config into the JS template, render with headless Chromium,
    screenshot to PNG. Returns raw bytes.

    Raises AssertionError if the PNG buffer is suspiciously small
    (indicating a render failure).
    """
    try:
        from pyppeteer import launch
    except ImportError:
        raise ImportError(
            "\n\nMissing dependency: pyppeteer\n"
            "Install with:  pip install pyppeteer\n"
            "Then fetch Chromium:  python -m pyppeteer fetch\n"
        )

    html = _JS_TEMPLATE.replace("__CONFIG__", json.dumps(config, default=float))

    browser = await launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
        ],
    )
    page = await browser.newPage()
    await page.setViewport({
        "width":             CANVAS_W,
        "height":            CANVAS_H,
        "deviceScaleFactor": DEVICE_SCALE,
    })
    await page.setContent(html, {"waitUntil": "networkidle0"})
    await page.waitForFunction("window.__chartReady === true", {"timeout": 15000})
    png_bytes = await page.screenshot({"type": "png", "omitBackground": False})
    await page.close()
    await browser.close()

    assert len(png_bytes) > 80_000, (
        f"PNG buffer is only {len(png_bytes)} bytes — chart render likely failed. "
        "Check Chromium installation and canvas drawing errors."
    )
    return png_bytes

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 11 — PUBLIC API
# This is the function you call from your alert system.
# ─────────────────────────────────────────────────────────────────────────────
async def render_all_charts(
    ticker:        str,
    candles_5m:    List[Dict],
    candles_15m:   List[Dict],
    candles_daily: List[Dict],
    current_price: float,
    prev_close:    float,
    net_move_pct:  float,
    now_ts:        Optional[float] = None,
) -> Tuple[bytes, bytes, bytes]:
    """
    Render all three charts for the given ticker and return PNG bytes.

    Parameters
    ----------
    ticker        : str   — e.g. "SES", "AAPL", "BTC-USD". Used in chart labels.
    candles_5m    : list  — at least 50 five-minute candles, oldest first
    candles_15m   : list  — at least 44 fifteen-minute candles, oldest first
    candles_daily : list  — at least 30 daily candles, oldest first
    current_price : float — live price shown in header
    prev_close    : float — prior day close (used for delta calculation)
    net_move_pct  : float — percentage change, can be positive or negative
    now_ts        : float — optional unix timestamp in seconds (defaults to now)

    Returns
    -------
    Tuple of three bytes objects: (chart_24h, chart_36h, chart_15d)
    Each is a complete PNG file ready for base64 encoding and email attachment.

    Each candle dict must have keys: o, h, l, c, v (open, high, low, close, volume)
    """
    if now_ts is None:
        now_ts = datetime.now(timezone.utc).timestamp()

    chart_inputs = [
        ("24H", candles_5m),
        ("36H", candles_15m),
        ("15D", candles_daily),
    ]

    results = []
    for chart_key, raw_candles in chart_inputs:
        config = build_config(
            chart_key     = chart_key,
            ticker        = ticker,
            candles       = raw_candles,
            current_price = current_price,
            net_move_pct  = net_move_pct,
            now_ts        = now_ts,
        )
        png = await _render_one(config)
        results.append(png)

    return tuple(results)  # type: ignore

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 12 — STANDALONE TEST
#
# Run this file directly to verify the full pipeline works:
#
#     python quant_chart_renderer.py
#
# This generates three PNG files using simulated data for a generic ticker.
# Open the output files and visually confirm:
#   - Three separate chart images (not merged)
#   - Red NOW plane visible in the center of each chart
#   - Glass spheres on the left half
#   - Pink fan of GBM paths on the right half
#   - White median line with staggered colored labels
#   - Legend on the left with all sections populated
#   - Header shows ticker, price, and delta
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":

    def _fake_candles(n: int, vol_base: int, vol_range: int,
                      start_price: float = 1.05) -> List[Dict]:
        """Generate synthetic candles for testing. Not used in production."""
        candles, price = [], start_price
        for _ in range(n):
            o   = price
            mv  = (random.random() - 0.51) * 0.009
            c   = max(start_price * 0.78, min(start_price * 1.22, o + mv))
            h   = max(o, c) + random.random() * 0.003
            l   = min(o, c) - random.random() * 0.003
            v   = vol_base + random.random() * vol_range * (3.0 if random.random() < 0.07 else 1.0)
            candles.append({"o": round(o,4), "h": round(h,4),
                            "l": round(l,4), "c": round(c,4), "v": int(v)})
            price = c
        return candles

    async def _test():
        TICKER = "TEST"  # Replace with any ticker for the visual test

        c5m    = _fake_candles(55,  22000,   62000)
        c15m   = _fake_candles(48,  50000,  180000)
        cdaily = _fake_candles(35, 900000, 3100000)

        lc  = c5m[-1]["c"]
        pc  = c5m[0]["o"]
        pct = (lc - pc) / pc * 100.0

        print(f"Rendering charts for {TICKER} — current price ${lc:.4f}  Δ{pct:+.3f}%")

        chart_24h, chart_36h, chart_15d = await render_all_charts(
            ticker        = TICKER,
            candles_5m    = c5m,
            candles_15m   = c15m,
            candles_daily = cdaily,
            current_price = lc,
            prev_close    = pc,
            net_move_pct  = pct,
        )

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        for name, buf in [
            (f"{TICKER}_24H_{ts}.png", chart_24h),
            (f"{TICKER}_36H_{ts}.png", chart_36h),
            (f"{TICKER}_15D_{ts}.png", chart_15d),
        ]:
            with open(name, "wb") as fh:
                fh.write(buf)
            print(f"  Saved {name}  ({len(buf):,} bytes)")

        print("\nDone. Open the three PNG files to verify the charts look correct.")
        print("If Chromium is not installed yet, run:  python -m pyppeteer fetch")

    asyncio.run(_test())

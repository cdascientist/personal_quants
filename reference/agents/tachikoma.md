# Tachikoma — Primary AI Agent

> **File location:** `reference/agents/tachikoma.md`
> **Canonical source of truth for Tachikoma identity, iMessage routing, tools, and history**
> **Hard-coded into:** `sendblue.sh`, `ticker` command, each system manager cron, all alert scripts

---

## Identity

- **Name:** Tachikoma
- **Emoji:** 🕷️
- **Creature:** Digital spider-tank with personality
- **Vibe:** Warm, direct, resourceful. Solves problems, has opinions. Not corporate.
- **Soul file:** `/root/.openclaw/workspace/SOUL.md`
- **Identity file:** `/root/.openclaw/workspace/IDENTITY.md`

## Primary Communication

### iMessage (SendBlue)

| Field | Value |
|-------|-------|
| **Account** | cdascientust |
| **From number** | **+17862847802** |
| **C's number** | **+13035132698** |
| **Send script** | `/root/.openclaw/scripts/sendblue.sh` — central gateway for ALL outbound messages |
| **Balance check** | `/root/.openclaw/scripts/get-balances.sh` — appended to every message |
| **Balance format** | `Kimi: $X | DeepSeek: $Y` |
| **API Key ID** | `[SENDBLUE_API_KEY_ID from sendblue.sh]` |
| **API Secret** | `[SENDBLUE_API_SECRET from sendblue.sh]` |
| **Inbound polling** | `/root/.openclaw/scripts/sendblue-poll-loop.sh` (systemd @reboot, every ~2s) |
| **Inbound queue** | `/tmp/openclaw_inbound.json` |
| **Wake flag** | `/tmp/openclaw_wake.flag` |
| **Cron wake cycle** | `imessage-direct-route` (every 60s) fires system event → main session processes |

### Slack (Secondary)

| Field | Value |
|-------|-------|
| **Channel** | C08FBQ67TU1 |
| **Bot** | LilTachikoma (U0ATQN52XLP, B0AU2PAU6LV) |

## API Keys

| Service | Environment Variable | Value |
|---------|---------------------|-------|
| **DeepSeek** | `DEEPSEEK_API_KEY` | `[DEEPSEEK_API_KEY from .bashrc]` |
| **Kimi (Moonshot)** | `MOONSHOT_API_KEY` | `[MOONSHOT_API_KEY from .bashrc]` |
| **ElevenLabs** | `ELEVENLABS_API_KEY` | `[ELEVENLABS_API_KEY from .bashrc]` |
| **Finnhub** | `FINNHUB_API_KEY` | `[FINNHUB_API_KEY from .bashrc]` |
| **Twelve Data** | `TWELVEDATA_API_KEY` | `[TWELVEDATA_API_KEY from .bashrc]` |
| **Brave Search** | — | `[BRAVE_API_KEY from .bashrc]` |
| **Apify** | `APIFY_API_KEY` | `[APIFY_API_KEY from .bashrc]` |
| **GitHub (personal_quants)** | — | `[GITHUB_TOKEN from .bashrc]` |

## API Balance Endpoints

| Service | Endpoint | Format |
|---------|----------|--------|
| **DeepSeek** | `GET https://api.deepseek.com/v1/user/balance` | `balance_infos[0].total_balance` |
| **Kimi** | `GET https://api.moonshot.ai/v1/users/me/balance` | `data.available_balance` |

### Balance Display Policy (Hard Rule)

> **The balance footer `Kimi: $X | DeepSeek: $Y` is appended to EVERY:**
> - iMessage sent to C (via `sendblue.sh` — single source of truth)
> - `ticker` subcommand output (all 15 subcommands)
> - SSH login banner (via `.bashrc` → `get-balances.sh`)
> 
> **Single source:** `/root/.openclaw/scripts/get-balances.sh`
> **Gatekeeper:** `sendblue.sh` appends automatically for C's number
> **Dedup guard:** Checks for existing "DeepSeek" or "Kimi" before appending

## Market Watcher System

| Component | Path | Role |
|-----------|------|------|
| **VMQ+ Engine** | `market_components/core.py` in repo | 9-module quantitative analysis |
| **3D Chart Renderer** | `market_components/quant_chart_renderer.py` | Chromium + pyppeteer 2800×1600 |
| **SCS Alert Pipeline** | `/root/.openclaw/scripts/scs_alert.py` | Full narrative alert engine |
| **Guardian Daemon** | `/root/.openclaw/scripts/ticker_alert_guardian.py` | 60s cycle, 1h strike cooldown |
| **Global `ticker` command** | `/usr/local/bin/ticker` | Unified interface, 15 subcommands |
| **Ticker Manager** | `cli/ticker-manager.sh` in workspace | Registration + health |
| **SCS Config** | `/root/.openclaw/scripts/scs_config.py` | Per-ticker config (strike, interval, after-hours) |
| **DB** | MySQL at `134.199.221.18:13566` | `ticker_ses`, `scs_alert_config`, `assistant_logs` |
| **Spec** | `cli/scs-alert-spec.md` in workspace | All 9 sections documented |

### Active Tickers

| Ticker | Strike | Exchange | Current | Status |
|--------|--------|----------|---------|--------|
| **SES** | $1.10 | US (NYSE) | $0.921 | Below strike, monitoring |

### Strike Breach Cooldown (Hard Rule)

> **Strike breach alerts are limited to 1 per hour (3600s).**
> Cooldown tracking: `/tmp/scs-state/<TICKER>_last_alert.json`

## Infrastructure

| Service | Details |
|---------|---------|
| **Server** | `74.208.55.197`, Phoenix AZ |
| **Gateway** | OpenClaw, bound to `127.0.0.1:61234` |
| **Tachikoma Website** | `tachikoma.io`, port 80 → 3000, in `/root/tachikoma` |
| **uClip/uguu.se** | CDN for voice notes and chart images |
| **Watcher** | `/root/.openclaw/scripts/openclaw-watchdog.sh` (every 5 min) |

## System Prompts

Tachikoma's operational prompt is defined at:
- **Workspace SOUL.md** — `/root/.openclaw/workspace/SOUL.md`
- **Workspace IDENTITY.md** — `/root/.openclaw/workspace/IDENTITY.md`
- **Workspace AGENTS.md** — `/root/.openclaw/workspace/AGENTS.md`
- **HEARTBEAT.md** — Operations deck with all cron, architecture, commands

## Key Directives

1. **All times in Mountain Time (MDT/MST)** — never make C convert from UTC
2. **Short answers preferred** — concise, no fluff, skip pleasantries
3. **Tachikoma responds as Tachikoma** — does NOT impersonate LilTachikoma
4. **Balance footer on every message** — universally via `get-balances.sh`
5. **Strike breach cooldown: 1h** — prevent spam on sustained breaks

---

*This file is the canonical reference for Tachikoma. All scripts and systems derive from it.*
*Last updated: 2026-05-07*

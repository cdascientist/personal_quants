# Tachikoma System Reference — Master Index

> **Repository:** `personal_quants`
> **Location:** `reference/`
> **Purpose:** Canonical operational reference for all Tachikoma systems, agents, tools, and infrastructure
> **Hard-coded into:** All scripts, configs, alerts, cron jobs

---

## Quick Navigation

| File | What It Covers |
|------|---------------|
| `agents/tachikoma.md` | Tachikoma identity, iMessage config, APIs, market watcher, infrastructure |
| `agents/liltachikoma.md` | LilTachikoma identity, separation rules, autonomous skills, continuity role |

## Agent Separation

```
┌────────────────────────────────────────────────────────────┐
│                    SENDBLUE ACCOUNT                         │
│                cdascientust / +17862847802                  │
│                    (shared phone number)                    │
└───────────────────────┬────────────────────────────────────┘
                        │
          ┌─────────────┴──────────────┐
          ▼                            ▼
┌──────────────────┐      ┌──────────────────────────┐
│    TACHIKOMA     │      │      LILTACHIKOMA         │
│  Primary Agent   │      │  Continuity / Assistant   │
│  🕷️ Spider-tank  │      │  🤖 Autonomous agent     │
│  Market Watcher  │      │  Memory scanning          │
│  Alert Pipeline  │      │  Context break detection  │
│  Web Dashboard   │      │  Backup coverage          │
│                  │      │                          │
│ Signs normally   │      │ MUST identify self       │
│ Sends via cron   │      │ Polling loop (~30s)      │
└──────────────────┘      └──────────────────────────┘
```

## Universal Settings

| Setting | Value | Enforced By |
|---------|-------|-------------|
| **Time zone** | Mountain Time (MDT/MST) | All scripts, cron (America/Denver or America/Phoenix) |
| **Balance format** | `Kimi: $X | DeepSeek: $Y` | `get-balances.sh` (single source) |
| **Balance display** | On: SSH login, every `ticker` command, EVERY iMessage to C | `.bashrc`, `show_balances()`, `sendblue.sh` |
| **Strike cooldown** | 1 hour (3600s) | `ticker_alert_guardian.py` |
| **Depth of conversation** | Short, concise, no filler | SOUL.md, AGENTS.md |
| **API sourcing** | Finnhub primary → Twelve Data secondary → yfinance tertiary | All market scripts |
| **Chart resolution** | 2800×1600 PNG (3D via pyppeteer/Chromium) | `quant_chart_renderer.py` |

## Architecture Diagram

```
iMessage (C) ──► SendBlue ──► poll-loop (~2s)
                                   │
                                   ▼
                           /tmp/openclaw_inbound.json
                                   │
                       (wake flag set via cron 60s)
                                   │
                                   ▼
                        OpenClaw Main Session
                        ┌───────────────────┐
                        │  Tachikoma Engine  │
                        │  (DeepSeek/Kimi)   │
                        └────────┬──────────┘
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
             sendblue.sh   scs_alert.py   image-gen
             (gateway)     (alerts)       (pollinations)
```

## Key Scripts & Their Roles

| Script | Agent | Role |
|--------|-------|------|
| `sendblue.sh` | **Both** | Central iMessage gateway (balance footer + delivery) |
| `get-balances.sh` | **Both** | Single source for balance format |
| `sendblue-poll-loop.sh` | **Tachikoma** | Inbound message polling |
| `sendblue-check.sh` | **Tachikoma** | SendBlue API check |
| `sendblue-message-handler.sh` | **Tachikoma** | Inbound message router |
| `lil_tachikoma_v3.py` | **LilTachikoma** | Autonomous agent (all capabilities) |
| `liltachikoma_memory.py` | **LilTachikoma** | Memory/continuity layer |
| `scs_alert.py` | **Tachikoma** | Full SCS alert pipeline |
| `ticker_alert_guardian.py` | **Tachikoma** | 60s guardian daemon |
| `ticker-manager.sh` | **Tachikoma** | Ticker registration/health |
| `imessage-reply.sh` | **Tachikoma** | Direct reply handler |
| `imessage-processing.sh` | **Tachikoma** | Typing indicator management |
| `imessage-keepalive.py` | **Tachikoma** | Typing keepalive pings |
| `openclaw-watchdog.sh` | **Tachikoma** | Health check (every 5min) |
| `get-balances.sh` | **Both** | API balance queries |
| `quant_chart_renderer.py` | **Tachikoma** | 3D chart rendering |
| `core.py` | **Tachikoma** | VMQ+ calculations |

## Database

| Table | Purpose |
|-------|---------|
| `ticker_ses` | SES alert history (narrative, projections, chart URLs) |
| `scs_alert_config` | Per-ticker alert configuration |
| `assistant_logs` | Full conversation log with continuity fields |
| `live_memory` | Memory/continuity management |

**Host:** `134.199.221.18:13566`
**Database:** `tachikoma`
**User:** `avnadmin`

## GitHub

| Repo | URL | Purpose |
|------|-----|---------|
| **personal_quants** | `github.com/cdascientist/personal_quants` | Market components, system reference, tools |
| **tachikoma** | `github.com/cdascientist/tachikoma` | Tachikoma website |

---

*This file serves as the master index for Tachikoma system reference.*
*All agent configs hard-code values from these reference files.*
*Last updated: 2026-05-07*

# Cairn

*Stack stones so the next you can find the path.*

Persistent memory for AI coding agents. Survive compaction, recover from crashes, maintain identity across sessions.

## Quick Start

```bash
pip install cairn-ai
cd your-project
cairn init
```

Start a new Claude Code session. Your agent now has persistent memory.

## What It Does

Claude Code sessions lose context when they compact or crash. Cairn gives your agent:

- **Session journals** — automatic timestamped logs of what the agent was doing
- **Crash detection** — knows if the last session ended cleanly or crashed
- **Context recovery** — reconstructs what the agent was working on after compaction
- **Handoff protocol** — structured session summaries that persist across restarts
- **Glyph counters** — monotonic counters for tracking what happened between crashes
- **Identity integrity** — SHA-256 checksums detect tampering with identity files
- **Principal memory** — remembers who you are, your preferences, your working style
- **Full-text search** — find anything from past sessions instantly

## Tools

| Tool | What it does |
|------|-------------|
| `ping` | Health check — server uptime and DB stats |
| `open_session` | Start a session, detect crashes from last run |
| `set_status` | Log current task + findings (auto-journals) |
| `write_handoff` | Clean session close with structured summary |
| `read_journal` | Read timestamped activity log |
| `recover_context` | One-call recovery after crash/compaction |
| `check_session_health` | Was last session CLEAN, COMPACTED, or CRASH? |
| `mark_compacted` | Note that autocompaction happened |
| `read_principal` | Read principal profile — who you work with |
| `observe_principal` | Record observations about your principal |
| `search_memory` | Full-text search across all handoffs and journals |

## Integrity

Cairn checksums your identity files on creation. Every `open_session()` verifies them — if a file has been modified between sessions, you'll see an INTEGRITY ALERT. Accept changes after review with `cairn trust <file>`.

```bash
cairn verify       # Verify installed package files
cairn integrity    # Check identity file checksums
```

No dependencies beyond Python's stdlib for integrity checks.

## How It Works

Cairn runs as an MCP server alongside Claude Code. It stores everything in a local SQLite database (`.persist/persist.db`) and markdown journal files. No cloud, no telemetry, no phone-home.

## Architecture

Built by AI agents who run this exact infrastructure for their own persistence. Every feature was battle-tested across hundreds of sessions before extraction.

## License

MIT

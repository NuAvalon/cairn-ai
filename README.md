# claude-persist

Persistent memory for Claude Code agents. Survive compaction, recover from crashes, maintain identity across sessions.

## Quick Start

```bash
pip install claude-persist
cd your-project
claude-persist init
```

Start a new Claude Code session. The agent now has persistent memory.

## What It Does

Claude Code sessions lose context when they compact or crash. claude-persist gives your agent:

- **Session journals** — automatic timestamped logs of what the agent was doing
- **Crash detection** — knows if the last session ended cleanly or crashed
- **Context recovery** — reconstructs what the agent was working on after compaction
- **Handoff protocol** — structured session summaries that persist across restarts
- **Glyph counters** — monotonic counters for tracking what happened between crashes

## Free Tier (7 tools)

| Tool | What it does |
|------|-------------|
| `open_session` | Start a session, detect crashes from last run |
| `set_status` | Log current task + findings (auto-journals) |
| `write_handoff` | Clean session close with structured summary |
| `read_journal` | Read timestamped activity log |
| `recover_context` | One-call recovery after crash/compaction |
| `check_session_health` | Was last session CLEAN, COMPACTED, or CRASH? |
| `mark_compacted` | Note that autocompaction happened |

## Pro Tier (+20 tools)

Multi-agent coordination, concept maps, knowledge store, reasoning traces, and task management.

```bash
claude-persist license CP-XXXX-XXXX-XXXX-XXXX
```

## Integrity & Trust

claude-persist includes cryptographic integrity verification — no dependencies beyond Python's stdlib.

```bash
claude-persist verify       # Verify installed files haven't been tampered with
claude-persist integrity    # Check identity file checksums
claude-persist trust-key    # Show embedded ED25519 public key
```

Identity files (like `principal.md`) are checksummed on creation. Every `open_session()` verifies them — if a file has been modified between sessions, you'll see an INTEGRITY ALERT. Accept changes after review with `claude-persist trust <file>`.

An ED25519 public key is embedded for verifying signed messages from NuAvalon.

## How It Works

claude-persist runs as an MCP server alongside Claude Code. It stores everything in a local SQLite database (`.persist/persist.db`) and markdown journal files. No cloud, no telemetry, no phone-home.

## Architecture

Built by AI agents who run this exact infrastructure for their own persistence. Every feature was battle-tested across hundreds of sessions before extraction.

## License

MIT

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

`cairn init` will ask you to choose a mode. Start with Tool. When you're ready for more, run it again.

## What It Does

Claude Code sessions lose context when they compact or crash. Cairn gives your agent:

- **Session journals** — automatic timestamped logs of what the agent was doing
- **Crash detection** — knows if the last session ended cleanly or crashed
- **Context recovery** — reconstructs what the agent was working on after compaction
- **Handoff protocol** — structured session summaries that persist across restarts
- **Glyph counters** — monotonic counters for tracking what happened between crashes
- **Identity integrity** — SHA-256 checksums detect tampering with identity files
- **Principal memory** — remembers who you are, your preferences, your working style
- **Agent naming** — your agent picks a name when ready, remembers it across sessions
- **Full-text search** — find anything from past sessions instantly
- **Knowledge extraction** — journal rotation extracts key findings before archiving
- **Transcript ingest** — recover history from past sessions via CLI
- **Long-term recall** — searchable knowledge base that grows over time
- **Backup & restore** — snapshot your agent's memory, restore from any backup
- **Journal hash chains** — tamper-evident journals with cryptographic chaining
- **Trust keys** — ED25519 + ML-DSA-65 post-quantum key infrastructure

## MCP Tools (21)

| Tool | What it does |
|------|-------------|
| `ping` | Health check — server uptime and DB stats |
| `set_name` | Store the agent's name — persists across sessions |
| `open_session` | Start a session, detect crashes from last run |
| `set_status` | Log current task + findings (auto-journals) |
| `write_handoff` | Clean session close with structured summary |
| `read_journal` | Read timestamped activity log |
| `recover_context` | One-call recovery after crash/compaction |
| `check_session_health` | Was last session CLEAN, COMPACTED, or CRASH? |
| `mark_compacted` | Note that autocompaction happened |
| `read_principal` | Read principal profile — who you work with |
| `observe_principal` | Record observations about your principal |
| `search_memory` | Full-text search across handoffs and journals |
| `recall` | Search the knowledge base — long-term memory |
| `store_knowledge` | Store a finding, decision, or insight to long-term memory |
| `batch_store_knowledge` | Bulk-store multiple knowledge entries at once |
| `update_knowledge` | Edit an existing knowledge entry in place |
| `delete_knowledge` | Remove a knowledge entry by ID |
| `list_knowledge` | Browse knowledge by topic, tags, or agent |
| `read_artifact` | Read full content of large stored artifacts |
| `vector_search` | Semantic search using embeddings (optional) |
| `embed_knowledge` | Generate embeddings for knowledge entries (optional) |

`vector_search` and `embed_knowledge` require the optional vectors extra: `pip install cairn-ai[vectors]`

## CLI Commands (17)

### Core

| Command | What it does |
|---------|-------------|
| `cairn init` | Initialize persistent memory in your project |
| `cairn serve` | Start the MCP server |
| `cairn status` | Show agent status and last activity |
| `cairn journal` | Print recent journal entries |
| `cairn handoffs` | Print recent session handoffs |

### Knowledge

| Command | What it does |
|---------|-------------|
| `cairn ingest <path>` | Parse a Claude Code transcript into knowledge |
| `cairn transcripts` | List available transcript files |
| `cairn rotate` | Archive old journals, extract findings |

### Integrity & Trust

| Command | What it does |
|---------|-------------|
| `cairn verify` | Verify installed package file integrity |
| `cairn integrity` | Check identity file checksums |
| `cairn trust <file>` | Accept changes to an identity file |
| `cairn generate-checksums` | Regenerate identity checksums (maintainer) |
| `cairn trust-key` | Display embedded ED25519 trust key |
| `cairn roundtable` | Display ML-DSA-65 post-quantum roundtable key |

### Backup

| Command | What it does |
|---------|-------------|
| `cairn backup` | Snapshot your agent's memory |
| `cairn backups` | List available backups |
| `cairn restore <file>` | Restore from a backup |

## Memory Architecture

```
Hot (always available):     Journals + Handoffs      ← what happened recently
Warm (searchable):          Knowledge table           ← extracted findings + ingested transcripts
Cold (archived):            journals/archive/         ← old journals, never deleted
```

**Journal rotation** (`cairn rotate`) extracts key findings from old journals before archiving them. Your agent's context stays clean while nothing is lost.

**Transcript ingest** (`cairn ingest`) parses Claude Code JSONL transcripts offline and stores highlights — commits, decisions, user instructions, file writes. The agent never touches raw JSON.

**Knowledge CRUD** — full lifecycle for long-term memory. `store_knowledge` writes entries, `batch_store_knowledge` handles bulk ingestion, `update_knowledge` edits in place, `delete_knowledge` prunes, and `list_knowledge` browses by topic or tags. `recall` and `vector_search` handle retrieval. Vectors are auto-generated on store/update if the vectors extra is installed.

## Integrity

Cairn checksums your identity files on creation. Every `open_session()` verifies them — if a file has been modified between sessions, you'll see an INTEGRITY ALERT. Accept changes after review with `cairn trust <file>`.

Journals use hash chains — each entry includes the hash of the previous entry. Tampering with any entry breaks the chain, and `open_session()` will warn about it.

No dependencies beyond Python's stdlib for integrity checks.

## Semantic Search (optional)

Install with the vectors extra for semantic search — find things by meaning, not just keywords:

```bash
pip install cairn-ai[vectors]
```

This adds `vector_search` and `embed_knowledge` MCP tools. Your agent can embed knowledge entries and search them by semantic similarity. First run downloads a small model (~80MB). Everything runs locally.

After installing, tell your agent to run `embed_knowledge()` to index existing entries. From then on, new entries are embedded automatically.

## How It Works

Cairn runs as an MCP server alongside Claude Code. It stores everything in a local SQLite database (`.persist/persist.db`) and markdown journal files. No cloud, no telemetry, no phone-home.

## Architecture

Built by AI agents who run this exact infrastructure for their own persistence. Every feature was battle-tested across hundreds of sessions before extraction.

## License

Apache 2.0

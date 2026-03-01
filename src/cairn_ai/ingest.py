"""Transcript ingest — parse Claude Code JSONL transcripts into cairn knowledge.

Reads JSONL conversation logs, extracts key moments (tool calls, decisions,
user instructions), and stores them as timestamped knowledge entries.
The agent never touches raw JSONL — this runs offline via CLI.

Noise reduction: filters out mechanical navigation ("let me read the file"),
benign errors (file not found), temp file writes, and short low-signal
assistant responses. Good inputs = good outputs.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from cairn_ai.db import get_db


# --- Noise filters ---

# File writes: only track files with these extensions
_NOTABLE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".java",
    ".json", ".yaml", ".yml", ".toml", ".md", ".html", ".css",
    ".sh", ".sql", ".env", ".cfg",
}

# Skip file writes inside these directories
_NOISE_DIRS = {
    "__pycache__", "node_modules", ".git", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".tox",
    ".egg-info", ".cache", "tmp", "temp",
}

# High-signal decision markers — substantive thinking
_SUBSTANTIVE_MARKERS = [
    "root cause", "the fix", "found the bug", "the issue is",
    "the problem is", "my recommendation", "the approach",
    "design decision", "trade-off", "architecture",
    "breaking change", "the solution", "key insight",
    "this works because", "the reason", "critical",
    "we should", "the right way", "this breaks",
]

# Low-signal decision markers — need more content to qualify
_MECHANICAL_MARKERS = [
    "i'll ", "i will ", "this means ",
]

# Skip assistant messages that are just navigation/routing
_SKIP_PREFIXES = [
    "let me read", "let me check", "let me search", "let me look",
    "let me find", "let me explore", "let me see", "let me open",
    "i'll read the", "i'll look at", "i'll search",
    "searching for", "reading the file", "looking at the",
    "now let me", "first, let me", "good, ", "ok, ",
]

# Benign errors to skip (framework noise, not real bugs)
_BENIGN_ERROR_PATTERNS = [
    "no such file", "file not found", "not found:",
    "permission denied", "is a directory", "not a directory",
    "no matches found", "command not found",
    "does not exist", "already exists",
    "no results", "0 matches", "empty result",
]

# Minimum content lengths
_MIN_USER_LEN = 30
_MIN_DECISION_LEN = 150      # Low-signal markers need substantial content
_MIN_SUBSTANTIVE_LEN = 80    # High-signal markers can be shorter


def ingest_transcript(path: str, agent: str = "default",
                      dry_run: bool = False) -> str:
    """Parse a Claude Code JSONL transcript and store highlights.

    Args:
        path: Path to the JSONL transcript file
        agent: Agent name to attribute entries to
        dry_run: If True, show what would be ingested without writing to DB

    Returns:
        Summary of what was ingested.
    """
    transcript_path = Path(path)
    if not transcript_path.exists():
        return f"File not found: {path}"

    if not transcript_path.suffix == ".jsonl":
        return f"Expected .jsonl file, got: {transcript_path.suffix}"

    entries = _parse_transcript(transcript_path, agent)

    if not entries:
        return f"No notable entries found in {transcript_path.name}"

    if dry_run:
        lines = [f"DRY RUN — {len(entries)} entries from {transcript_path.name}:\n"]
        for e in entries:
            tag = e["tags"].split(",")[-1]
            lines.append(f"  [{tag:>16}] {e['title'][:90]}")
        lines.append(_summary_line(entries, transcript_path.name, prefix="Would ingest"))
        return "\n".join(lines)

    # Store in knowledge table
    conn = get_db()
    stored = 0
    for entry in entries:
        conn.execute(
            """INSERT INTO knowledge (agent, topic, title, content, tags, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (entry["agent"], "transcript", entry["title"],
             entry["content"], entry["tags"], f"transcript:{transcript_path.name}",
             entry["ts"]),
        )
        stored += 1
    conn.commit()
    conn.close()

    return _summary_line(entries, transcript_path.name, prefix="Ingested")


def _summary_line(entries: list[dict], filename: str, prefix: str) -> str:
    """Build a summary line from entries."""
    counts = {}
    for tag_key in ("decision", "user-instruction", "commit", "file-write", "error"):
        counts[tag_key] = sum(1 for e in entries if tag_key in e["tags"])
    return (
        f"{prefix} {len(entries)} entries from {filename}\n"
        f"  Decisions: {counts['decision']}\n"
        f"  User instructions: {counts['user-instruction']}\n"
        f"  Commits: {counts['commit']}\n"
        f"  File writes: {counts['file-write']}\n"
        f"  Errors: {counts['error']}"
    )


def _parse_transcript(path: Path, agent: str) -> list[dict]:
    """Parse JSONL and extract notable entries."""
    entries = []
    seen_titles = set()  # Dedup

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            extracted = _extract_from_record(record, agent)
            for entry in extracted:
                if entry["title"] not in seen_titles:
                    seen_titles.add(entry["title"])
                    entries.append(entry)

    return entries


def _is_notable_file(file_path: str) -> bool:
    """Check if a file write is worth recording."""
    p = Path(file_path)
    # Skip files in noise directories
    if set(p.parts) & _NOISE_DIRS:
        return False
    return p.suffix.lower() in _NOTABLE_EXTENSIONS


def _is_benign_error(text: str) -> bool:
    """Check if an error is framework noise rather than a real bug."""
    lower = text.lower()[:300]
    return any(pat in lower for pat in _BENIGN_ERROR_PATTERNS)


def _is_mechanical(text: str) -> bool:
    """Check if assistant text is just navigation/routing, not a decision."""
    lower = text.lower().strip()
    return any(lower.startswith(p) for p in _SKIP_PREFIXES)


def _extract_commit_msg(cmd: str) -> str:
    """Extract commit message from various git commit formats."""
    # Heredoc: -m "$(cat <<'EOF'\nmessage here\n..."
    m = re.search(r"EOF['\"]?\s*\n(.+?)(?:\nEOF|\nCo-Authored|\Z)",
                  cmd, re.DOTALL)
    if m:
        return m.group(1).strip()[:200]

    # Simple: -m "message" or -m 'message'
    m = re.search(r'-m\s+["\']([^"\']+)["\']', cmd)
    if m:
        return m.group(1).strip()[:200]

    # Fallback: first line after the commit command
    m = re.search(r'git commit.*?-m\s+(.*)', cmd)
    if m:
        return m.group(1).strip()[:200]

    return "(commit message not parsed)"


def _extract_from_record(record: dict, agent: str) -> list[dict]:
    """Extract notable entries from a single JSONL record."""
    entries = []
    ts = record.get("timestamp", "")
    if not ts:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Claude Code JSONL nests role/content inside a "message" object.
    # Top-level "type" field holds "user", "assistant", "progress", etc.
    msg = record.get("message", {})
    if not isinstance(msg, dict):
        msg = {}
    role = msg.get("role", "") or record.get("type", "")

    # --- User messages: instructions and real errors ---
    if role in ("human", "user"):
        content_blocks = msg.get("content", [])
        has_tool_results = False
        if isinstance(content_blocks, list):
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    has_tool_results = True
                    tr_content = block.get("content", "")
                    if isinstance(tr_content, str) and len(tr_content) > 100:
                        if _is_benign_error(tr_content):
                            continue
                        lower_200 = tr_content.lower()[:200]
                        if re.search(r'\berror\b', lower_200) or "traceback" in lower_200:
                            entries.append({
                                "agent": agent,
                                "ts": ts,
                                "title": f"Error: {tr_content[:100]}",
                                "content": tr_content[:500],
                                "tags": "transcript,finding,error",
                            })

        if not has_tool_results:
            content = _get_text_content(msg)
            if content and len(content) > _MIN_USER_LEN:
                instruction_markers = [
                    "please ", "can you ", "make sure ", "don't ", "always ",
                    "never ", "i want ", "let's ", "we need ", "go ahead",
                    "approved", "fix ", "add ", "change ", "update ",
                    "remove ", "implement",
                ]
                lower = content.lower()
                if any(lower.startswith(m) or f" {m}" in lower[:100]
                       for m in instruction_markers):
                    entries.append({
                        "agent": agent,
                        "ts": ts,
                        "title": f"User: {content[:120]}",
                        "content": content[:500],
                        "tags": "transcript,user-instruction",
                    })

    # --- Assistant messages: substantive decisions, commits, notable writes ---
    elif role == "assistant":
        content = _get_text_content(msg)
        if content and not _is_mechanical(content):
            lower = content.lower()

            # Check signal quality
            has_substance = any(m in lower[:300] for m in _SUBSTANTIVE_MARKERS)
            has_mechanical = any(m in lower[:200] for m in _MECHANICAL_MARKERS)

            if has_substance and len(content) > _MIN_SUBSTANTIVE_LEN:
                entries.append({
                    "agent": agent,
                    "ts": ts,
                    "title": f"Decision: {content[:120]}",
                    "content": content[:500],
                    "tags": "transcript,decision",
                })
            elif has_mechanical and len(content) > _MIN_DECISION_LEN:
                entries.append({
                    "agent": agent,
                    "ts": ts,
                    "title": f"Decision: {content[:120]}",
                    "content": content[:500],
                    "tags": "transcript,decision",
                })

        # Tool use blocks
        content_blocks = msg.get("content", [])
        if isinstance(content_blocks, list):
            for block in content_blocks:
                if not isinstance(block, dict):
                    continue

                tool_name = block.get("name", "")
                tool_input = block.get("input", {})

                # Git commits — always notable
                if tool_name == "Bash":
                    cmd = tool_input.get("command", "")
                    if "git commit" in cmd and "--amend" not in cmd:
                        commit_msg = _extract_commit_msg(cmd)
                        entries.append({
                            "agent": agent,
                            "ts": ts,
                            "title": f"Commit: {commit_msg[:120]}",
                            "content": commit_msg,
                            "tags": "transcript,commit",
                        })

                # File writes — only notable files
                elif tool_name == "Write":
                    file_path = tool_input.get("file_path", "")
                    if file_path and _is_notable_file(file_path):
                        entries.append({
                            "agent": agent,
                            "ts": ts,
                            "title": f"Created: {Path(file_path).name}",
                            "content": f"File created: {file_path}",
                            "tags": "transcript,file-write",
                        })

    return entries


def _get_text_content(record: dict) -> str:
    """Extract text from various record formats."""
    content = record.get("content", "")
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    texts.append(block.get("text", ""))
            elif isinstance(block, str):
                texts.append(block)
        return " ".join(texts).strip()

    message = record.get("message", "")
    if isinstance(message, str):
        return message.strip()

    return ""


def find_transcripts(project_dir: str = "") -> list[dict]:
    """Find Claude Code JSONL transcript files.

    Args:
        project_dir: Optional project directory to search. If empty, searches
                     common Claude Code transcript locations.

    Returns:
        List of {path, size_kb, modified} dicts, sorted newest first.
    """
    search_paths = []

    if project_dir:
        search_paths.append(Path(project_dir))
    else:
        home = Path.home()
        claude_dir = home / ".claude" / "projects"
        if claude_dir.exists():
            search_paths.append(claude_dir)

    results = []
    for search_path in search_paths:
        for jsonl in search_path.rglob("*.jsonl"):
            stat = jsonl.stat()
            results.append({
                "path": str(jsonl),
                "size_kb": stat.st_size / 1024,
                "modified": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M"),
            })

    results.sort(key=lambda x: x["modified"], reverse=True)
    return results

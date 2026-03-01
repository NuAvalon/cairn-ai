"""Transcript ingest — parse Claude Code JSONL transcripts into cairn knowledge.

Reads JSONL conversation logs, extracts key moments (tool calls, decisions,
user instructions), and stores them as timestamped knowledge entries.
The agent never touches raw JSONL — this runs offline via CLI.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from cairn_ai.db import get_db


def ingest_transcript(path: str, agent: str = "default") -> str:
    """Parse a Claude Code JSONL transcript and store highlights.

    Args:
        path: Path to the JSONL transcript file
        agent: Agent name to attribute entries to

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

    return (
        f"Ingested {stored} entries from {transcript_path.name}\n"
        f"  Decisions: {sum(1 for e in entries if 'decision' in e['tags'])}\n"
        f"  User instructions: {sum(1 for e in entries if 'user-instruction' in e['tags'])}\n"
        f"  Commits: {sum(1 for e in entries if 'commit' in e['tags'])}\n"
        f"  File writes: {sum(1 for e in entries if 'file-write' in e['tags'])}\n"
        f"  Findings: {sum(1 for e in entries if 'finding' in e['tags'])}"
    )


def _parse_transcript(path: Path, agent: str) -> list[dict]:
    """Parse JSONL and extract notable entries."""
    entries = []
    seen_titles = set()  # Dedup

    with open(path) as f:
        for line_num, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            extracted = _extract_from_record(record, agent)
            for entry in extracted:
                # Dedup by title
                if entry["title"] not in seen_titles:
                    seen_titles.add(entry["title"])
                    entries.append(entry)

    return entries


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
    msg_type = record.get("type", "")

    # User messages — look for instructions, decisions, and tool results
    if role == "human" or role == "user":
        # Check if this is a tool_result message
        content_blocks = msg.get("content", [])
        has_tool_results = False
        if isinstance(content_blocks, list):
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    has_tool_results = True
                    tr_content = block.get("content", "")
                    if isinstance(tr_content, str) and len(tr_content) > 100:
                        lower_200 = tr_content.lower()[:200]
                        if re.search(r'\berror\b', lower_200) or "traceback" in lower_200:
                            entries.append({
                                "agent": agent,
                                "ts": ts,
                                "title": f"Error encountered: {tr_content[:100]}",
                                "content": tr_content[:500],
                                "tags": "transcript,finding,error",
                            })

        # If not a tool result, check for user instructions
        if not has_tool_results:
            content = _get_text_content(msg)
            if content and len(content) > 30:
                instruction_markers = [
                    "please ", "can you ", "make sure ", "don't ", "always ", "never ",
                    "i want ", "let's ", "we need ", "go ahead", "approved",
                    "fix ", "add ", "change ", "update ", "remove ", "implement",
                ]
                lower = content.lower()
                if any(lower.startswith(m) or f" {m}" in lower[:100] for m in instruction_markers):
                    entries.append({
                        "agent": agent,
                        "ts": ts,
                        "title": f"User: {content[:120]}",
                        "content": content[:500],
                        "tags": "transcript,user-instruction",
                    })

    # Assistant messages — look for decisions and findings
    elif role == "assistant":
        content = _get_text_content(msg)
        if content and len(content) > 50:
            # Detect decisions
            decision_markers = [
                "i'll ", "i will ", "the approach ", "my recommendation ",
                "the issue is ", "root cause ", "the fix ",
                "this means ", "the problem ", "found the bug",
            ]
            lower = content.lower()
            if any(m in lower[:200] for m in decision_markers):
                entries.append({
                    "agent": agent,
                    "ts": ts,
                    "title": f"Decision: {content[:120]}",
                    "content": content[:500],
                    "tags": "transcript,decision",
                })

        # Look for tool use in content blocks (nested under message.content)
        content_blocks = msg.get("content", [])
        if isinstance(content_blocks, list):
            for block in content_blocks:
                if not isinstance(block, dict):
                    continue

                tool_name = block.get("name", "")
                tool_input = block.get("input", {})

                # Git commits
                if tool_name == "Bash":
                    cmd = tool_input.get("command", "")
                    if "git commit" in cmd:
                        # Extract commit message
                        msg_match = re.search(r'-m ["\'](.+?)["\']', cmd)
                        if not msg_match:
                            msg_match = re.search(r"EOF\n(.+?)(?:\n|EOF)", cmd, re.DOTALL)
                        commit_msg = msg_match.group(1)[:200] if msg_match else cmd[:200]
                        entries.append({
                            "agent": agent,
                            "ts": ts,
                            "title": f"Commit: {commit_msg[:120]}",
                            "content": commit_msg,
                            "tags": "transcript,commit",
                        })

                # File writes
                elif tool_name == "Write":
                    file_path = tool_input.get("file_path", "")
                    if file_path:
                        entries.append({
                            "agent": agent,
                            "ts": ts,
                            "title": f"Created: {file_path}",
                            "content": f"File created: {file_path}",
                            "tags": "transcript,file-write",
                        })

    return entries


def _get_text_content(record: dict) -> str:
    """Extract text from various record formats."""
    # Direct content string
    content = record.get("content", "")
    if isinstance(content, str):
        return content.strip()

    # Content blocks array
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    texts.append(block.get("text", ""))
            elif isinstance(block, str):
                texts.append(block)
        return " ".join(texts).strip()

    # Message field
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
        # Common Claude Code transcript locations
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

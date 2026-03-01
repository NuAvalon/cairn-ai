"""Stress test for cairn — QA before public launch.

Tests realistic usage patterns:
1. Multi-agent concurrent access (4 agents, rapid status updates)
2. High-volume status updates (200 rapid writes)
3. Recovery flows (crash → recovery → verify integrity)
4. Edge cases (Unicode, long strings, special characters)
5. Journal accumulation (30 days simulated)
6. DB size sanity after heavy use
"""

import sqlite3
import time
import threading
from pathlib import Path
from datetime import datetime, timezone

import pytest

# Configure before any imports touch the DB
_tmpdir = None


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """Each test gets a fresh .persist directory."""
    global _tmpdir
    persist_dir = tmp_path / ".persist"
    persist_dir.mkdir()
    (persist_dir / "journals").mkdir()

    import cairn_ai.db as db_mod
    db_mod.configure(persist_dir)
    _tmpdir = persist_dir
    yield persist_dir

    # Reset for next test
    db_mod._persist_dir = None
    db_mod._db_path = None
    db_mod._journal_dir = None


# ── 1. Multi-agent concurrent access ──────────────────────────────────────────

class TestConcurrentAccess:
    def test_four_agents_rapid_status(self, fresh_db):
        """4 agents writing status updates concurrently."""
        from cairn_ai.db import get_db

        errors = []
        agents = ["archie", "apollo", "athena", "hypatia"]

        def agent_work(agent_name, n_updates):
            try:
                for i in range(n_updates):
                    conn = get_db()
                    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    conn.execute(
                        "INSERT OR REPLACE INTO agent_status (agent, status, current_task, last_finding, updated_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (agent_name, "active", f"Task {i}", f"Finding {i}", now),
                    )
                    conn.commit()
                    conn.close()
            except Exception as e:
                errors.append((agent_name, str(e)))

        threads = [
            threading.Thread(target=agent_work, args=(a, 50)) for a in agents
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Concurrent errors: {errors}"

        # Verify all 4 agents have final state
        conn = get_db()
        rows = conn.execute("SELECT agent FROM agent_status").fetchall()
        conn.close()
        assert len(rows) == 4


# ── 2. High volume ────────────────────────────────────────────────────────────

class TestHighVolume:
    def test_200_status_updates(self, fresh_db):
        """200 rapid status updates from one agent."""
        from cairn_ai.db import get_db

        for i in range(200):
            conn = get_db()
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn.execute(
                "INSERT OR REPLACE INTO agent_status (agent, status, current_task, updated_at, tool_calls_since_checkpoint) "
                "VALUES (?, 'active', ?, ?, ?)",
                ("athena", f"Task {i}", now, i),
            )
            conn.commit()
            conn.close()

        conn = get_db()
        row = conn.execute(
            "SELECT current_task, tool_calls_since_checkpoint FROM agent_status WHERE agent = ?",
            ("athena",),
        ).fetchone()
        conn.close()
        assert row[0] == "Task 199"
        assert row[1] == 199


# ── 3. Recovery flows ─────────────────────────────────────────────────────────

class TestRecoveryFlows:
    def test_crash_and_recovery(self, fresh_db):
        """Simulate: open session → write status → crash → recover."""
        from cairn_ai.db import get_db, load_lifecycle, save_lifecycle

        # Open session
        lf = load_lifecycle()
        lf["sessions"].append({
            "agent": "athena",
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "closed_at": None,
            "close_type": None,
        })
        save_lifecycle(lf)

        # Write some status
        conn = get_db()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "INSERT OR REPLACE INTO agent_status (agent, status, current_task, updated_at) "
            "VALUES ('athena', 'active', 'Important work', ?)",
            (now,),
        )
        conn.commit()
        conn.close()

        # Simulate crash (no handoff, no lifecycle close)
        # Now "recover"
        lf2 = load_lifecycle()
        last = lf2["sessions"][-1]
        assert last["closed_at"] is None  # crash detected

        # Recovery: read last status
        conn = get_db()
        row = conn.execute(
            "SELECT status, current_task FROM agent_status WHERE agent = 'athena'"
        ).fetchone()
        conn.close()
        assert row[0] == "active"
        assert row[1] == "Important work"  # data survived

    def test_journal_survives_crash(self, fresh_db):
        """Journal entries persist across simulated crashes."""
        from cairn_ai.journal import write_journal, read_journal_file

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Write journal entries
        write_journal("athena", "active", "First entry before crash", "", now)
        write_journal("athena", "active", "Second entry before crash", "", now)

        # "Crash" — no cleanup
        # "Recover" — read journal
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        content = read_journal_file("athena", today)
        assert "First entry" in content
        assert "Second entry" in content


# ── 4. Edge cases ─────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_unicode_in_status(self, fresh_db):
        """Unicode characters in status fields."""
        from cairn_ai.db import get_db

        conn = get_db()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        conn.execute(
            "INSERT OR REPLACE INTO agent_status (agent, status, current_task, last_finding, updated_at) "
            "VALUES ('athena', 'active', '🦉 建造 البناء', '発見 اكتشاف 🔍', ?)",
            (now,),
        )
        conn.commit()

        row = conn.execute(
            "SELECT current_task FROM agent_status WHERE agent = 'athena'"
        ).fetchone()
        assert "🦉" in row[0]
        assert "建造" in row[0]
        conn.close()

    def test_very_long_handoff(self, fresh_db):
        """10KB+ strings in handoff summary."""
        from cairn_ai.db import get_db

        conn = get_db()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        long_summary = "A" * 50000  # 50KB
        conn.execute(
            "INSERT INTO handoffs (agent, ts, summary, accomplished, pending) "
            "VALUES ('athena', ?, ?, '', '')",
            (now, long_summary),
        )
        conn.commit()

        row = conn.execute(
            "SELECT LENGTH(summary) FROM handoffs WHERE agent = 'athena'"
        ).fetchone()
        conn.close()
        assert row[0] == 50000

    def test_special_sql_characters(self, fresh_db):
        """SQL injection attempts are safely handled by parameterized queries."""
        from cairn_ai.db import get_db

        conn = get_db()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        evil = "'; DROP TABLE agent_status; --"
        conn.execute(
            "INSERT OR REPLACE INTO agent_status (agent, status, current_task, last_finding, updated_at) "
            "VALUES ('evil_agent', 'active', ?, ?, ?)",
            (evil, evil, now),
        )
        conn.commit()

        # Table still exists
        count = conn.execute("SELECT COUNT(*) FROM agent_status").fetchone()[0]
        assert count == 1

        row = conn.execute("SELECT current_task FROM agent_status WHERE agent = 'evil_agent'").fetchone()
        assert row[0] == evil  # stored as literal text
        conn.close()

    def test_empty_strings(self, fresh_db):
        """Empty strings in optional fields."""
        from cairn_ai.db import get_db

        conn = get_db()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        conn.execute(
            "INSERT OR REPLACE INTO agent_status (agent, status, current_task, last_finding, updated_at) "
            "VALUES ('athena', 'active', '', '', ?)",
            (now,),
        )
        conn.commit()

        row = conn.execute(
            "SELECT current_task FROM agent_status WHERE agent = 'athena'"
        ).fetchone()
        assert row[0] == ""
        conn.close()


# ── 5. Journal accumulation ───────────────────────────────────────────────────

class TestJournalAccumulation:
    def test_30_days_of_journals(self, fresh_db):
        """30 days of journal entries with multiple entries per day."""
        from cairn_ai.journal import write_journal, read_journal_file
        from cairn_ai.db import get_journal_dir

        for day in range(30):
            date_str = f"2026-02-{day + 1:02d}"
            journal_path = get_journal_dir() / f"athena_{date_str}.md"
            # Write 10 entries per day
            entries = []
            for i in range(10):
                entries.append(f"## {date_str}T{i:02d}:00:00Z\n- Status: active\n- Task: Day {day} task {i}\n")
            journal_path.write_text("\n".join(entries))

        # Verify all journals exist
        journals = list(get_journal_dir().glob("athena_*.md"))
        assert len(journals) == 30

        # Read a specific day
        content = (get_journal_dir() / "athena_2026-02-15.md").read_text()
        assert "Day 14 task 9" in content

    def test_journal_write_performance(self, fresh_db):
        """100 journal writes should complete in < 5 seconds."""
        from cairn_ai.journal import write_journal

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        start = time.time()
        for i in range(100):
            write_journal("athena", "active", f"Entry {i}: " + "x" * 200, "", now)
        elapsed = time.time() - start

        assert elapsed < 5.0, f"100 journal writes took {elapsed:.2f}s (> 5s)"


# ── 6. DB size sanity ─────────────────────────────────────────────────────────

class TestDBSize:
    def test_db_size_after_heavy_use(self, fresh_db):
        """After 200 status updates + 100 handoffs + 50 sync points, DB < 1MB."""
        from cairn_ai.db import get_db, get_db_path

        conn = get_db()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 200 status updates (INSERT OR REPLACE = 1 final row per agent)
        for i in range(200):
            conn.execute(
                "INSERT OR REPLACE INTO agent_status (agent, status, current_task, updated_at, tool_calls_since_checkpoint) "
                "VALUES (?, 'active', ?, ?, ?)",
                (f"agent_{i % 4}", f"Task {i}", now, i),
            )

        # 100 handoffs
        for i in range(100):
            conn.execute(
                "INSERT INTO handoffs (agent, ts, summary, accomplished, pending) "
                "VALUES (?, ?, ?, ?, ?)",
                (f"agent_{i % 4}", now, f"Summary {i} " * 10, f"Done {i}", f"Todo {i}"),
            )

        # 50 sync points
        for i in range(50):
            conn.execute(
                "INSERT INTO sync_points (agent, sync_num, summary, created_at) "
                "VALUES (?, ?, ?, ?)",
                (f"agent_{i % 4}", i, f"Sync summary {i}", now),
            )

        conn.commit()
        conn.close()

        db_size = get_db_path().stat().st_size
        assert db_size < 1 * 1024 * 1024, f"DB is {db_size / 1024 / 1024:.2f}MB (> 1MB)"


# ── 7. Init flow ──────────────────────────────────────────────────────────────

class TestInitFlow:
    def test_clean_init(self, tmp_path):
        """Simulate what happens when a new user runs cairn init."""
        from cairn_ai.db import configure, get_db

        persist_dir = tmp_path / "fresh_project" / ".persist"
        persist_dir.mkdir(parents=True)
        configure(persist_dir)

        # First DB access creates schema
        conn = get_db()

        # Verify all tables exist
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        conn.close()

        expected = [
            "agent_status", "glyph_counters", "sync_points", "handoffs",
        ]
        for table in expected:
            assert table in tables, f"Missing table: {table}"

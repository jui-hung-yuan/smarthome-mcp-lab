"""Tests for MemoryManager: write, sync, BM25 search, device event logging."""

import asyncio
import json
import time
from pathlib import Path

import pytest

from smarthome.agent.memory.manager import MemoryManager


@pytest.fixture
def mem(tmp_path):
    """MemoryManager backed by a temp directory (no real embedder)."""
    return MemoryManager(memory_dir=tmp_path / "memory", embedder=None)


# ---------------------------------------------------------------------------
# write()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_creates_file(mem, tmp_path):
    await mem.write("USER.md", "# Preferences\n- Likes dim lights\n")
    target = mem._dir / "USER.md"
    assert target.exists()
    assert "dim lights" in target.read_text()


@pytest.mark.asyncio
async def test_write_append_adds_content(mem):
    await mem.write("USER.md", "First line\n", mode="append")
    await mem.write("USER.md", "Second line\n", mode="append")
    text = (mem._dir / "USER.md").read_text()
    assert "First line" in text
    assert "Second line" in text


@pytest.mark.asyncio
async def test_write_overwrite_replaces_content(mem):
    await mem.write("USER.md", "Old content\n", mode="overwrite")
    await mem.write("USER.md", "New content\n", mode="overwrite")
    text = (mem._dir / "USER.md").read_text()
    assert "New content" in text
    assert "Old content" not in text


@pytest.mark.asyncio
async def test_write_creates_nested_dirs(mem):
    await mem.write("memory/2026-02-26.md", "# Daily log\n")
    assert (mem._dir / "memory" / "2026-02-26.md").exists()


# ---------------------------------------------------------------------------
# sync() + BM25 search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_indexes_written_file(mem):
    await mem.write("USER.md", "I prefer warm white light at 2700K in the evening.\n")
    await mem.sync()

    # Verify a chunk was inserted into the DB
    row = mem._conn.execute("SELECT count(*) as n FROM chunks").fetchone()
    assert row["n"] > 0


@pytest.mark.asyncio
async def test_bm25_search_returns_relevant_result(mem):
    await mem.write("USER.md", "User prefers brightness at 30% for movie night.\n")
    await mem.sync()

    results = await mem.search("brightness movie night", max_results=3)
    assert len(results) > 0
    assert "brightness" in results[0].text.lower() or "movie" in results[0].text.lower()


@pytest.mark.asyncio
async def test_search_returns_empty_for_no_match(mem):
    await mem.write("USER.md", "User prefers warm light.\n")
    await mem.sync()
    results = await mem.search("xylophone quantum flux")
    assert results == []


@pytest.mark.asyncio
async def test_sync_is_incremental(mem):
    await mem.write("MEMORY.md", "First fact.\n")
    await mem.sync()

    count_after_first = mem._conn.execute("SELECT count(*) as n FROM chunks").fetchone()["n"]

    # Sync again without changes — should not duplicate chunks
    await mem.sync()
    count_after_second = mem._conn.execute("SELECT count(*) as n FROM chunks").fetchone()["n"]
    assert count_after_first == count_after_second


@pytest.mark.asyncio
async def test_sync_reindexes_on_file_change(mem):
    await mem.write("MEMORY.md", "Original content.\n", mode="overwrite")
    await mem.sync()

    await mem.write("MEMORY.md", "Updated content with new keyword frobnicate.\n", mode="overwrite")
    await mem.sync(force=True)

    results = await mem.search("frobnicate")
    assert len(results) > 0


# ---------------------------------------------------------------------------
# load_session_context()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_session_context_includes_memory_files(mem):
    await mem.write("MEMORY.md", "## Key facts\n- Light prefers warm.\n")
    await mem.write("USER.md", "## Preferences\n- Early bird.\n")
    context = await mem.load_session_context()
    assert "Key facts" in context
    assert "Preferences" in context


@pytest.mark.asyncio
async def test_load_session_context_empty_when_no_files(mem):
    context = await mem.load_session_context()
    assert context == ""


# ---------------------------------------------------------------------------
# log_device_event()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_log_device_event_inserts_row(mem):
    await mem.log_device_event(
        device_id="light-control",
        action="set_brightness",
        params={"brightness": 40},
        result={"success": True, "message": "OK"},
    )
    row = mem._conn.execute("SELECT * FROM device_events").fetchone()
    assert row is not None
    assert row["device_id"] == "light-control"
    assert row["action"] == "set_brightness"
    assert json.loads(row["params"]) == {"brightness": 40}


@pytest.mark.asyncio
async def test_log_device_event_stores_timestamp(mem):
    before = time.time()
    await mem.log_device_event("d", "turn_on", {}, {"success": True})
    after = time.time()
    row = mem._conn.execute("SELECT timestamp FROM device_events").fetchone()
    assert before <= row["timestamp"] <= after


# ---------------------------------------------------------------------------
# append_session_summary()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_append_session_summary_creates_daily_log(mem):
    await mem.append_session_summary("Turned on the light for movie night.")
    from datetime import date
    log_path = mem._dir / "memory" / f"{date.today().isoformat()}.md"
    assert log_path.exists()
    assert "Turned on" in log_path.read_text()

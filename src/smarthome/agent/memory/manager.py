"""MemoryManager: search, write, sync, and session context for agent memory."""

import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Literal, Optional

from .chunker import chunk_markdown
from .embedder import OllamaEmbedder
from .schema import open_db

logger = logging.getLogger(__name__)


@dataclass
class MemoryResult:
    path: str          # relative to memory_dir
    start_line: int
    end_line: int
    text: str
    score: float       # higher = more relevant


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:32]


def _reciprocal_rank_fusion(
    ranked_lists: list[list[tuple[str, float]]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Merge multiple ranked lists using Reciprocal Rank Fusion."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, (chunk_id, _) in enumerate(ranked):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


class MemoryManager:
    """Manages persistent agent memory: Markdown files + SQLite index."""

    def __init__(self, memory_dir: Path, embedder: Optional[OllamaEmbedder] = None):
        self._dir = memory_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        db_path = memory_dir / ".index" / "memory.db"
        self._conn, self._vec_available = open_db(db_path)
        self._embedder = embedder or OllamaEmbedder()
        self._dirty: set[Path] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search(self, query: str, max_results: int = 6) -> list[MemoryResult]:
        """Hybrid BM25 + vector search with Reciprocal Rank Fusion."""
        await self.sync()

        bm25_ranked = self._bm25_search(query, limit=max_results * 2)
        vec_ranked: list[tuple[str, float]] = []

        if self._vec_available:
            embedding = await self._embedder.embed(query)
            if embedding is not None:
                vec_ranked = self._vector_search(embedding, limit=max_results * 2)

        if vec_ranked:
            fused = _reciprocal_rank_fusion([bm25_ranked, vec_ranked])
        else:
            fused = bm25_ranked

        top_ids = [chunk_id for chunk_id, _ in fused[:max_results]]
        if not top_ids:
            return []

        placeholders = ",".join("?" * len(top_ids))
        rows = self._conn.execute(
            f"SELECT id, path, start_line, end_line, text FROM chunks WHERE id IN ({placeholders})",
            top_ids,
        ).fetchall()

        # Maintain fusion order
        order = {cid: i for i, cid in enumerate(top_ids)}
        results = [
            MemoryResult(
                path=r["path"],
                start_line=r["start_line"],
                end_line=r["end_line"],
                text=r["text"],
                score=1.0 / (1 + order.get(r["id"], 99)),
            )
            for r in rows
        ]
        results.sort(key=lambda x: x.score, reverse=True)
        return results

    async def write(
        self,
        rel_path: str,
        content: str,
        mode: Literal["append", "overwrite"] = "append",
    ) -> None:
        """Write to ~/.smarthome/memory/<rel_path>, mark file dirty."""
        target = self._dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)

        if mode == "append":
            with open(target, "a", encoding="utf-8") as f:
                if target.exists() and target.stat().st_size > 0:
                    f.write("\n")
                f.write(content)
        else:
            target.write_text(content, encoding="utf-8")

        self._dirty.add(target)

    async def sync(self, force: bool = False) -> None:
        """Incremental sync: detect changed Markdown files, re-chunk, re-embed, update SQLite."""
        md_files = list(self._dir.rglob("*.md"))
        for path in md_files:
            if self._dir / ".index" in path.parents:
                continue
            if not force and path not in self._dirty:
                # Check if file changed since last index
                row = self._conn.execute(
                    "SELECT hash, mtime FROM files WHERE path=?", (str(path),)
                ).fetchone()
                if row:
                    stat = path.stat()
                    if row["mtime"] == stat.st_mtime and row["hash"] == _file_hash(path):
                        continue
            await self._index_file(path)

        self._dirty.clear()

    async def load_session_context(self) -> str:
        """Return MEMORY.md + USER.md + today's + yesterday's daily log as a single string."""
        parts: list[str] = []
        today = date.today()
        yesterday = today - timedelta(days=1)

        for rel in [
            "MEMORY.md",
            "USER.md",
            "SOUL.md",
            f"memory/{today.isoformat()}.md",
            f"memory/{yesterday.isoformat()}.md",
        ]:
            p = self._dir / rel
            if p.exists():
                text = p.read_text(encoding="utf-8").strip()
                if text:
                    parts.append(f"### {rel}\n{text}")

        return "\n\n".join(parts)

    async def log_device_event(
        self,
        device_id: str,
        action: str,
        params: dict,
        result: dict,
    ) -> None:
        """Insert a row into the device_events table."""
        self._conn.execute(
            "INSERT INTO device_events (device_id, action, params, result, timestamp) VALUES (?,?,?,?,?)",
            (device_id, action, json.dumps(params), json.dumps(result), time.time()),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _index_file(self, path: Path) -> None:
        """Chunk a Markdown file, embed chunks, update SQLite."""
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Cannot read %s: %s", path, e)
            return

        path_str = str(path)
        file_hash = _file_hash(path)
        stat = path.stat()

        # Remove old chunks for this file
        old_ids = [
            r["id"]
            for r in self._conn.execute(
                "SELECT id FROM chunks WHERE path=?", (path_str,)
            ).fetchall()
        ]
        if old_ids:
            placeholders = ",".join("?" * len(old_ids))
            self._conn.execute(f"DELETE FROM chunks_fts WHERE id IN ({placeholders})", old_ids)
            self._conn.execute(f"DELETE FROM chunks WHERE id IN ({placeholders})", old_ids)
            if self._vec_available:
                self._conn.execute(
                    f"DELETE FROM chunks_vec WHERE id IN ({placeholders})", old_ids
                )

        chunks = chunk_markdown(text, path=path_str)
        now = time.time()

        for chunk in chunks:
            chunk_id = f"{path_str}:L{chunk.start_line}-{chunk.end_line}"
            self._conn.execute(
                "INSERT OR REPLACE INTO chunks (id, path, start_line, end_line, text, hash, updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (chunk_id, path_str, chunk.start_line, chunk.end_line, chunk.text, chunk.hash, now),
            )
            self._conn.execute(
                "INSERT INTO chunks_fts (text, id, path) VALUES (?,?,?)",
                (chunk.text, chunk_id, path_str),
            )

            if self._vec_available and self._embedder:
                embedding = await self._embedder.embed(chunk.text)
                if embedding is not None:
                    self._conn.execute(
                        "INSERT OR REPLACE INTO chunks_vec (id, embedding) VALUES (?,?)",
                        (chunk_id, json.dumps(embedding)),
                    )

        self._conn.execute(
            "INSERT OR REPLACE INTO files (path, hash, mtime, size) VALUES (?,?,?,?)",
            (path_str, file_hash, stat.st_mtime, stat.st_size),
        )
        self._conn.commit()
        logger.debug("Indexed %s (%d chunks)", path, len(chunks))

    def _bm25_search(self, query: str, limit: int = 12) -> list[tuple[str, float]]:
        """BM25 search via FTS5, returns [(chunk_id, score)]."""
        try:
            # FTS5 rank() is negative (more negative = better match)
            rows = self._conn.execute(
                "SELECT id, rank FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                (query, limit),
            ).fetchall()
            # Normalize: invert so higher = better
            return [(r["id"], -r["rank"]) for r in rows]
        except sqlite3.OperationalError as e:
            logger.warning("BM25 search error: %s", e)
            return []

    def _vector_search(self, embedding: list[float], limit: int = 12) -> list[tuple[str, float]]:
        """KNN vector search via sqlite-vec, returns [(chunk_id, distance)]."""
        if not self._vec_available:
            return []
        try:
            rows = self._conn.execute(
                "SELECT id, distance FROM chunks_vec WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
                (json.dumps(embedding), limit),
            ).fetchall()
            # Convert distance to score (lower distance = higher score)
            return [(r["id"], 1.0 / (1.0 + r["distance"])) for r in rows]
        except Exception as e:
            logger.warning("Vector search error: %s", e)
            return []

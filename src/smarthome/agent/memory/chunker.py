"""MarkdownChunker: split Markdown files into overlapping text chunks."""

import hashlib
import re
from dataclasses import dataclass


# Target ~400 tokens ≈ 1600 chars; overlap ~80 tokens ≈ 320 chars
TARGET_CHARS = 1600
OVERLAP_CHARS = 320

# Heading pattern: any ATX heading (# through ######)
HEADING_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)


@dataclass
class Chunk:
    start_line: int   # 1-based, inclusive
    end_line: int     # 1-based, inclusive
    text: str
    hash: str


def _make_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _split_by_headings(lines: list[str]) -> list[tuple[int, int]]:
    """Return list of (start_idx, end_idx) ranges split at heading boundaries (0-based line indices)."""
    split_points = [0]
    for i, line in enumerate(lines):
        if i > 0 and HEADING_RE.match(line):
            split_points.append(i)
    split_points.append(len(lines))
    return [(split_points[i], split_points[i + 1]) for i in range(len(split_points) - 1)]


def chunk_markdown(text: str, path: str = "") -> list[Chunk]:
    """Split Markdown text into overlapping chunks with line numbers.

    Strategy:
    1. Split at heading boundaries.
    2. If a section is larger than TARGET_CHARS, further split at blank lines.
    3. Combine small sections greedily until TARGET_CHARS.
    4. Add OVERLAP_CHARS of text from the previous chunk as prefix.
    """
    lines = text.splitlines(keepends=True)
    if not lines:
        return []

    # Collect raw sections (list of line-index ranges)
    heading_sections = _split_by_headings(lines)

    # Sub-split sections that exceed TARGET_CHARS at blank lines
    raw_sections: list[tuple[int, int]] = []
    for start, end in heading_sections:
        section_text = "".join(lines[start:end])
        if len(section_text) <= TARGET_CHARS:
            raw_sections.append((start, end))
            continue
        # Split on blank lines within section
        sub_start = start
        for i in range(start, end):
            if lines[i].strip() == "" and i > sub_start:
                raw_sections.append((sub_start, i + 1))
                sub_start = i + 1
        if sub_start < end:
            raw_sections.append((sub_start, end))

    # Greedily combine small sections
    merged: list[tuple[int, int]] = []
    current_start: int | None = None
    current_end: int = 0
    current_len: int = 0

    for start, end in raw_sections:
        section_len = sum(len(l) for l in lines[start:end])
        if current_start is None:
            current_start, current_end, current_len = start, end, section_len
        elif current_len + section_len <= TARGET_CHARS:
            current_end = end
            current_len += section_len
        else:
            merged.append((current_start, current_end))
            current_start, current_end, current_len = start, end, section_len

    if current_start is not None:
        merged.append((current_start, current_end))

    # Build Chunk objects with overlap prefix
    chunks: list[Chunk] = []
    for idx, (start, end) in enumerate(merged):
        body = "".join(lines[start:end])

        if idx > 0:
            # Grab tail of previous chunk's body as overlap prefix
            prev_start, prev_end = merged[idx - 1]
            prev_text = "".join(lines[prev_start:prev_end])
            overlap = prev_text[-OVERLAP_CHARS:] if len(prev_text) > OVERLAP_CHARS else prev_text
            full_text = overlap + body
        else:
            full_text = body

        full_text = full_text.strip()
        if not full_text:
            continue

        chunks.append(
            Chunk(
                start_line=start + 1,  # convert to 1-based
                end_line=end,          # end is exclusive in range; last line number = end
                text=full_text,
                hash=_make_hash(full_text),
            )
        )

    return chunks

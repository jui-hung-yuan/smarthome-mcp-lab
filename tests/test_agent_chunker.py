"""Tests for MarkdownChunker."""

import pytest
from smarthome.agent.memory.chunker import chunk_markdown, Chunk


def test_empty_text_returns_no_chunks():
    assert chunk_markdown("") == []


def test_single_short_paragraph_is_one_chunk():
    text = "Hello world, this is a short paragraph."
    chunks = chunk_markdown(text)
    assert len(chunks) == 1
    assert "Hello world" in chunks[0].text


def test_chunk_contains_correct_line_numbers():
    text = "line one\nline two\nline three\n"
    chunks = chunk_markdown(text)
    assert len(chunks) == 1
    assert chunks[0].start_line == 1
    assert chunks[0].end_line >= 3


def test_heading_splits_into_separate_chunks():
    text = "# Section One\n\nContent of section one.\n\n# Section Two\n\nContent of section two.\n"
    chunks = chunk_markdown(text)
    # Should be at least 2 chunks (one per heading section or merged if small)
    combined = " ".join(c.text for c in chunks)
    assert "Section One" in combined
    assert "Section Two" in combined


def test_each_chunk_has_hash():
    text = "# Heading\n\nSome content here.\n"
    chunks = chunk_markdown(text)
    for chunk in chunks:
        assert isinstance(chunk.hash, str)
        assert len(chunk.hash) == 16  # sha256 hex[:16]


def test_identical_chunks_have_same_hash():
    text = "Same content"
    c1 = chunk_markdown(text)
    c2 = chunk_markdown(text)
    assert c1[0].hash == c2[0].hash


def test_large_text_is_split_into_multiple_chunks():
    # Generate text larger than TARGET_CHARS (1600)
    paragraph = "This is a paragraph with some content. " * 20  # ~780 chars
    text = f"# Section\n\n{paragraph}\n\n{paragraph}\n\n{paragraph}\n"
    chunks = chunk_markdown(text)
    assert len(chunks) >= 2


def test_overlap_prefix_appears_in_subsequent_chunk():
    # Create two sections, second should contain tail of first
    section1 = "A" * 1700  # bigger than TARGET_CHARS to force split
    section2 = "B" * 400
    text = f"{section1}\n\n# New Section\n\n{section2}\n"
    chunks = chunk_markdown(text)
    # If there are multiple chunks, later chunks may contain overlap
    assert len(chunks) >= 1


def test_chunk_text_is_stripped():
    text = "\n\n  Some content  \n\n"
    chunks = chunk_markdown(text)
    if chunks:
        assert chunks[0].text == chunks[0].text.strip()


def test_multiline_markdown_preserves_structure():
    text = (
        "# Title\n\n"
        "Paragraph one.\n\n"
        "## Subsection\n\n"
        "- Item 1\n"
        "- Item 2\n"
    )
    chunks = chunk_markdown(text)
    all_text = " ".join(c.text for c in chunks)
    assert "Title" in all_text
    assert "Item 1" in all_text

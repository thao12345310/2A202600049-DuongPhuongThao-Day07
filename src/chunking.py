from __future__ import annotations

import math
import re


class FixedSizeChunker:
    """
    Split text into fixed-size chunks with optional overlap.

    Rules:
        - Each chunk is at most chunk_size characters long.
        - Consecutive chunks share overlap characters.
        - The last chunk contains whatever remains.
        - If text is shorter than chunk_size, return [text].
    """

    def __init__(self, chunk_size: int = 500, overlap: int = 50) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, text: str) -> list[str]:
        if not text:
            return []
        if len(text) <= self.chunk_size:
            return [text]

        step = self.chunk_size - self.overlap
        chunks: list[str] = []
        for start in range(0, len(text), step):
            chunk = text[start : start + self.chunk_size]
            chunks.append(chunk)
            if start + self.chunk_size >= len(text):
                break
        return chunks


class SentenceChunker:
    """
    Split text into chunks of at most max_sentences_per_chunk sentences.

    Sentence detection: split on ". ", "! ", "? " or ".\n".
    Strip extra whitespace from each chunk.
    """

    def __init__(self, max_sentences_per_chunk: int = 3) -> None:
        self.max_sentences_per_chunk = max(1, max_sentences_per_chunk)

    def chunk(self, text: str) -> list[str]:
        # TODO: split into sentences, group into chunks
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks: list[str] = []
        for i in range(0, len(sentences), self.max_sentences_per_chunk):
            chunk = ' '.join(sentences[i:i + self.max_sentences_per_chunk])
            chunks.append(chunk)
        return chunks


class RecursiveChunker:
    """
    Recursively split text using separators in priority order.

    Default separator priority:
        ["\n\n", "\n", ". ", " ", ""]
    """

    DEFAULT_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]

    def __init__(self, separators: list[str] | None = None, chunk_size: int = 500) -> None:
        self.separators = self.DEFAULT_SEPARATORS if separators is None else list(separators)
        self.chunk_size = chunk_size

    def chunk(self, text: str) -> list[str]:
        # TODO: implement recursive splitting strategy
        return self._split(text, self.separators)

    def _split(self, current_text: str, remaining_separators: list[str]) -> list[str]:
        # TODO: recursive helper used by RecursiveChunker.chunk
        if len(current_text) <= self.chunk_size:
            return [current_text]
        if not remaining_separators:
            return [current_text]
            
        separator = remaining_separators[0]
        if separator == "":
            splits = list(current_text)
        else:
            splits = current_text.split(separator)
            
        good_splits = []
        for s in splits:
            if len(s) <= self.chunk_size:
                good_splits.append(s)
            else:
                good_splits.extend(self._split(s, remaining_separators[1:]))
                
        merged = []
        current_chunk = ""
        
        for s in good_splits:
            if not current_chunk:
                current_chunk = s
            elif len(current_chunk) + len(separator) + len(s) <= self.chunk_size:
                current_chunk += separator + s
            else:
                merged.append(current_chunk)
                current_chunk = s
                
        if current_chunk:
            merged.append(current_chunk)
            
        return merged

class SectionChunker:
    """
    Split markdown text by section headers (# and ##).

    Each chunk contains one section including its header.
    If a section exceeds max_section_chars, it is further split
    by sub-headers or paragraph breaks.

    Design rationale: Handbook/policy documents are organized by sections.
    Keeping header + content together preserves the topic context of each chunk,
    making it easier for both embedders and metadata filters to identify relevance.
    """

    def __init__(self, max_section_chars: int = 1000) -> None:
        self.max_section_chars = max_section_chars

    def chunk(self, text: str) -> list[str]:
        if not text:
            return []

        # Split by markdown headers (lines starting with # or ##)
        sections = []
        current_section = ""

        for line in text.split("\n"):
            # Detect header lines (# or ## but not ### which is too granular)
            if re.match(r'^#{1,2}\s+', line) and current_section.strip():
                sections.append(current_section.strip())
                current_section = line + "\n"
            else:
                current_section += line + "\n"

        if current_section.strip():
            sections.append(current_section.strip())

        # Further split oversized sections by paragraph breaks
        final_chunks = []
        for section in sections:
            if len(section) <= self.max_section_chars:
                final_chunks.append(section)
            else:
                # Extract header (first line if it's a header)
                lines = section.split("\n")
                header = ""
                body_start = 0
                if lines and re.match(r'^#{1,2}\s+', lines[0]):
                    header = lines[0]
                    body_start = 1

                # Split body by paragraph breaks
                body = "\n".join(lines[body_start:])
                paragraphs = body.split("\n\n")

                current_chunk = header
                for para in paragraphs:
                    if not para.strip():
                        continue
                    candidate = (current_chunk + "\n\n" + para).strip() if current_chunk else para.strip()
                    if len(candidate) <= self.max_section_chars:
                        current_chunk = candidate
                    else:
                        if current_chunk.strip():
                            final_chunks.append(current_chunk.strip())
                        current_chunk = (header + "\n\n" + para).strip() if header else para.strip()

                if current_chunk.strip():
                    final_chunks.append(current_chunk.strip())

        return final_chunks


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def compute_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """
    Compute cosine similarity between two vectors.

    cosine_similarity = dot(a, b) / (||a|| * ||b||)

    Returns 0.0 if either vector has zero magnitude.
    """
    # TODO: implement cosine similarity formula
    dot_product = _dot(vec_a, vec_b)
    norm_a = math.sqrt(_dot(vec_a, vec_a))
    norm_b = math.sqrt(_dot(vec_b, vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)


class ChunkingStrategyComparator:
    """Run all built-in chunking strategies and compare their results."""

    def compare(self, text: str, chunk_size: int = 200) -> dict:
        # TODO: call each chunker, compute stats, return comparison dict
        chunkers = {
            "fixed_size": FixedSizeChunker(chunk_size=chunk_size),
            "by_sentences": SentenceChunker(max_sentences_per_chunk=3),
            "recursive": RecursiveChunker(chunk_size=chunk_size),
        }
        results = {}
        for name, chunker in chunkers.items():
            chunks = chunker.chunk(text)
            results[name] = {
                "count": len(chunks),
                "avg_length": sum(len(c) for c in chunks) / len(chunks) if chunks else 0.0,
                "chunks": chunks
            }
        return results

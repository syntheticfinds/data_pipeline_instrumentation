from dataclasses import dataclass
from typing import List

from google_docs_client import Paragraph


@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    paragraph_start: int
    paragraph_end: int  # inclusive
    text: str


def chunk_document(
    paragraphs: List[Paragraph],
    max_chars: int = 3500,
    overlap_paragraphs: int = 1,
) -> List[Chunk]:
    """
    Paragraph-aware chunker:
      - groups consecutive paragraphs up to max_chars
      - keeps paragraph indices for anchoring + traceability
      - overlaps by N paragraphs to reduce boundary misses
    """
    chunks: List[Chunk] = []
    i = 0
    chunk_idx = 0

    while i < len(paragraphs):
        start = i
        buf = []
        char_count = 0

        while i < len(paragraphs):
            ptext = paragraphs[i].text
            add_len = len(ptext) + 2  # spacing
            if buf and char_count + add_len > max_chars:
                break
            buf.append(ptext)
            char_count += add_len
            i += 1

        end = i - 1
        text = "\n\n".join(buf).strip()
        chunks.append(
            Chunk(
                chunk_index=chunk_idx,
                paragraph_start=paragraphs[start].paragraph_index,
                paragraph_end=paragraphs[end].paragraph_index,
                text=text,
            )
        )
        chunk_idx += 1

        # Overlap
        i = max(i - overlap_paragraphs, start + 1)

    return chunks

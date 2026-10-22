"""Plain data containers shared by the processor and the chunker."""
from dataclasses import dataclass, field, asdict


@dataclass
class Page:
    """One page of a document: its number and its cleaned paragraphs."""
    number: int
    paragraphs: list[str]

    @property
    def char_count(self) -> int:
        return sum(len(p) for p in self.paragraphs)


@dataclass
class Chunk:
    """One searchable passage. These fields map onto the document_chunks table."""
    id: str            # e.g. "lecture-0007" (unique across documents)
    index: int         # order inside the document -> chunk_index
    page_start: int    # first page the text comes from -> page_number
    page_end: int      # last page (differs from page_start if the chunk spans pages)
    text: str          # original text -> text column
    char_count: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProcessedDocument:
    doc_id: str
    filename: str
    page_count: int
    empty_pages: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)

"""Three chunking strategies, kept side by side so evals/compare_chunking.py can measure them."""

import re
from dataclasses import dataclass

STRATEGIES = ("fixed", "recursive", "section")

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
RECURSIVE_SEPS = ("\n## ", "\n### ", "\n\n", "\n", ". ", " ")
SECTION_SEPS = ("\n\n", "\n", ". ", " ")


@dataclass
class Document:
    doc_id: str
    title: str
    text: str


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    text: str

    def embed_text(self) -> str:
        """Title and section are prepended so a short chunk still carries its context."""
        return "\n".join(p for p in (self.title, self.section, self.text) if p)


def chunk(doc: Document, strategy: str = "section", max_chars: int = 600) -> list[Chunk]:
    if strategy == "fixed":
        pieces = [("", t) for t in fixed_windows(doc.text, size=400, overlap=80)]
    elif strategy == "recursive":
        pieces = [("", t) for t in recursive_split(doc.text, max_chars)]
    elif strategy == "section":
        pieces = section_split(doc.text, max_chars)
    else:
        raise ValueError(f"unknown chunking strategy: {strategy}")

    pieces = [(sec, txt.strip()) for sec, txt in pieces if txt.strip()]
    return [
        Chunk(chunk_id=f"{doc.doc_id}#{i}", doc_id=doc.doc_id, title=doc.title, section=sec, text=txt)
        for i, (sec, txt) in enumerate(pieces)
    ]


def fixed_windows(text: str, size: int, overlap: int) -> list[str]:
    """Character windows with overlap, snapped to whitespace so words are not cut."""
    out: list[str] = []
    start, n = 0, len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            space = text.rfind(" ", start + size // 2, end)
            if space != -1:
                end = space
        out.append(text[start:end])
        if end >= n:
            break
        start = max(end - overlap, start + 1)
        space = text.find(" ", start, end)
        if space != -1:
            start = space + 1
    return out


def recursive_split(text: str, max_chars: int, seps: tuple[str, ...] = RECURSIVE_SEPS) -> list[str]:
    """Split on the coarsest separator present, then greedily merge pieces up to max_chars."""
    if len(text) <= max_chars:
        return [text]
    for i, sep in enumerate(seps):
        if sep not in text:
            continue
        parts = text.split(sep)
        pieces = [parts[0]] + [sep + p for p in parts[1:]]
        out: list[str] = []
        buf = ""
        for p in pieces:
            if len(p) > max_chars:
                if buf:
                    out.append(buf)
                    buf = ""
                out.extend(recursive_split(p, max_chars, seps[i + 1 :]))
            elif len(buf) + len(p) <= max_chars:
                buf += p
            else:
                out.append(buf)
                buf = p
        if buf:
            out.append(buf)
        return out
    return fixed_windows(text, max_chars, 0)


def section_split(text: str, max_chars: int) -> list[tuple[str, str]]:
    """One chunk per markdown section, labelled with its heading path (H1 is the doc title)."""
    out: list[tuple[str, str]] = []
    path: dict[int, str] = {}
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            section = " > ".join(path[k] for k in sorted(path))
            out.extend((section, piece) for piece in recursive_split(body, max_chars, SECTION_SEPS))
        buf.clear()

    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if not m:
            buf.append(line)
            continue
        flush()
        level = len(m.group(1))
        if level == 1:
            continue
        path = {k: v for k, v in path.items() if k < level}
        path[level] = m.group(2).strip()
    flush()
    return out

import io
import re
from pathlib import Path

from app.rag.chunking import Document

SUPPORTED_EXT = {".md": "text/markdown", ".txt": "text/plain", ".pdf": "application/pdf"}
_H1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def parse(content: bytes, mime_type: str, doc_id: str, title: str | None = None) -> Document:
    if mime_type == "application/pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
    elif mime_type.startswith("text/"):
        text = content.decode("utf-8-sig")
    else:
        raise ValueError(f"unsupported mime type: {mime_type}")

    if not title:
        m = _H1.search(text)
        title = m.group(1).strip() if m else doc_id
    return Document(doc_id=doc_id, title=title, text=text)


def load_path(path: Path) -> Document:
    mime = SUPPORTED_EXT.get(path.suffix.lower())
    if not mime:
        raise ValueError(f"unsupported file: {path}")
    return parse(path.read_bytes(), mime, doc_id=path.stem)


def load_dir(directory: Path) -> list[Document]:
    return [load_path(p) for p in sorted(directory.iterdir()) if p.suffix.lower() in SUPPORTED_EXT]

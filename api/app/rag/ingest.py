import logging
from dataclasses import replace

from app.core.config import get_settings
from app.guardrails.injection import sanitize_document
from app.llm import client as llm
from app.llm.cost import Usage
from app.rag import chunking
from app.rag.chunking import Document
from app.rag.store import KBStore, get_store

logger = logging.getLogger("smartcs.ingest")


async def ingest_document(
    doc: Document, strategy: str | None = None, store: KBStore | None = None, usage: Usage | None = None
) -> int:
    settings = get_settings()
    strategy = strategy or settings.chunk_strategy
    store = store or get_store(strategy)
    if settings.guard_injection:
        # Indirect prompt injection: a document must not be able to talk to the model.
        text, dropped = sanitize_document(doc.text)
        if dropped:
            logger.warning("ingest %s: dropped %d instruction-like line(s): %s", doc.doc_id, len(dropped),
                           [d[:80] for d in dropped])
            doc = replace(doc, text=text)
    chunks = chunking.chunk(doc, strategy)
    if not chunks:
        return 0
    vectors = await llm.embed([c.embed_text() for c in chunks], usage)
    await store.ensure(dim=len(vectors[0]))
    await store.replace_doc(doc.doc_id, chunks, vectors)
    return len(chunks)

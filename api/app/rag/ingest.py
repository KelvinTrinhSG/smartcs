from app.core.config import get_settings
from app.llm import client as llm
from app.llm.cost import Usage
from app.rag import chunking
from app.rag.chunking import Document
from app.rag.store import KBStore, get_store


async def ingest_document(
    doc: Document, strategy: str | None = None, store: KBStore | None = None, usage: Usage | None = None
) -> int:
    strategy = strategy or get_settings().chunk_strategy
    store = store or get_store(strategy)
    chunks = chunking.chunk(doc, strategy)
    if not chunks:
        return 0
    vectors = await llm.embed([c.embed_text() for c in chunks], usage)
    await store.ensure(dim=len(vectors[0]))
    await store.replace_doc(doc.doc_id, chunks, vectors)
    return len(chunks)

import uuid
from dataclasses import asdict, dataclass
from functools import lru_cache

from qdrant_client import AsyncQdrantClient, models

from app.core.config import get_settings
from app.rag import sparse
from app.rag.chunking import Chunk

DENSE = "dense"
SPARSE = "sparse"
_NS = uuid.UUID("6f1c2b1e-5d6a-4b8e-9a51-2f0c7d3e4a10")


@dataclass
class Hit:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    text: str
    score: float


class KBStore:
    def __init__(self, client: AsyncQdrantClient, collection: str):
        self.client = client
        self.collection = collection

    async def ensure(self, dim: int) -> None:
        if await self.client.collection_exists(self.collection):
            return
        await self.client.create_collection(
            self.collection,
            vectors_config={DENSE: models.VectorParams(size=dim, distance=models.Distance.COSINE)},
            sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        await self.client.create_payload_index(
            self.collection, field_name="doc_id", field_schema=models.PayloadSchemaType.KEYWORD
        )

    async def replace_doc(self, doc_id: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """Re-ingesting a document replaces all of its old chunks."""
        await self.client.delete(
            self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]
                )
            ),
        )
        points = []
        for c, vec in zip(chunks, vectors, strict=True):
            idx, vals = sparse.doc_vector(c.embed_text())
            points.append(
                models.PointStruct(
                    id=str(uuid.uuid5(_NS, c.chunk_id)),
                    vector={DENSE: vec, SPARSE: models.SparseVector(indices=idx, values=vals)},
                    payload=asdict(c),
                )
            )
        if points:
            await self.client.upsert(self.collection, points=points)

    async def search_dense(self, vector: list[float], limit: int) -> list[Hit]:
        res = await self.client.query_points(
            self.collection, query=vector, using=DENSE, limit=limit, with_payload=True
        )
        return [_hit(p) for p in res.points]

    async def search_sparse(self, text: str, limit: int) -> list[Hit]:
        idx, vals = sparse.query_vector(text)
        if not idx:
            return []
        res = await self.client.query_points(
            self.collection,
            query=models.SparseVector(indices=idx, values=vals),
            using=SPARSE,
            limit=limit,
            with_payload=True,
        )
        return [_hit(p) for p in res.points]


def _hit(p: models.ScoredPoint) -> Hit:
    pl = p.payload or {}
    return Hit(
        chunk_id=pl["chunk_id"],
        doc_id=pl["doc_id"],
        title=pl.get("title", ""),
        section=pl.get("section", ""),
        text=pl["text"],
        score=p.score,
    )


@lru_cache
def _client() -> AsyncQdrantClient:
    settings = get_settings()
    return AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)


def get_store(strategy: str | None = None) -> KBStore:
    settings = get_settings()
    return KBStore(_client(), f"{settings.kb_collection_prefix}_{strategy or settings.chunk_strategy}")

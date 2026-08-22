"""Knowledge base ingestion and retrieval — shared, plain-Python core.

Both the voice agent (Phase 3) and the email agent (Phase 6) import
`search_knowledge` directly; see boundary rule 5 in documents/plan.md (tools
are plain Python functions, agent-framework adapters wrap them, they never
fork the logic). Keep these signatures stable once Phase 3 starts depending
on them.

Design: Postgres (KnowledgeDoc/KnowledgeChunk) stays the source of truth for
chunk text, so the Qdrant index can always be rebuilt from it. Qdrant also
stores the chunk text in its payload so `search_knowledge` never needs a
round trip back to Postgres to serve a result.
"""

from __future__ import annotations

import asyncio
import re
import uuid

from fastembed import TextEmbedding
from qdrant_client import AsyncQdrantClient
from qdrant_client import models as qmodels
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from db.models import KnowledgeChunk, KnowledgeDoc

# BAAI/bge-small-en-v1.5: fastembed's own suggested default — 384-dim, good
# quality/speed tradeoff for local CPU inference. Whatever model is picked
# here, EMBEDDING_DIM must match its output size: ensure_collection() sizes
# the Qdrant collection from it, and getting it wrong fails every upsert with
# a dimension-mismatch error.
EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384

# Module-level singletons — loading the embedding model or opening a new
# Qdrant client per call would be needless disk/network work on every
# ingest or search.
_embedding_model: TextEmbedding | None = None
_qdrant_client: AsyncQdrantClient | None = None
_collection_ready = False


def get_embedding_model() -> TextEmbedding:
    """Lazily loads the fastembed model once per process. fastembed caches
    the (~100MB+) model weights on disk on first use; loading it per-call
    would re-read from disk (or re-download) on every ingest/search."""
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = TextEmbedding(model_name=EMBEDDING_MODEL_NAME)
    return _embedding_model


def get_qdrant_client() -> AsyncQdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        settings = get_settings()
        _qdrant_client = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
        )
    return _qdrant_client


async def ensure_collection() -> None:
    """Creates the Qdrant collection if it doesn't exist yet. Safe to call on
    every ingest/search — short-circuits after the first successful check in
    this process."""
    global _collection_ready
    if _collection_ready:
        return

    settings = get_settings()
    client = get_qdrant_client()
    if not await client.collection_exists(settings.qdrant_collection):
        await client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=qmodels.VectorParams(size=EMBEDDING_DIM, distance=qmodels.Distance.COSINE),
        )
    _collection_ready = True


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def chunk_text(text: str, chunk_size: int = 400, overlap: int = 60) -> list[str]:
    """Naive paragraph/sentence-aware chunker. `chunk_size`/`overlap` are word
    counts — a rough proxy for tokens, good enough to keep chunks from being
    severed mid-thought without pulling in a tokenizer. Deliberately simple:
    chunks are keyed by their own Qdrant point id, so improving this later
    never requires a migration, just re-ingesting.
    """
    text = text.strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    sentences: list[str] = []
    for paragraph in paragraphs:
        sentences.extend(s.strip() for s in _SENTENCE_SPLIT_RE.split(paragraph) if s.strip())

    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    for sentence in sentences:
        sentence_words = len(sentence.split())
        if current and current_words + sentence_words > chunk_size:
            chunks.append(" ".join(current))
            # Carry the tail of the chunk just closed into the next one, so
            # context isn't severed right at the boundary.
            carried: list[str] = []
            carried_words = 0
            for s in reversed(current):
                w = len(s.split())
                if carried_words + w > overlap:
                    break
                carried.insert(0, s)
                carried_words += w
            current, current_words = carried, carried_words

        current.append(sentence)
        current_words += sentence_words

    if current:
        chunks.append(" ".join(current))

    return chunks


async def ingest_document(
    session: AsyncSession,
    workspace_id: str,
    title: str,
    source_type: str,
    text: str,
    source_url: str | None = None,
) -> KnowledgeDoc:
    """Chunks, embeds (one batch), upserts to Qdrant, then writes the
    KnowledgeDoc/KnowledgeChunk rows. Qdrant is written before Postgres so a
    failed upsert never leaves an orphaned KnowledgeDoc with no vectors
    behind it.
    """
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("document produced no chunks — text was empty after chunking")

    model = get_embedding_model()
    # fastembed's embed() is a lazy generator over blocking CPU work; run it
    # off the event loop so one big ingest doesn't stall other requests.
    embeddings = await asyncio.to_thread(lambda: list(model.embed(chunks)))

    await ensure_collection()
    client = get_qdrant_client()
    settings = get_settings()

    doc = KnowledgeDoc(
        id=uuid.uuid4().hex,
        workspace_id=workspace_id,
        title=title,
        source_type=source_type,
        source_url=source_url,
    )

    points: list[qmodels.PointStruct] = []
    chunk_rows: list[KnowledgeChunk] = []
    for index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        point_id = str(uuid.uuid4())
        points.append(
            qmodels.PointStruct(
                id=point_id,
                vector=embedding.tolist(),
                payload={
                    "doc_id": doc.id,
                    "doc_title": title,
                    "chunk_index": index,
                    "content": chunk,
                },
            )
        )
        chunk_rows.append(
            KnowledgeChunk(
                id=uuid.uuid4().hex,
                doc_id=doc.id,
                content=chunk,
                qdrant_point_id=point_id,
                chunk_index=index,
            )
        )

    await client.upsert(collection_name=settings.qdrant_collection, points=points)

    session.add(doc)
    session.add_all(chunk_rows)
    await session.commit()

    # Not a mapped column — a plain attribute for the caller's convenience
    # (e.g. reporting chunk count in the ingest response) so it doesn't need
    # a second query, or a lazy-load async SQLAlchemy can't do implicitly.
    doc.chunk_count = len(chunk_rows)  # type: ignore[attr-defined]
    return doc


async def search_knowledge(query: str, top_k: int = 5) -> list[dict]:
    """Embeds `query`, searches Qdrant, returns chunks shaped for an LLM tool
    result directly — no round trip to Postgres needed. `chunk_id` is the
    Qdrant point id, which is exactly `KnowledgeChunk.qdrant_point_id`, so
    callers can persist it (e.g. `CallTurn.citedChunkIds`) and it maps
    straight back to the Postgres row.
    """
    await ensure_collection()
    settings = get_settings()
    model = get_embedding_model()
    embedded = await asyncio.to_thread(lambda: list(model.embed([query])))
    query_vector = embedded[0].tolist()

    client = get_qdrant_client()
    result = await client.query_points(
        collection_name=settings.qdrant_collection,
        query=query_vector,
        limit=top_k,
        with_payload=True,
    )

    return [
        {
            "content": (point.payload or {}).get("content", ""),
            "score": point.score,
            "chunk_id": str(point.id),
            "doc_id": (point.payload or {}).get("doc_id", ""),
            "doc_title": (point.payload or {}).get("doc_title", ""),
            "chunk_index": (point.payload or {}).get("chunk_index"),
        }
        for point in result.points
    ]

"""Thin HTTP layer over tools/knowledge.py.

Every route here is server-to-server only (Next.js calls it via
web/src/lib/fastapi.ts) — protected by the same internal-secret dependency
as routers/agent.py. The dashboard's upload form and search box are what
this phase needs to prove retrieval works before any agent depends on it.
"""

from __future__ import annotations

import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession

from app.security import require_internal_secret
from db.engine import get_db
from tools.knowledge import ingest_document, search_knowledge

router = APIRouter(prefix="/knowledge", tags=["knowledge"], dependencies=[Depends(require_internal_secret)])


class IngestResponse(BaseModel):
    doc_id: str
    title: str
    chunk_count: int


class SearchResult(BaseModel):
    content: str
    score: float
    chunk_id: str
    doc_id: str
    doc_title: str
    chunk_index: int | None = None


def _extract_pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    workspace_id: str = Form(...),
    title: str = Form(...),
    text: str | None = Form(default=None),
    source_url: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    session: AsyncSession = Depends(get_db),
) -> IngestResponse:
    if not file and not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either `text` or `file`",
        )

    if file:
        data = await file.read()
        is_pdf = file.content_type == "application/pdf" or (file.filename or "").lower().endswith(".pdf")
        if is_pdf:
            body_text = _extract_pdf_text(data)
            source_type = "pdf"
        else:
            body_text = data.decode("utf-8", errors="ignore")
            source_type = "text"
    else:
        body_text = text or ""
        source_type = "text"

    if not body_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No extractable text found in the upload",
        )

    doc = await ingest_document(
        session=session,
        workspace_id=workspace_id,
        title=title,
        source_type=source_type,
        text=body_text,
        source_url=source_url,
    )

    return IngestResponse(doc_id=doc.id, title=doc.title, chunk_count=doc.chunk_count)  # type: ignore[attr-defined]


@router.get("/search", response_model=list[SearchResult])
async def search(q: str, top_k: int = 5) -> list[dict]:
    if not q.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Query must not be empty")
    return await search_knowledge(q, top_k=top_k)

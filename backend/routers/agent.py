"""Stub for now — the real SDR drafting agent lands in Phase 4/6.

Exists this early only so the internal-secret dependency has a protected
route to prove itself against (see Phase 0 verification in documents/plan.md).
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.security import require_internal_secret

router = APIRouter(prefix="/agent", tags=["agent"], dependencies=[Depends(require_internal_secret)])


@router.post("/draft")
async def draft_email():
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="SDR drafting agent is not implemented yet (Phase 4/6)",
    )

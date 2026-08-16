from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"status": "ok", "service": "backend/sales-agent"}


@router.get("/health/db")
async def health_db(session: AsyncSession = Depends(get_db)):
    """Proves the SQLAlchemy mirrors (db/models.py) can actually reach the
    Postgres instance Prisma migrates — separate from /health so a DB outage
    doesn't take down the plain liveness check."""
    await session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "reachable"}

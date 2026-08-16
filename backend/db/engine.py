from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    echo=False,
    pool_pre_ping=True,
    # Defends against a real bug class, not a hypothetical one: if
    # DATABASE_URL ever points at a PgBouncer-style transaction pooler (Neon's
    # pooled endpoint, Supabase, etc.) instead of a direct connection,
    # asyncpg's prepared-statement cache breaks — a pooled connection can
    # swap the underlying server connection between statements, so a cached
    # "prepared" statement can point at a connection that no longer has it.
    # Harmless no-op against a direct connection (what we actually use).
    connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0},
)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a session, always closed after the request."""
    async with async_session_factory() as session:
        yield session

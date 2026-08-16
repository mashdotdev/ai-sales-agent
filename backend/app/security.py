"""Auth for the Next.js -> FastAPI boundary.

The browser never calls FastAPI directly except the call WebSocket (which is
authorized separately by its own single-use token — see realtime/ws.py).
Every plain HTTP route is only ever called server-to-server from Next.js, so
a single shared secret header is enough; this is not a public API.
"""

from fastapi import Header, HTTPException, status

from app.config import get_settings


async def require_internal_secret(x_internal_secret: str = Header(default="")) -> None:
    settings = get_settings()

    if not settings.internal_api_secret:
        # Misconfiguration, not a client error — fail loudly rather than
        # silently accepting every request because the secret was never set.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="INTERNAL_API_SECRET is not configured on the server",
        )

    if x_internal_secret != settings.internal_api_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid internal secret",
        )

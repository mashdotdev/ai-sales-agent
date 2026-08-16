# Phase 0 + 1 — Done

> Read `documents/plan.md` first for the overall design, decisions, and constraints.
> This file is a factual record of what's actually built and verified, so a
> new session can pick up Phase 2 without re-deriving any of this.

## Status

**Phase 0 (Scaffold) and Phase 1 (DB + auth) are both complete and verified
end to end.** Nothing here is theoretical — every claim below was tested with
real requests against a running stack, not just written and assumed to work.

## What exists right now

### Repo layout

```
sales-agent/
  documents/
    plan.md          # the full design — read this first
    phase1.md         # this file
    phase2.md         # what to do next
  web/                # Next.js 16 App Router, bun, Prisma, Better Auth
    prisma/
      schema.prisma           # full schema — auth tables + all 13 domain tables
      migrations/20260816110000_init/
    prisma.config.ts          # driver-adapter config, reads DATABASE_URL from .env.local
    src/
      server/auth.ts          # Better Auth config (prismaAdapter, Resend, Google)
      lib/
        prisma.ts             # PrismaClient singleton (PrismaPg adapter)
        auth-client.ts        # signIn/signUp/signOut/useSession + requestGoogleWorkspaceAccess()
        fastapi.ts            # server-only fetch wrapper, injects X-Internal-Secret
      components/
        dashboard-shell.tsx   # the Phase 1 dashboard UI
      app/
        (auth)/sign-in/page.tsx
        (auth)/sign-up/page.tsx
        api/auth/[...all]/route.ts   # Better Auth route handler
        api/health/route.ts          # round-trips to FastAPI, proves the boundary works
        page.tsx                     # dashboard page (server component, session-gated)
    .env.example / .env.local
  backend/            # FastAPI, uv, Python 3.13
    app/
      config.py        # Settings (pydantic-settings), reads backend/.env
      security.py       # require_internal_secret dependency
      main.py           # FastAPI app, registers routers
    routers/
      health.py         # GET /health, GET /health/db
      agent.py           # POST /agent/draft — STUB, returns 501, protected by internal secret
    db/
      base.py            # SQLAlchemy DeclarativeBase
      engine.py           # async engine + get_db() dependency, Neon-pooler-safe connect_args
      models.py           # SQLAlchemy mirrors of ALL 13 Prisma domain tables (not the auth tables)
    ai_agents/          # empty (__init__.py only) — Phase 4/6
    tools/               # empty (__init__.py only) — Phase 2+
    realtime/            # empty — Phase 3
    models/              # empty — schemas as needed
    .env.example / .env
```

### Database: Neon Postgres (not Docker)

Decided and migrated during this phase — see `plan.md`'s Decisions table and
"Free-tier reality" section for the full reasoning. Short version:

- **One Neon project, two connection strings**, both already in the env files:
  - `web/.env.local` → **pooled** connection (has `-pooler` in the hostname). Prisma 5.10+ handles pooled connections fine for both `migrate` and the client.
  - `backend/.env` → **direct/non-pooled** connection (same hostname, minus `-pooler`). asyncpg's prepared-statement cache breaks against PgBouncer-style pooling, so the backend deliberately avoids the pooled endpoint. There's also a defensive `connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0}` in `backend/db/engine.py` in case that URL ever changes.
- `docker-compose.yml` **no longer exists**. There is nothing to `docker compose up` for the database.
- Qdrant is **not yet wired up** — it's Phase 2's job, on Qdrant Cloud (not Docker). See `phase2.md`.

### Auth: Better Auth + Prisma

- Email/password with `requireEmailVerification: true` — a fresh sign-up **cannot sign in** until the verification email is clicked. This only actually sends if `RESEND_API_KEY` is a real key; with the placeholder, sign-up still creates the row but verification email delivery silently no-ops (Resend call fails, sign-up response is still 200).
- Google OAuth is configured for plain login (`accessType: "offline"`, `prompt: "select_account consent"` — needed so Google actually returns a refresh token). **Gmail/Calendar scopes are NOT requested at login.** They're requested separately via `requestGoogleWorkspaceAccess()` in `lib/auth-client.ts`, which calls `authClient.linkSocial()` with the full scope list. This keeps first-time login a low-scope one-click consent screen. Nothing calls this function automatically — it's wired to the "Connect Google Workspace" button in the dashboard shell, and hasn't been exercised with real Google credentials yet (no `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` set).
- Dashboard (`web/src/app/page.tsx`) is a server component that calls `auth.api.getSession()`, redirects to `/sign-in` if there's no session, and queries `Account` for a Google row with a refresh token to decide whether to show "Connected" or the connect button.

### FastAPI ↔ Next.js boundary

- Every FastAPI route except the (future) call WebSocket requires an `X-Internal-Secret` header matching `INTERNAL_API_SECRET`, enforced by `app/security.py`'s `require_internal_secret` dependency.
- `web/src/lib/fastapi.ts` is the only place that should ever call FastAPI from Next.js — it injects the header automatically. Server-only; never import it from a client component.
- Backend runs on **port 8010**, not FastAPI's default 8000 — see "Known quirks" below for why. `FASTAPI_URL` in `web/.env.local` already points at 8010.

### SQLAlchemy mirrors (`backend/db/models.py`)

All 13 non-auth Prisma tables are mirrored: `Workspace`, `KnowledgeDoc`, `KnowledgeChunk`, `Lead`, `Campaign`, `CampaignLead`, `EmailMessage`, `Meeting`, `FollowUpTask`, `Suppression`, `ActivityLog`, `Call`, `CallTurn`. Better Auth's own tables (`User`, `Session`, `Account`, `Verification`) are **deliberately not mirrored** — FastAPI never reads them directly per the plan's boundary rule 2.

Two things worth knowing if you touch this file:

1. **`createdAt`/`updatedAt` need the `_created_at_col()`/`_updated_at_col()` helpers, not a bare `mapped_column("createdAt")`.** Prisma's `@default(now())` compiles to a real Postgres `DEFAULT CURRENT_TIMESTAMP`, so `createdAt` uses `server_default=func.now()`. Prisma's `@updatedAt` is enforced at the Prisma Client layer, not the DB — there's no DB-level default for it — so `updatedAt` uses client-side `default=func.now(), onupdate=func.now()` instead. Using the wrong one causes a `NotNullViolationError` on insert. This was caught and fixed during Phase 1, not a theoretical concern.
2. **This file is hand-maintained.** Every time `web/prisma/schema.prisma` changes, this file needs a matching manual update — nothing keeps them in sync automatically. If FastAPI throws a column-not-found or type-mismatch error after a schema change, this is almost certainly why.

### Verified working (actually tested, this session)

- `bunx prisma migrate deploy` against Neon — clean apply.
- Sign-up → row created in `User` table (`emailVerified: false`).
- Sign-in blocked with `403 EMAIL_NOT_VERIFIED` before verification — confirms the gate works.
- Manually verified a test user → sign-in → session → dashboard renders `Welcome, {name}` and the correct Google-connection status → confirms the whole session pipeline.
- Unauthenticated `GET /` → `307` redirect to `/sign-in`.
- `GET localhost:8010/health` → `200`.
- `GET localhost:8010/health/db` → `200`, proves SQLAlchemy can reach the same Neon database Prisma migrates.
- `POST /agent/draft` unauthenticated → `401`; with correct `X-Internal-Secret` → `501` (expected stub).
- `GET localhost:3000/api/health` → round-trips through all of the above in one call.
- SQLAlchemy mirror round-trip test: inserted/read back `Workspace`, `Lead` (enum columns `source`/`status`, JSONB `enrichment`), `Call`, `CallTurn` (`String[]` array column `citedChunkIds`), `EmailMessage`, and confirmed relationship traversal (`lead.calls`, `lead.email_messages`) all work correctly against the live schema.
- Confirmed Prisma and SQLAlchemy see the **same rows** in Neon (created a user via Better Auth's API, read it back via a raw SQL query through the SQLAlchemy session).
- All test/throwaway rows created during verification were deleted afterward — the database is clean.

## Known quirks (don't re-debug these)

- **Windows + `fastapi dev` crashes with `UnicodeEncodeError`** unless `PYTHONUTF8=1` is set first. It's `rich`/`fastapi_cli` trying to print an emoji through the cp1252 console codepage — nothing to do with the app. Documented in `backend/README.md`.
- **Port 8000 has a persistent phantom listener in this dev environment.** Something answers requests on `127.0.0.1:8000` that doesn't show up reliably in `Get-Process`/`Get-NetTCPConnection` lookups, and killing whatever PID *does* show up doesn't free it. Cost real debugging time before the fix was just "use a different port." **The backend now runs on 8010 by convention** — don't move it back to 8000 without expecting to hit this again.
- **Backgrounded dev servers don't reliably die between session restarts.** Multiple restarts this session left orphaned Python processes holding old code and answering requests while a "successfully started" new process sat unable to bind. If a code change doesn't seem to take effect, check `Get-NetTCPConnection -LocalPort <port>` for a stale owner before assuming the code is wrong.
- **Neon pooled vs direct connection is not a style choice** — using the pooled connection string for the SQLAlchemy/asyncpg engine will eventually produce intermittent, confusing "prepared statement does not exist" errors. Keep the split described above.

## Credentials currently in place vs. still placeholder

| Credential | Status |
|---|---|
| Neon `DATABASE_URL` (both variants) | ✅ real, working |
| `INTERNAL_API_SECRET` | ✅ generated, matches on both sides |
| `GEMINI_API_KEY` | ❌ placeholder — needed before Phase 2 embeddings/agents work meaningfully (fastembed doesn't need it, but nothing else does anything without it) |
| `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` | ❌ placeholder — Google login and the Workspace connect flow are wired but untested against real Google |
| `RESEND_API_KEY` | ❌ placeholder — email verification silently no-ops |
| `HUBSPOT_PRIVATE_APP_TOKEN` | ❌ placeholder — not needed until Phase 5 |
| `SLACK_WEBHOOK_URL` | ❌ placeholder — not needed until Phase 5 |
| Qdrant URL + API key | ❌ not created yet — needed before Phase 2 |

## How to resume dev servers

```
# Backend (from backend/)
set PYTHONUTF8=1 && uv run fastapi dev app/main.py --port 8010

# Web (from web/)
bun run dev
```

No `docker compose up` step anymore — Postgres is Neon (always on), Qdrant isn't wired up yet.

# AI Sales Employee — backend

FastAPI + `google-genai` (voice, via Gemini Live) + `openai-agents` (email, via
Gemini's OpenAI-compatible endpoint). See `../documents/plan.md` for the full
design.

## Layout

Flat top-level packages, run from this directory (`fastapi dev` puts `cwd` on
`sys.path`) — matches the sibling `multi-agent-stock-market/backend` project:

```
app/         config.py (Settings), security.py (internal-secret dependency), main.py
ai_agents/   voice + email agent definitions
tools/       shared tools — search_knowledge, get_crm_context, book_meeting, ...
routers/     FastAPI routers
realtime/    the call WebSocket relay (Phase 3+)
db/          SQLAlchemy models mirroring Prisma's schema (never migrates here)
models/      Pydantic schemas
```

## Run

```
uv run fastapi dev app/main.py --port 8010
```

Port 8010, not FastAPI's default 8000 — port 8000 turned out to have a
persistent phantom listener in this dev environment (nothing to do with the
app; a second, unrelated process would occasionally answer requests instead
of the one just started). `web/.env.local`'s `FASTAPI_URL` already points at
8010 — if you're on a machine where 8000 is actually free, either port works,
just keep both sides in sync.

**Windows note:** if that crashes immediately with a `UnicodeEncodeError` from
`rich`/`fastapi_cli` trying to print an emoji through the cp1252 console
codepage, force UTF-8 output:

```
set PYTHONUTF8=1
uv run fastapi dev app/main.py
```

(PowerShell: `$env:PYTHONUTF8=1`). This is a Windows console quirk in the
`fastapi dev` banner, unrelated to the app itself.

`GET /health` → `{"status": "ok", ...}`, unauthenticated.
`POST /agent/draft` → 401 without `X-Internal-Secret`, 501 with it (stub until Phase 4/6).

## Env

Copy `.env.example` to `.env` and fill in keys as you reach the phase that
needs them — `.env` here already has `DATABASE_URL` (Neon, direct/non-pooled
connection) and `INTERNAL_API_SECRET` pre-wired to match `web/.env.local`
(same Neon database; web/ uses the pooled connection instead — see the
comment in `.env.example` for why the two differ). No local database to
start — Postgres is Neon, Qdrant lands in Phase 2 on Qdrant Cloud.

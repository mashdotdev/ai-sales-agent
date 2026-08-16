# Phase 2 — Knowledge Base

> Read `documents/plan.md` (design) and `documents/phase1.md` (what's built,
> what's verified, what's a known quirk) before starting. This file is the
> actionable brief for Phase 2 specifically — detailed enough to execute
> without re-deriving decisions, but it doesn't repeat things those two files
> already cover.

## Why this phase, and why it's first after auth

From `plan.md`'s build order: **Knowledge → voice → CRM → email.** The voice
agent (Phase 3, the hero feature) is worthless without something real to
answer questions from — so the knowledge base has to exist and be provably
working *before* any agent is built on top of it. The success bar for this
phase is a plain search box that returns correct, relevant chunks. Prove
retrieval in isolation; don't let the first test of it be inside a live
voice call.

## What "done" looks like

- Upload a real document (PDF or plain text) through a form in the dashboard.
- It gets chunked, embedded, and stored.
- A search box on the same page returns the right chunks for a real query, with visible relevance scores.
- The data survives a server restart (it's in Postgres + Qdrant, not memory).

## Prerequisite: Qdrant Cloud (not created yet)

This is the one credential blocking this phase — nothing else needed to
start (Gemini isn't required yet either; `fastembed` runs fully local, no
API key). Get a free Qdrant Cloud cluster:

1. Sign up at https://cloud.qdrant.io (free tier, 1GB, no card).
2. Create a cluster, copy its **URL** (looks like `https://xxxxx.region.aws.cloud.qdrant.io:6333`) and generate an **API key**.
3. Fill in `backend/.env`:
   ```
   QDRANT_URL=<cluster url>
   QDRANT_API_KEY=<api key>
   QDRANT_COLLECTION=company_knowledge
   ```
   (These three lines already exist in `backend/.env` and `backend/.env.example` as empty placeholders from Phase 1 — just fill them in.)

## What already exists to build on — don't recreate these

- **Data model** (`web/prisma/schema.prisma`, already migrated to Neon): `KnowledgeDoc` (id, workspaceId, title, sourceType, sourceUrl, createdAt) and `KnowledgeChunk` (id, docId, content, **qdrantPointId** [unique], chunkIndex, createdAt). The design intent, per the plan: *Postgres holds the text and stays the source of truth; Qdrant holds the vector, keyed by `qdrantPointId`, so the index can always be rebuilt from Postgres if it's ever lost.*
- **SQLAlchemy mirrors** for both tables already exist in `backend/db/models.py` (`KnowledgeDoc`, `KnowledgeChunk` classes) — use these to write/read, don't hand-roll raw SQL.
- **Settings pattern**: `backend/app/config.py` already has `qdrant_url` and `qdrant_collection` fields. **You need to add `qdrant_api_key: str = ""`** — it's not there yet (Phase 1 didn't know Qdrant Cloud needed auth; local Docker Qdrant didn't).
- **Router pattern**: follow `backend/routers/health.py` / `agent.py` — `APIRouter`, internal-secret dependency via `Depends(require_internal_secret)` for anything not meant to be hit by the browser directly (everything in this phase goes through Next.js, so protect it the same way `agent.py` does).
- **The `db.get_db` dependency** (`backend/db/engine.py`) — inject `AsyncSession` the same way `routers/health.py`'s `/health/db` does.

## Build steps

1. **`backend/app/config.py`** — add `qdrant_api_key: str = ""`.

2. **`backend/tools/knowledge.py`** — the core module. This is also the first thing the voice agent (Phase 3) and email agent (Phase 6) will import, so keep the public function signatures clean and agent-agnostic (plain Python, no framework-specific decorators here — those get added as thin adapters later, per the plan's boundary rule 5: *tools are plain Python functions; `@function_tool`/`FunctionDeclaration` wrap them, they never fork the logic*):
   - `get_embedding_model()` — lazily loads a `fastembed.TextEmbedding` instance once (module-level singleton; loading it per-call would re-load the model from disk every time). Recommended model: `BAAI/bge-small-en-v1.5` (384-dim, fastembed's own suggested default, good quality/speed tradeoff). **Whatever model you pick, the Qdrant collection's vector size must match its output dimension** — get this wrong and every upsert fails with a dimension-mismatch error.
   - `get_qdrant_client()` — `qdrant_client.AsyncQdrantClient(url=..., api_key=...)`, module-level singleton.
   - `ensure_collection()` — create the Qdrant collection if it doesn't exist yet (check via `collection_exists`, then `create_collection` with the embedding model's vector size and cosine distance). Call this once at startup or lazily on first use — either is fine, just don't skip it and assume the collection exists.
   - `chunk_text(text: str, chunk_size=..., overlap=...) -> list[str]` — start simple: split on paragraphs/sentences, group into ~300–500 token chunks with a little overlap so context isn't severed mid-thought. Don't over-engineer this on the first pass; a naive splitter is fine to start and easy to improve later since chunks are keyed and rebuildable.
   - `ingest_document(session, workspace_id, title, source_type, text, source_url=None) -> KnowledgeDoc` — chunks the text, embeds all chunks in one batch (fastembed batches efficiently), upserts to Qdrant with a generated point id per chunk (store `doc_id`, `chunk_index`, and **the chunk text itself** in the Qdrant payload — storing the text in Qdrant too, not just Postgres, means search results don't need a round trip back to Postgres; Postgres stays authoritative for rebuilds, not for serving reads), then writes `KnowledgeDoc` + `KnowledgeChunk` rows via the SQLAlchemy mirrors with `qdrant_point_id` set to whatever id you gave Qdrant.
   - `search_knowledge(query: str, top_k=5) -> list[dict]` — embeds the query, searches Qdrant, returns chunks with their score and text from the Qdrant payload. This exact function is what gets wrapped as a tool for both agents later — keep its return shape something an LLM tool result can consume directly (list of `{content, score, chunk_id, doc_title}` or similar), since you won't want to reshape it again in Phase 3/6.

3. **`backend/routers/knowledge.py`**:
   - `POST /knowledge/ingest` — accepts a title + either raw text or an uploaded file. For the first pass, support plain text and PDF (add `pypdf` or `pymupdf` as a dependency for PDF text extraction — neither is installed yet). URL ingestion (fetch + strip HTML) is fine as a fast-follow, not required to call this phase done.
   - `GET /knowledge/search?q=...&top_k=5` — thin wrapper over `search_knowledge`, for the dashboard's search box to hit directly (and to prove retrieval works before any agent depends on it, per the whole point of this phase).
   - Register the router in `app/main.py` (`app.include_router(knowledge.router)`), same pattern as `health`/`agent`.

4. **`web/src/app/` — a knowledge page** under the dashboard (e.g. `(dashboard)/knowledge/page.tsx`, or add a section to the existing `page.tsx`/`dashboard-shell.tsx` if you'd rather keep the dashboard as one page for now — Phase 1 left it as a single page with placeholder sections for exactly this). Needs:
   - An upload form (title + file or pasted text) → calls `fastapi("/knowledge/ingest", { method: "POST", ... })` from `web/src/lib/fastapi.ts` (already built, already injects the internal secret — don't call FastAPI any other way from Next.js).
   - A search box → calls `/knowledge/search`, renders results with their scores.

5. **A `Workspace` row needs to exist** before any of this works — `KnowledgeDoc.workspaceId` is a required FK. Nothing in Phase 1 created one (there's no workspace-creation flow yet; the dashboard shell doesn't create a `Workspace` row on signup). Either seed one manually for now (a quick script or a raw insert) or, better, add minimal "create workspace on first login" logic while you're in here — your call, but **don't skip this and then be confused why ingestion 500s on a foreign-key violation**.

## New dependencies to add (backend)

```
uv add pypdf   # or pymupdf — PDF text extraction, pick one
```
`fastembed` and `qdrant-client` are already installed (Phase 0).

## Verification checklist

- [ ] `qdrant_api_key` added to `Settings`, cluster reachable (a simple `get_qdrant_client().get_collections()` call is a good smoke test).
- [ ] Collection created with the correct vector size for whatever embedding model was chosen.
- [ ] Upload a real document (use one of the "3–5 real company documents" from the plan's pre-flight checklist — if those were never gathered, grab something now; a generic Lorem Ipsum test proves plumbing but not retrieval quality).
- [ ] Confirm rows landed in both `KnowledgeDoc`/`KnowledgeChunk` (Postgres) and the Qdrant collection (point count matches chunk count).
- [ ] Search with a query the document actually answers → top result is relevant, score is sane (not near-zero, not identical across unrelated chunks).
- [ ] Search with a query **not** covered by any uploaded document → results should be low-relevance/low-score, not confidently wrong — this is what the voice agent will rely on in Phase 3 to know when to say "I don't know" instead of inventing an answer.
- [ ] Restart the backend process → data still there (proves nothing is in-memory-only).
- [ ] Fastembed's model download happens once on first use (~100MB+, cached under fastembed's cache dir) — confirm it doesn't try to redownload on every call.

## What NOT to build yet

- Any agent wiring (`@function_tool`/`FunctionDeclaration` wrappers around `search_knowledge`) — that's Phase 3 (voice) and Phase 6 (email). This phase only needs the plain-Python function and a way to prove it works from the dashboard.
- URL ingestion, if it's slowing things down — text + PDF is enough to call this phase done.
- Re-ranking, hybrid search, or anything fancier than top-k cosine similarity. Not needed until there's evidence naive search isn't good enough.

## Handoff to Phase 3

Once this phase is done, **write `documents/phase3.md` the same way this file
was written** — what's built, what's verified, exact function signatures the
voice agent will import (`search_knowledge`'s return shape especially), any
new quirks hit along the way, and what Phase 3 needs to start (per
`plan.md`: the WS relay, Gemini Live session loop, and the barge-in/`go_away`
handling — all detailed in the "The voice call (hero feature)" section of
`plan.md`).

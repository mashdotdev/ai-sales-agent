# Phase 2 — Done (mostly); Phase 3 — Voice, part 1

> Read `documents/plan.md` (design) and `documents/phase1.md` first. This
> file records what Phase 2 actually built and verified, the one thing left
> to verify once a real credential exists, and what Phase 3 needs to start.

## Status

**Phase 2 code is complete and wired end to end.** Everything that can be
verified without a live Qdrant Cloud cluster has been verified. The one
remaining item — real ingest/search against Qdrant — is blocked on the user
creating a free Qdrant Cloud cluster and putting `QDRANT_URL`/`QDRANT_API_KEY`
into `backend/.env`. Nothing else blocks Phase 3 from starting.

## What exists now (new this phase)

```
backend/
  app/config.py          # + qdrant_api_key: str = ""
  tools/knowledge.py      # get_embedding_model, get_qdrant_client, ensure_collection,
                           # chunk_text, ingest_document, search_knowledge
  routers/knowledge.py     # POST /knowledge/ingest, GET /knowledge/search
  app/main.py             # registers knowledge.router
  pyproject.toml          # + pypdf (PDF text extraction)

web/src/
  lib/workspace.ts                       # getOrCreateWorkspace() — single-workspace-for-v1
  lib/fastapi.ts                         # fixed: no longer forces Content-Type on FormData bodies
  app/page.tsx                            # calls getOrCreateWorkspace() on every dashboard load
  app/api/knowledge/ingest/route.ts       # session-gated proxy, injects workspace id server-side
  app/api/knowledge/search/route.ts       # session-gated proxy
  components/knowledge-section.tsx        # upload form + search box, added to dashboard-shell.tsx
```

## Key decisions made this phase

- **Workspace creation: auto-create on first login**, not a manual seed
  script. `getOrCreateWorkspace()` in `web/src/lib/workspace.ts` does a
  `findFirst()` and creates one row (`name: "My Workspace"`) if none exists.
  Called from `page.tsx` on every dashboard load (idempotent, cheap — one
  indexed SELECT) and again from the ingest API route so it never depends on
  prop-threading a workspace id through the UI.
- **Embedding model: `BAAI/bge-small-en-v1.5`, 384-dim**, fastembed's own
  suggested default. `EMBEDDING_DIM = 384` in `tools/knowledge.py` sizes the
  Qdrant collection — if this model ever changes, that constant must change
  with it or every upsert fails with a dimension mismatch.
- **Chunking is word-count-based, not token-based**: `chunk_text()` splits on
  paragraphs then sentences (regex, not a real sentence tokenizer), groups
  sentences into ~400-word chunks with ~60-word overlap carried from the tail
  of the previous chunk. No tokenizer dependency was pulled in — deliberately
  simple per phase2.md, and safe to improve later since chunks are keyed by
  their own Qdrant point id and fully rebuildable from Postgres.
- **`chunk_id` returned by `search_knowledge` is the Qdrant point id**, which
  is exactly `KnowledgeChunk.qdrant_point_id`. This was a deliberate choice
  so a caller (voice or email agent) can persist `chunk_id` directly into
  `CallTurn.citedChunkIds` / `EmailMessage.citedChunkIds` and it maps straight
  back to the Postgres row with no extra lookup or ID translation.
- **PDF extraction lives in the router, not in `tools/knowledge.py`.** Only
  the router deals with `UploadFile`/multipart; `ingest_document()` only ever
  takes already-extracted `text: str`, keeping the tools module plain-Python
  and framework-agnostic per boundary rule 5.
- **Found and fixed a real bug in `web/src/lib/fastapi.ts`**: it
  unconditionally set `Content-Type: application/json` whenever a body was
  present, which would have silently broken multipart file uploads (no
  boundary). Now skips that when `init.body instanceof FormData`.

## Exact function signatures Phase 3 will import

```python
# backend/tools/knowledge.py

async def search_knowledge(query: str, top_k: int = 5) -> list[dict]:
    """Returns a list of:
    {
        "content": str,       # the chunk text
        "score": float,       # cosine similarity, 0..1-ish (not guaranteed bounded)
        "chunk_id": str,      # == KnowledgeChunk.qdrant_point_id — persist this for citations
        "doc_id": str,        # == KnowledgeDoc.id
        "doc_title": str,
        "chunk_index": int | None,
    }
    """

async def ingest_document(
    session: AsyncSession,
    workspace_id: str,
    title: str,
    source_type: str,   # "pdf" | "text" (url ingestion not built — fast-follow, not required)
    text: str,
    source_url: str | None = None,
) -> KnowledgeDoc:
    ...  # doc.chunk_count is set as a plain (non-mapped) attribute for convenience
```

`search_knowledge` is exactly what Phase 3 wraps as a Gemini
`FunctionDeclaration` and Phase 6 wraps as an Agents SDK `@function_tool` —
per boundary rule 5, wrap it, don't reshape or fork it. The return shape was
chosen so an LLM tool result can consume it directly.

## Verification checklist — status

- [x] `qdrant_api_key` added to `Settings`.
- [x] `/knowledge/ingest` and `/knowledge/search` registered, internal-secret
      gated — confirmed `401` with no secret, correct routing with a valid
      one (verified via `app.openapi()` path listing and live curl).
- [x] Confirmed the exact `qdrant-client`/`fastembed` APIs used
      (`query_points`, `collection_exists`, `create_collection`, `upsert`,
      `TextEmbedding`) exist in the installed versions (`qdrant-client`
      1.19.0, `fastembed` 0.8.0) — checked directly against the installed
      packages, not assumed from memory.
- [x] Backend imports cleanly, Next.js `bun run build` and `bun run lint`
      both pass with the new files in place.
- [x] Hit `/knowledge/search` with a valid secret and no real Qdrant cluster
      configured — got the *expected* failure (`ResponseHandlingException:
      All connection attempts failed`, trying `localhost:6333`, the config
      default), not a code bug. This confirms the whole path down to the
      Qdrant client call is wired correctly.
- [ ] **Blocked on the user**: create a free Qdrant Cloud cluster, fill
      `QDRANT_URL`/`QDRANT_API_KEY` into `backend/.env`, then:
  - [ ] Collection auto-creates on first use with the correct vector size (384).
  - [ ] Upload a real document (PDF or text) through the dashboard.
  - [ ] Confirm row counts match: `KnowledgeDoc`/`KnowledgeChunk` in Postgres,
        point count in the Qdrant collection.
  - [ ] Search with a query the document answers → relevant top result, sane score.
  - [ ] Search with an off-topic query → low scores, not confidently wrong.
  - [ ] Restart the backend → data still there (proves nothing is in-memory).
  - [ ] Confirm the fastembed model downloads once (first call) and isn't
        re-fetched on subsequent calls (cache dir: fastembed's default, under
        the user's cache directory — not configured or moved in this phase).

## Known quirks hit this phase (don't re-debug these)

- **This environment's `fastapi` and `prisma` packages are ahead of my
  training data** (FastAPI 0.141.1, Prisma 7.9.1, Next.js 16.3.1, React
  19.2.8) — both ship their own `.agents`/`AGENTS.md`-style guidance
  (`backend/.venv/Lib/site-packages/fastapi/.agents/skills/fastapi/SKILL.md`,
  `web/AGENTS.md` pointing at `node_modules/next/dist/docs/`). Check those
  before assuming a remembered API still works. One concrete surprise this
  phase: `app.routes` no longer eagerly expands `include_router()`'d routes
  into `APIRoute` objects — they show up as opaque `_IncludedRouter` entries
  until something forces resolution (e.g. `app.openapi()`). Don't debug "my
  router didn't register" by inspecting `app.routes` directly in this
  FastAPI version; call `app.openapi()` and check `schema["paths"]` instead,
  or just hit the route with a live server.
- **`backend/.env`'s `QDRANT_URL=` (blank) does not fall back to the
  `Settings` field default.** pydantic-settings treats a present-but-empty
  env var as an explicit empty string for `str` fields, not "unset" — so with
  a blank `QDRANT_URL`, `AsyncQdrantClient` was constructed with `url=""` and
  qdrant-client itself fell back to trying `localhost:6333` (confirmed via
  the actual connection-refused error), not the `Settings` class's own
  `"http://localhost:6333"` default. Harmless here (both roads lead to "no
  local Qdrant, fails"), but worth knowing so a blank Cloud credential
  doesn't get misread as "using the local default."
- **Port 8010 has the same phantom-listener behavior Phase 1 documented for
  port 8000** — after backgrounding `fastapi run` for a smoke test, the
  owning PID had to be found via `Get-NetTCPConnection -LocalPort 8010
  -State Listen` and killed explicitly; it did not die on its own.

## What Phase 3 needs to start

Per `plan.md`'s "The voice call (hero feature)" section:

- The WS relay (`backend/realtime/ws.py`), Gemini Live session loop
  (`backend/realtime/session.py`), and tool bridge
  (`backend/realtime/tool_bridge.py`) are all still empty (`__init__.py`
  only) — Phase 3 creates all three.
- `search_knowledge` (signature above) is the only tool Phase 3 wires in —
  per `plan.md`, ship voice with search-only first; `capture_lead`/
  `check_availability`/`book_meeting` are Phase 4.
- `GEMINI_API_KEY` is still a placeholder in `backend/.env` — needed before
  Phase 3 can do anything (fastembed doesn't need it; the Live API does).
  Also confirm the current Gemini Live model id and free-tier quotas before
  starting (`plan.md` open decision 2) — `gemini-live-2.5-flash-preview` is
  what's in `config.py` now but Live models are preview-tagged and rename.
- The knowledge base needs at least one real document in it before a voice
  demo is worth anything — ingest the "3–5 real company documents" from the
  plan's pre-flight checklist once Qdrant is live, not synthetic filler.

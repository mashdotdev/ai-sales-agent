# AI Sales Employee — Implementation Plan

> **Status: not started.** The project directory is empty; no code has been written. The design below is settled — the decisions table and the three constraints are the outcome of a full planning pass, not defaults to be re-litigated. Build begins in a later session.
>
> **To resume:** read this file top to bottom, work the pre-flight checklist, then start at Phase 0. Two items still need a decision (see *Open decisions*); neither blocks Phase 0.

## Context

`A:\Coding\portfolio\latest-portfolio\sales-agent` is empty. The product is an **AI sales employee** working two channels off one brain:

- **Live voice calls (the hero feature).** A visitor clicks "Talk to our AI rep," speaks into their browser, and the agent qualifies them, answers product questions from the company knowledge base, handles objections, and books a meeting on a real calendar while they're still on the line.
- **Email SDR (the supporting loop).** Pulls leads from HubSpot, writes and sends personalized outreach from Gmail, detects replies, books meetings, updates the CRM, creates follow-up tasks, pings Slack.

Both live in one codebase because **they share a tools layer**: `search_knowledge`, `get_crm_context`, `book_meeting`, `update_hubspot`, `create_task`, `notify_slack` are written once in Python and consumed by both agents. Voice isn't a second product — it's a second mouth on the same brain. That's also the pitch.

**Hard constraint: $0 budget.** No OpenAI key, no paid services. Everything below runs on free tiers or locally. This shaped several decisions and is called out where it costs something real.

### Decisions

| Area | Choice |
|---|---|
| Call channel | Browser mic widget only — no PSTN, no outbound dialing |
| Voice model | **Google Gemini Live API** (`google-genai`), server-relay |
| Text agents | OpenAI Agents SDK pointed at **Gemini's OpenAI-compatible endpoint** |
| Embeddings | **fastembed**, local CPU — no API, no quota |
| Close depth | Qualify → handle objections → book meeting. No payments |
| Orchestration | Inngest in Next.js invoking FastAPI — post-call and email work only |
| Integrations | Real APIs on your own test accounts, behind a `DRY_RUN` flag |
| Vector store | Qdrant Cloud free tier (Phase 2 — not wired up yet, no local fallback) |
| State | **Neon Postgres**; **Prisma owns the schema**, FastAPI reads it via SQLAlchemy |
| Auth | Better Auth |
| Build order | Knowledge → voice → CRM → email |

### The three constraints that shaped this

**No outbound AI dialing.** The FCC's Feb 2024 declaratory ruling put AI-generated voices under the TCPA's "artificial voice" prohibition — outbound AI calls to US cell numbers need prior express consent, with per-call statutory penalties. Inbound browser calls are consented by definition (the visitor clicked), cost nothing in telephony, and demo better: anyone can try it in five seconds without surrendering a phone number.

**"Close" means booked commitment, not payment.** Card details over an AI voice call pulls the project into PCI scope and call-recording consent law, and demos no better than a booked meeting. The agent closes by getting a slot committed, live.

**Voice can't use the Agents SDK.** `RealtimeAgent`/`RealtimeRunner` speak OpenAI's Realtime protocol specifically — LiteLLM and custom providers cover text models only, so there is no base-URL swap for speech-to-speech. The voice session loop is hand-written against `google-genai`. The *text* agents keep the Agents SDK unchanged (`set_default_openai_client` + `set_tracing_disabled(True)`), so this costs us one module, not the architecture.

### Conventions

Follow the siblings: `multi-agent-stock-market/backend` (Python 3.13, `uv`, FastAPI, `openai-agents`, `app/ ai_agents/ tools/ routers/ models/`) and `saas-starter-kit/apps/web/src/server/auth.ts` (Better Auth + `prismaAdapter`, Resend, Google social provider) — that auth file is close to copy-paste usable.

---

## Architecture

```
sales-agent/
  # No docker-compose.yml — Postgres is Neon, Qdrant is Qdrant Cloud (Phase 2).
  # Nothing to run locally besides the two dev servers below.
  web/                          # Next.js 16 App Router, bun, Prisma, Better Auth, Inngest
    prisma/schema.prisma        # single source of truth for the relational schema
    src/
      server/auth.ts
      lib/{prisma,inngest,fastapi}.ts
      components/voice/         # CallWidget, mic capture, playback, live transcript
      hooks/useVoiceCall.ts     # AudioWorklet capture + WS + playback queue
      inngest/functions/        # call.completed, campaign.run, lead.outreach, reply.handle
      app/
        api/auth/[...all]/route.ts
        api/inngest/route.ts
        api/voice/session/route.ts    # mints a single-use call token
        (dashboard)/...               # calls, leads, campaigns, inbox, knowledge, settings
  backend/                      # FastAPI
    app/{main,config,security}.py
    realtime/
      ws.py                     # /ws/call/{callId} — relay endpoint
      session.py                # Gemini Live loop: audio in/out, tool_call dispatch, resumption
      tool_bridge.py            # shared tools -> Gemini FunctionDeclarations
      recorder.py               # transcript + turn persistence
    ai_agents/
      voice_prompt.py           # system instruction assembled from Workspace
      sdr_agent.py              # email drafting (Agents SDK)
      reply_agent.py            # inbound email replies (Agents SDK)
      guardrails.py
    tools/{knowledge,crm,calendar,gmail,slack,tasks}.py   # SHARED, plain Python
    models/schema.py
    routers/{agent,knowledge,calls,health}.py
    db/                         # SQLAlchemy models mirroring Prisma tables (no migrations)
```

### Boundary rules

1. **Prisma is the only thing that migrates.** Python mirrors the tables in SQLAlchemy and never migrates. After each `prisma migrate dev`, hand-update the mirrors. Real maintenance cost, accepted deliberately.
2. **Next.js is the sole Google *OAuth* token authority.** Better Auth holds the user's Google refresh token (Gmail/Calendar) in its `Account` table and mints short-lived access tokens via `auth.api.getAccessToken`, passed to FastAPI per call. FastAPI never refreshes — two processes racing one refresh token gives intermittent `invalid_grant` failures that are miserable to debug. *(Separate concern from the Gemini API key, which is a plain server-side env var in FastAPI.)*
3. **Next.js → FastAPI uses a shared `INTERNAL_API_SECRET` header.** The browser never calls FastAPI directly *except* the call WebSocket, authorized by its own single-use token.
4. **Realtime during the call, durable after it.** A call is a stateful connection held open for minutes — it does not fit Inngest's step-function model, and forcing it there is the main way this project goes wrong. The call lives entirely in one FastAPI WebSocket handler. On hangup, FastAPI emits `call/completed` and everything durable (CRM write-back, recap email, task, Slack) runs in Inngest with retries.
5. **Tools are plain Python functions with an explicit JSON schema.** Two thin adapters expose them: `@function_tool` for the Agents SDK (email) and `types.FunctionDeclaration` for Gemini Live (voice). Write the tool once; never fork the logic.

---

## The voice call (hero feature)

### Why server-relay

The browser could talk to Gemini directly, but tool calls would surface client-side — meaning CRM lookups and calendar writes either run in the browser (unacceptable: credentials exposed, and a hostile client can forge tool results) or get relayed back anyway. Server-relay keeps every tool in Python with direct Qdrant/Postgres/HubSpot access and reuses the email agent's tools verbatim.

### Path

```
Browser mic → AudioWorklet → PCM16 16kHz → WS /ws/call/{id} → FastAPI
  → session.send_realtime_input(audio=Blob(data=..., mime_type="audio/pcm;rate=16000"))
  ← session.receive() → LiveServerMessage:
        server_content.model_turn      → audio out (PCM16 24kHz)
        server_content.interrupted     → flush client playback queue
        server_content.*_transcription → CallTurn rows
        tool_call                      → dispatch → send_tool_response(id=...)
        go_away / session_resumption_update → reconnect transparently
FastAPI → WS → browser → playback queue → speakers
```

### Session config

`client.aio.live.connect(model="gemini-live-2.5-flash-preview", config=LiveConnectConfig(...))` with:
- `response_modalities=["AUDIO"]`, `speech_config` with a chosen voice
- `input_audio_transcription` **and** `output_audio_transcription` enabled — this is how `CallTurn` gets populated; without it you have audio and no record
- `realtime_input_config.activity_handling = START_OF_ACTIVITY_INTERRUPTS` for barge-in, with `automatic_activity_detection` silence/sensitivity tuned by ear
- `tools=[FunctionDeclaration...]` from the tool bridge
- `session_resumption` enabled (see below)

Note the asymmetry: **input is 16kHz, output is 24kHz.** Resampling both directions in the AudioWorklet is a small thing that will absolutely bite if missed.

### Four details that decide whether this feels good or broken

1. **Session limits and `go_away`.** Live API sessions have server-side time limits and the server sends `go_away` before disconnecting. A 10-minute sales call will outlive one session. Handle `session_resumption_update`, store the handle, and reconnect transparently on `go_away` — the caller should never hear it. **This is the single most likely thing to break a long demo call**, and it has no equivalent in the OpenAI plan.
2. **Barge-in and playback lag.** The server knows what it *sent*; the browser is still playing audio buffered ahead. On `server_content.interrupted`, flush the client queue immediately — otherwise the agent keeps talking over the person for a second after they cut in, which reads as broken.
3. **Tool calls must not create dead air.** A HubSpot lookup or freebusy query is 300–800ms of silence. Instruct the agent to speak a filler before slow tools, and handle `tool_call_cancellation` (the model can abandon a call it no longer wants).
4. **Grounded answers only.** The agent must never invent product facts — `search_knowledge` results only, with an explicit "I'll find out and follow up" fallback. Persist cited chunk ids per turn: a trust feature and the most interesting thing on the dashboard.

### Authorizing the call socket

Browser → `POST /api/voice/session` (Next.js) → creates a `Call` row, returns a single-use short-TTL token. Browser opens `wss://.../ws/call/{callId}?token=...`; FastAPI validates against Postgres, marks it consumed, starts the session. **Per-IP rate limit and a hard server-side duration cap are phase-3 requirements, not polish** — on a free tier an open mic endpoint doesn't cost money, it burns your daily quota and takes the demo offline.

### Agent design

System instruction assembled from `Workspace` (company, offer, ICP, tone, persona name) plus a discovery framework. Tools: `search_knowledge`, `get_crm_context`, `capture_lead`, `check_availability`, `book_meeting`, `flag_for_human`. On hangup: transcript, structured qualification summary, sentiment and objections persisted, then `call/completed` fires.

### The demo

Visitor clicks the widget → agent greets → asks what they're working on → answers a pricing question citing the knowledge base → handles "that's more than we budgeted" → offers Thursday 2pm → books it → invite lands in their inbox and the contact appears in HubSpot with a call summary, before they leave the page.

---

## Free-tier reality

Everything runs at $0, but three things need eyes open:

- **Gemini free tier has real limits** on Live API concurrent sessions and daily usage, the Live models are preview-tagged and rename periodically, and **free-tier data may be used for model improvement** — so demo with synthetic prospects, not real customer data. Verify current quotas before phase 3 rather than discovering them mid-build.
- **Deploying the WebSocket backend is the one genuinely awkward part.** Vercel hosts the Next.js app fine, but long-lived WebSockets need a real always-on process. Render's free tier cold-starts ~50s after idling, which ruins a portfolio demo. Hugging Face Spaces (Docker SDK) is the best free fit — always-on and WebSocket-friendly. **Decide before phase 8; local dev is unaffected.**
- **Postgres is Neon** (decided during Phase 1, replacing the original local-Docker plan — no card required, and it removes Docker Desktop as a dependency entirely for the DB). One Neon project, two connection strings: `web/.env.local` uses the **pooled** one (Prisma 5.10+ supports pooled connections for both migrate and client), `backend/.env` uses the **direct/non-pooled** one (asyncpg's prepared-statement cache breaks against PgBouncer-style pooling — see the comment on `connect_args` in `backend/db/engine.py`). Same database either way, just two entry points into it.
- Free elsewhere: Qdrant Cloud (1GB, Phase 2), Resend (3k/mo), Inngest, HubSpot developer sandbox, Slack webhooks, Vercel Hobby.

---

## Data model (Prisma)

Better Auth tables (`User`, `Session`, `Account`, `Verification`) come from its CLI — don't hand-write them.

**Voice:** `Call` (status `pending | live | completed | failed`, single-use token + consumed flag, duration, outcome `booked | qualified | not_fit | abandoned`, qualification JSON, sentiment, consent flag, resumption handle) · `CallTurn` (role, text, timestamps, cited chunk ids, tool calls — powers live transcript and post-call review).

**Shared:** `Workspace` (identity, persona, tone, offer, `dryRun`, `dailySendCap`, HubSpot/Slack creds) · `KnowledgeDoc`/`KnowledgeChunk` (text in Postgres, vectors in Qdrant keyed by `chunkId`, so the index is always rebuildable) · `Lead` (`hubspotContactId`, contact fields, `source: call | email | manual`, status, enrichment) · `Meeting` · `Campaign`/`CampaignLead` · `EmailMessage` · `FollowUpTask` · `Suppression` · `ActivityLog` (append-only agent action feed — makes the demo legible).

---

## Open decisions

Neither blocks Phase 0. Both should be closed before the phase named.

1. **WebSocket host for the FastAPI backend** — *decide before Phase 8.* Vercel hosts the Next.js app fine, but a long-lived call socket needs an always-on process. Render's free tier cold-starts ~50s after idling, which wrecks a portfolio demo. Hugging Face Spaces (Docker SDK) is the leading candidate: always-on and WebSocket-friendly. Local dev is unaffected either way.
2. **Gemini Live free-tier quotas** — *verify before Phase 3.* Concurrent-session and daily limits change, and Live models are preview-tagged (they get renamed). Confirm current limits and the exact model id in AI Studio rather than trusting `gemini-live-2.5-flash-preview` to still resolve.

---

## Pre-flight checklist

Work through this before Phase 0 — each item has blocked someone at some point.

- [ ] Google AI Studio API key created (powers **both** voice and text agents).
- [ ] Confirm the current Gemini Live model id and free-tier quotas (open decision 2).
- [ ] Google Cloud project: OAuth client created, **Gmail API and Calendar API explicitly enabled**, your own address added under *Test users*. The app stays unverified — fine for ≤100 testers, but without the test-user entry consent fails with an opaque error.
- [ ] HubSpot developer account + a test/sandbox portal, private app token with contacts, companies, deals, tasks, and engagements scopes.
- [ ] Slack workspace with an incoming webhook URL.
- [ ] Resend account and API key (`onboarding@resend.dev` works until you own a sending domain).
- [x] Neon project created, both connection strings (pooled + direct) in hand — done in Phase 1.
- [ ] Qdrant Cloud free-tier cluster (URL + API key) — needed before Phase 2, not before.
- [ ] Node/bun and Python 3.13 + `uv` available.
- [ ] A headset with a real microphone. Laptop speakers into a laptop mic causes echo the model hears as speech, and it will interrupt itself constantly — this looks like a barge-in bug and is not one.
- [ ] 3–5 real company documents to ingest (pricing, product one-pager, FAQ). The voice demo is only as good as the knowledge base, so gather these before Phase 2, not during.
- [ ] Test contacts you personally own for the email phases — never seed a stranger's address.

---

## Build phases

Each phase should end in something runnable. Phases 3 and 4 are the hero feature; everything before them exists to make them possible and everything after makes them look like an employee rather than a demo.

**0 — Scaffold. ✅** `bun create next-app` in `web/`; `uv init` in `backend/` with `fastapi[standard]`, `google-genai`, `openai-agents`, `fastembed`, `qdrant-client`, `pydantic-settings`, `sqlalchemy[asyncio]`, `asyncpg`, `google-api-python-client`, `google-auth`, `hubspot-api-client`, `websockets`. Health check both directions, `.env.example` each. (Originally planned around a local `docker-compose.yml` for Postgres + Qdrant — dropped during Phase 1 in favor of Neon; see Decisions and Free-tier reality above. Backend runs on port 8010, not FastAPI's default 8000 — see `backend/README.md`.)

**1 — DB + auth. ✅** Prisma schema, `migrate deploy` against Neon, Better Auth per `saas-starter-kit/apps/web/src/server/auth.ts` (reuse its Resend verification/reset handlers as-is). Google Workspace connect flow requesting `gmail.send`, `gmail.readonly`, `gmail.modify`, `calendar.events`, `calendar.freebusy` with `accessType: "offline"` — a separate action, not at signup, so login stays a low-scope one-click. SQLAlchemy mirrors + internal-secret dependency. Dashboard shell. Verified end to end: sign-up → email-verification gate → sign-in → session, and the SQLAlchemy mirrors round-tripping enums/JSONB/arrays/relationships against the same Neon database Prisma migrates.

**2 — Knowledge base.** Ingest (PDF/docs/URL), chunking, **fastembed** embeddings, Qdrant upsert, `search_knowledge`, and a knowledge page with a search box. Voice is worthless without this, and a plain search box proves retrieval before any agent depends on it.

**3 — Voice, part 1: talking.** WS relay, Gemini Live session loop, tool bridge, AudioWorklet capture/playback with 16k↔24k resampling, live transcript UI, `go_away`/resumption handling, duration cap and rate limit. Ship with `search_knowledge` as the only tool. **Milestone: a real conversation about your company, with working interruption, that survives past the session limit.** Deliberately early — this is the risky part.

**4 — Voice, part 2: closing.** `capture_lead`, `check_availability`, `book_meeting` against real Calendar. Summary + qualification extraction on hangup. `call/completed` → Inngest. **Milestone: a call ends with a real calendar invite.**

**5 — CRM.** HubSpot private-app token, contact/company sync, `get_crm_context`, write-back (contact upsert, call summary as engagement, deal stage, tasks). Slack on booked calls. Leads + calls dashboard.

**6 — Email SDR.** Agents SDK wired to Gemini's OpenAI-compatible endpoint. Inngest client + `/api/inngest`, `campaign.run`/`lead.outreach`, SDR drafting, approval gate via `step.waitForEvent`, guardrails, Gmail send.

**7 — Reply loop + follow-ups.** Gmail history-API poller on an Inngest cron **first** (Pub/Sub push needs a public URL and a GCP topic — a bad thing to be blocked on), reply agent with intent classification, then `step.sleep`/`cancelOn` sequences. Add Pub/Sub last as an upgrade; keep the poller as fallback.

**8 — Deploy + polish.** Pick the WebSocket host, landing page built around the widget, activity feed, call review with citations, metrics.

---

## Guardrails

**Voice:** hard duration cap + per-IP rate limit on session creation (quota protection). Disclose it's an AI in the greeting — several US states require it and it costs nothing. Transcript/recording consent in the widget before the mic opens. `flag_for_human` escalation. Knowledge-grounded answers only; never invent pricing.

**Email:** `DRY_RUN` defaults to **true** — sending requires explicit opt-in. Suppression checked immediately before every send, not just at draft time. Per-workspace daily cap. Unsubscribe line in every cold email. Approval queue on by default. Send only from a domain you control with SPF/DKIM. README notes that unsolicited commercial email is regulated (CAN-SPAM, GDPR/PECR) and the demo uses seeded test contacts.

---

## Verification

**Infra:** `docker compose up -d` → Postgres + Qdrant reachable; `bunx prisma migrate dev` clean; `uv run fastapi dev` → `/health` ok; unauthenticated `/agent/draft` → 401.

**Knowledge:** upload a doc → search box returns relevant chunks with sane scores; confirm fastembed model downloads once and caches.

**Voice (the core):**
- Click widget, grant mic → agent greets within ~1s of connect.
- Ask something answerable only from an uploaded doc → correct answer, correct chunk ids on the `CallTurn`.
- Ask something absent from the knowledge base → declines and offers follow-up rather than inventing.
- **Interrupt mid-sentence** → audio stops immediately and it responds to what you actually said.
- **Talk past the Live session limit** → `go_away` handled, session resumed, caller hears nothing. Test this explicitly; it will not show up in a two-minute test.
- Trigger a slow tool → it fills the silence instead of going dead.
- Exceed the duration cap → clean close, `Call` row `completed`.
- Reload mid-call → no orphaned session, no quota still burning.
- Replay a used call token → rejected.

**Closing:** agree to a slot → Calendar event created, invite in your inbox, `Meeting` row written, HubSpot contact upserted with summary, Slack pinged.

**Email:** seed 3 leads (addresses you own), `DRY_RUN=true` → drafts cite knowledge and CRM facts, Gmail never called. Flip false, approve one → arrives with unsubscribe line. Reply "sure, Thursday?" → books. Reply "unsubscribe" → `Suppression` row, no reply, future sends blocked. Kill FastAPI mid-campaign → Inngest retries, no duplicate sends.

---

## Credentials to gather (all free)

Google AI Studio API key (Gemini — powers both voice and text agents) · Google Cloud OAuth client with Gmail + Calendar APIs enabled and test users added (unverified app is fine for ≤100 testers) · HubSpot developer sandbox + private app token · Slack incoming webhook · Resend key (`onboarding@resend.dev` works until you have a domain) · Inngest keys (dev server needs none).

## Deferred

OpenAI Realtime as a swappable voice adapter if a budget appears · Twilio PSTN inbound · consented outbound callbacks · Stripe quotes and payment links · multi-tenant workspaces · lead enrichment vendors · subject-line A/B tests · deliverability warmup · call-quality evals.

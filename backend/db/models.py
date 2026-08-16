"""SQLAlchemy mirrors of the Prisma-owned schema.

Boundary rule 1 (documents/plan.md): Prisma is the only thing that migrates.
These models are hand-maintained to match web/prisma/schema.prisma — after
every `prisma migrate dev`, update this file to match. Never call
`Base.metadata.create_all()` or point Alembic at this database; if the two
schemas drift, the migration in web/ is correct and this file is stale.

Better Auth's own tables (User, Session, Account, Verification) are
deliberately not mirrored here — FastAPI never reads them directly. Next.js
is the sole OAuth token authority (boundary rule 2) and only ever hands
FastAPI a short-lived access token per request, never the underlying rows.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base

# ─── Enums ───────────────────────────────────────────────────────────────
# create_type=False: Prisma already created these types via migration; this
# process must never try to (re)create them.

LeadSource = PgEnum("call", "email", "manual", name="LeadSource", create_type=False)
LeadStatus = PgEnum(
    "new",
    "researching",
    "queued",
    "contacted",
    "replied",
    "meeting_booked",
    "disqualified",
    "unsubscribed",
    name="LeadStatus",
    create_type=False,
)
EmailDirection = PgEnum("inbound", "outbound", name="EmailDirection", create_type=False)
EmailStatus = PgEnum(
    "draft", "pending_approval", "sent", "failed", "suppressed",
    name="EmailStatus", create_type=False,
)
CallStatus = PgEnum("pending", "live", "completed", "failed", name="CallStatus", create_type=False)
CallOutcome = PgEnum(
    "booked", "qualified", "not_fit", "abandoned", name="CallOutcome", create_type=False
)
CallTurnRole = PgEnum("user", "agent", name="CallTurnRole", create_type=False)


def _cuid_str_pk() -> Mapped[str]:
    """Every table uses Prisma's cuid() text ids — never generated here."""
    return mapped_column("id", Text, primary_key=True)


def _created_at_col() -> Mapped[dt.datetime]:
    """Matches Prisma's `@default(now())`, which compiles to an actual
    `DEFAULT CURRENT_TIMESTAMP` in the migration — server_default is correct
    here because the DB really does have that default, so it's safe to omit
    this column from INSERTs written by FastAPI and let Postgres fill it."""
    return mapped_column("createdAt", server_default=func.now())


def _updated_at_col() -> Mapped[dt.datetime]:
    """Matches Prisma's `@updatedAt`, which Prisma Client sets at the app
    layer on every write — the migration gives this column NO db-level
    default. Use default=/onupdate= (a client-side SQL expression sent with
    every statement) rather than server_default, or an INSERT/UPDATE from
    this process would hit the same NOT NULL violation Prisma's own default
    would never trigger, since there'd be nothing for Postgres to fall back on."""
    return mapped_column("updatedAt", default=func.now(), onupdate=func.now())


# ─── Workspace + knowledge base ─────────────────────────────────────────────


class Workspace(Base):
    __tablename__ = "Workspace"

    id: Mapped[str] = _cuid_str_pk()
    name: Mapped[str] = mapped_column(Text)
    persona_name: Mapped[str] = mapped_column("personaName", Text, default="Alex")
    tone: Mapped[str | None] = mapped_column(Text)
    offer: Mapped[str | None] = mapped_column(Text)
    icp: Mapped[str | None] = mapped_column(Text)
    dry_run: Mapped[bool] = mapped_column("dryRun", Boolean, default=True)
    daily_send_cap: Mapped[int] = mapped_column("dailySendCap", Integer, default=20)
    hubspot_portal_id: Mapped[str | None] = mapped_column("hubspotPortalId", Text)
    slack_webhook_url: Mapped[str | None] = mapped_column("slackWebhookUrl", Text)
    created_at: Mapped[dt.datetime] = _created_at_col()
    updated_at: Mapped[dt.datetime] = _updated_at_col()

    knowledge_docs: Mapped[list["KnowledgeDoc"]] = relationship(back_populates="workspace")
    leads: Mapped[list["Lead"]] = relationship(back_populates="workspace")
    campaigns: Mapped[list["Campaign"]] = relationship(back_populates="workspace")
    calls: Mapped[list["Call"]] = relationship(back_populates="workspace")


class KnowledgeDoc(Base):
    __tablename__ = "KnowledgeDoc"

    id: Mapped[str] = _cuid_str_pk()
    workspace_id: Mapped[str] = mapped_column("workspaceId", ForeignKey("Workspace.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column("sourceType", Text)  # "pdf" | "url" | "text"
    source_url: Mapped[str | None] = mapped_column("sourceUrl", Text)
    created_at: Mapped[dt.datetime] = _created_at_col()

    workspace: Mapped["Workspace"] = relationship(back_populates="knowledge_docs")
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(back_populates="doc")


class KnowledgeChunk(Base):
    __tablename__ = "KnowledgeChunk"

    id: Mapped[str] = _cuid_str_pk()
    doc_id: Mapped[str] = mapped_column("docId", ForeignKey("KnowledgeDoc.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text)
    # Key into the Qdrant collection — Postgres stays the source of truth so
    # the vector index can always be rebuilt from here.
    qdrant_point_id: Mapped[str] = mapped_column("qdrantPointId", Text, unique=True)
    chunk_index: Mapped[int] = mapped_column("chunkIndex", Integer)
    created_at: Mapped[dt.datetime] = _created_at_col()

    doc: Mapped["KnowledgeDoc"] = relationship(back_populates="chunks")


# ─── Leads, campaigns, email ────────────────────────────────────────────────


class Lead(Base):
    __tablename__ = "Lead"

    id: Mapped[str] = _cuid_str_pk()
    workspace_id: Mapped[str] = mapped_column("workspaceId", ForeignKey("Workspace.id", ondelete="CASCADE"))
    hubspot_contact_id: Mapped[str | None] = mapped_column("hubspotContactId", Text, unique=True)
    email: Mapped[str] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    company: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(LeadSource, default="manual")
    status: Mapped[str] = mapped_column(LeadStatus, default="new")
    enrichment: Mapped[dict | None] = mapped_column(JSONB)
    last_synced_at: Mapped[dt.datetime | None] = mapped_column("lastSyncedAt")
    created_at: Mapped[dt.datetime] = _created_at_col()
    updated_at: Mapped[dt.datetime] = _updated_at_col()

    workspace: Mapped["Workspace"] = relationship(back_populates="leads")
    campaign_leads: Mapped[list["CampaignLead"]] = relationship(back_populates="lead")
    email_messages: Mapped[list["EmailMessage"]] = relationship(back_populates="lead")
    meetings: Mapped[list["Meeting"]] = relationship(back_populates="lead")
    calls: Mapped[list["Call"]] = relationship(back_populates="lead")
    follow_up_tasks: Mapped[list["FollowUpTask"]] = relationship(back_populates="lead")
    suppression: Mapped["Suppression | None"] = relationship(back_populates="lead")


class Campaign(Base):
    __tablename__ = "Campaign"

    id: Mapped[str] = _cuid_str_pk()
    workspace_id: Mapped[str] = mapped_column("workspaceId", ForeignKey("Workspace.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    icp: Mapped[str | None] = mapped_column(Text)
    offer: Mapped[str | None] = mapped_column(Text)
    auto_send: Mapped[bool] = mapped_column("autoSend", Boolean, default=False)
    created_at: Mapped[dt.datetime] = _created_at_col()
    updated_at: Mapped[dt.datetime] = _updated_at_col()

    workspace: Mapped["Workspace"] = relationship(back_populates="campaigns")
    campaign_leads: Mapped[list["CampaignLead"]] = relationship(back_populates="campaign")


class CampaignLead(Base):
    __tablename__ = "CampaignLead"

    id: Mapped[str] = _cuid_str_pk()
    campaign_id: Mapped[str] = mapped_column("campaignId", ForeignKey("Campaign.id", ondelete="CASCADE"))
    lead_id: Mapped[str] = mapped_column("leadId", ForeignKey("Lead.id", ondelete="CASCADE"))
    step: Mapped[int] = mapped_column(Integer, default=0)
    # Loose string, not an enum — the Phase 7 sequence engine owns this
    # vocabulary and it's cheaper to let it evolve than migrate an enum.
    status: Mapped[str] = mapped_column(Text, default="pending")
    created_at: Mapped[dt.datetime] = _created_at_col()

    campaign: Mapped["Campaign"] = relationship(back_populates="campaign_leads")
    lead: Mapped["Lead"] = relationship(back_populates="campaign_leads")


class EmailMessage(Base):
    __tablename__ = "EmailMessage"

    id: Mapped[str] = _cuid_str_pk()
    lead_id: Mapped[str] = mapped_column("leadId", ForeignKey("Lead.id", ondelete="CASCADE"))
    direction: Mapped[str] = mapped_column(EmailDirection)
    status: Mapped[str] = mapped_column(EmailStatus, default="draft")
    gmail_thread_id: Mapped[str | None] = mapped_column("gmailThreadId", Text)
    gmail_message_id: Mapped[str | None] = mapped_column("gmailMessageId", Text)
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    # KnowledgeChunk ids the agent cited when drafting.
    cited_chunk_ids: Mapped[list[str]] = mapped_column("citedChunkIds", ARRAY(String), default=list)
    sent_at: Mapped[dt.datetime | None] = mapped_column("sentAt")
    created_at: Mapped[dt.datetime] = _created_at_col()

    lead: Mapped["Lead"] = relationship(back_populates="email_messages")


class Meeting(Base):
    __tablename__ = "Meeting"

    id: Mapped[str] = _cuid_str_pk()
    lead_id: Mapped[str] = mapped_column("leadId", ForeignKey("Lead.id", ondelete="CASCADE"))
    calendar_event_id: Mapped[str | None] = mapped_column("calendarEventId", Text)
    hubspot_meeting_id: Mapped[str | None] = mapped_column("hubspotMeetingId", Text)
    starts_at: Mapped[dt.datetime] = mapped_column("startsAt")
    ends_at: Mapped[dt.datetime] = mapped_column("endsAt")
    attendees: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    source_call_id: Mapped[str | None] = mapped_column(
        "sourceCallId", ForeignKey("Call.id", ondelete="SET NULL"), unique=True
    )
    created_at: Mapped[dt.datetime] = _created_at_col()

    lead: Mapped["Lead"] = relationship(back_populates="meetings")
    source_call: Mapped["Call | None"] = relationship(back_populates="meeting")


class FollowUpTask(Base):
    __tablename__ = "FollowUpTask"

    id: Mapped[str] = _cuid_str_pk()
    lead_id: Mapped[str] = mapped_column("leadId", ForeignKey("Lead.id", ondelete="CASCADE"))
    hubspot_task_id: Mapped[str | None] = mapped_column("hubspotTaskId", Text)
    title: Mapped[str] = mapped_column(Text)
    due_at: Mapped[dt.datetime | None] = mapped_column("dueAt")
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = _created_at_col()

    lead: Mapped["Lead"] = relationship(back_populates="follow_up_tasks")


class Suppression(Base):
    """Hard block list, checked immediately before every send — not just at
    draft time. See Guardrails in documents/plan.md."""

    __tablename__ = "Suppression"

    id: Mapped[str] = _cuid_str_pk()
    email: Mapped[str] = mapped_column(Text, unique=True)
    lead_id: Mapped[str | None] = mapped_column(
        "leadId", ForeignKey("Lead.id", ondelete="SET NULL"), unique=True
    )
    reason: Mapped[str] = mapped_column(Text)  # "unsubscribed" | "bounced" | "manual" | "not_interested"
    created_at: Mapped[dt.datetime] = _created_at_col()

    lead: Mapped["Lead | None"] = relationship(back_populates="suppression")


class ActivityLog(Base):
    """Append-only feed of everything the agent(s) did — what makes the demo
    legible rather than a black box. No FKs on purpose: it should still
    record something even if the row it references gets deleted."""

    __tablename__ = "ActivityLog"

    id: Mapped[str] = _cuid_str_pk()
    workspace_id: Mapped[str | None] = mapped_column("workspaceId", Text)
    lead_id: Mapped[str | None] = mapped_column("leadId", Text)
    call_id: Mapped[str | None] = mapped_column("callId", Text)
    type: Mapped[str] = mapped_column(Text)  # e.g. "email.sent", "call.booked", "lead.replied"
    message: Mapped[str] = mapped_column(Text)
    log_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[dt.datetime] = _created_at_col()


# ─── Voice calls ─────────────────────────────────────────────────────────
# See "The voice call (hero feature)" in documents/plan.md for the session
# lifecycle these two tables track.


class Call(Base):
    __tablename__ = "Call"

    id: Mapped[str] = _cuid_str_pk()
    workspace_id: Mapped[str] = mapped_column("workspaceId", ForeignKey("Workspace.id", ondelete="CASCADE"))
    lead_id: Mapped[str | None] = mapped_column("leadId", ForeignKey("Lead.id", ondelete="SET NULL"))
    # Single-use token minted by POST /api/voice/session; this process
    # validates and consumes it before starting the Gemini Live session.
    token: Mapped[str] = mapped_column(Text, unique=True)
    token_consumed_at: Mapped[dt.datetime | None] = mapped_column("tokenConsumedAt")
    status: Mapped[str] = mapped_column(CallStatus, default="pending")
    outcome: Mapped[str | None] = mapped_column(CallOutcome)
    started_at: Mapped[dt.datetime | None] = mapped_column("startedAt")
    ended_at: Mapped[dt.datetime | None] = mapped_column("endedAt")
    duration_seconds: Mapped[int | None] = mapped_column("durationSeconds", Integer)
    qualification: Mapped[dict | None] = mapped_column(JSONB)
    sentiment: Mapped[str | None] = mapped_column(Text)
    consent_given: Mapped[bool] = mapped_column("consentGiven", Boolean, default=False)
    # Gemini Live session_resumption handle — lets a call that outlives one
    # Live session (see go_away handling in the plan) reconnect transparently.
    resumption_handle: Mapped[str | None] = mapped_column("resumptionHandle", Text)
    created_at: Mapped[dt.datetime] = _created_at_col()

    workspace: Mapped["Workspace"] = relationship(back_populates="calls")
    lead: Mapped["Lead | None"] = relationship(back_populates="calls")
    turns: Mapped[list["CallTurn"]] = relationship(back_populates="call")
    meeting: Mapped["Meeting | None"] = relationship(back_populates="source_call")


class CallTurn(Base):
    __tablename__ = "CallTurn"

    id: Mapped[str] = _cuid_str_pk()
    call_id: Mapped[str] = mapped_column("callId", ForeignKey("Call.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(CallTurnRole)
    text: Mapped[str] = mapped_column(Text)
    cited_chunk_ids: Mapped[list[str]] = mapped_column("citedChunkIds", ARRAY(String), default=list)
    tool_calls: Mapped[dict | list | None] = mapped_column("toolCalls", JSON)
    created_at: Mapped[dt.datetime] = _created_at_col()

    call: Mapped["Call"] = relationship(back_populates="turns")

import uuid
from datetime import datetime
from sqlalchemy import (
    String, Text, DateTime, Boolean, ForeignKey,
    Enum as SAEnum, JSON, Integer, Float, func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.core.database import Base


# ── Enums ──────────────────────────────────────────────────────────────────────

class TicketStatus(str, enum.Enum):
    open = "open"
    pending = "pending"       # waiting on user reply
    in_progress = "in_progress"
    resolved = "resolved"
    closed = "closed"


class TicketPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class TicketCategory(str, enum.Enum):
    refund_request = "refund_request"
    bug_report = "bug_report"
    billing = "billing"
    question = "question"
    feature_request = "feature_request"
    account = "account"
    other = "other"


class MessageDirection(str, enum.Enum):
    inbound = "inbound"    # from user → us
    outbound = "outbound"  # from us → user


class MessageSource(str, enum.Enum):
    outlook = "outlook"      # arrived/sent via Outlook natively
    platform = "platform"    # sent from our support platform


# ── Models ─────────────────────────────────────────────────────────────────────

class SupportAgent(Base):
    """Internal Studyflash team members who handle tickets."""
    __tablename__ = "support_agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    assigned_tickets: Mapped[list["Ticket"]] = relationship("Ticket", back_populates="assignee")

    def __repr__(self) -> str:
        return f"<SupportAgent {self.email}>"


class Ticket(Base):
    """
    A support ticket. One ticket = one email conversation.
    Linked to an Outlook thread via outlook_conversation_id.
    """
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Display ID (human-readable, e.g. SF-1042)
    ticket_number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)

    # Core fields
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[TicketStatus] = mapped_column(
        SAEnum(TicketStatus, name="ticket_status"), default=TicketStatus.open, index=True
    )
    priority: Mapped[TicketPriority] = mapped_column(
        SAEnum(TicketPriority, name="ticket_priority"), default=TicketPriority.medium
    )
    category: Mapped[TicketCategory | None] = mapped_column(
        SAEnum(TicketCategory, name="ticket_category"), nullable=True
    )

    # User who submitted the ticket (external)
    sender_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detected_language: Mapped[str | None] = mapped_column(String(10), nullable=True)  # e.g. "de", "fr"

    # Assignee (internal agent)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("support_agents.id"), nullable=True, index=True
    )

    # ── Outlook thread linkage ──────────────────────────────────────────────────
    # This is the critical field: the Graph API conversationId that keeps
    # our platform and Outlook in sync. All messages in this ticket share
    # the same conversationId so replies land in the correct Outlook thread.
    outlook_conversation_id: Mapped[str | None] = mapped_column(
        String(500), nullable=True, unique=True, index=True
    )
    # The internet Message-ID header (for MIME threading)
    outlook_internet_message_id: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Tags (free-form, stored as array in JSONB)
    tags: Mapped[list] = mapped_column(JSON, default=list)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    assignee: Mapped[SupportAgent | None] = relationship("SupportAgent", back_populates="assigned_tickets")
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="ticket", order_by="Message.created_at", cascade="all, delete-orphan"
    )
    enrichment: Mapped["TicketEnrichment | None"] = relationship(
        "TicketEnrichment", back_populates="ticket", uselist=False, cascade="all, delete-orphan"
    )
    ai_draft: Mapped["AIDraft | None"] = relationship(
        "AIDraft", back_populates="ticket", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def display_id(self) -> str:
        return f"SF-{self.ticket_number}"

    def __repr__(self) -> str:
        return f"<Ticket {self.display_id} [{self.status}]>"


class Message(Base):
    """
    A single email message within a ticket thread.
    Preserves the Outlook message ID so we never duplicate on re-sync.
    """
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Who sent it
    sender_email: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Email body - we store both HTML and plain text
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)

    direction: Mapped[MessageDirection] = mapped_column(
        SAEnum(MessageDirection, name="message_direction"), nullable=False, index=True
    )
    source: Mapped[MessageSource] = mapped_column(
        SAEnum(MessageSource, name="message_source"), nullable=False
    )

    # ── Outlook linkage ────────────────────────────────────────────────────────
    # The Graph API message ID — used to:
    # 1. Deduplicate (don't create duplicate messages if webhook fires twice)
    # 2. Reply in the correct thread (Graph API needs the parent message ID)
    outlook_message_id: Mapped[str | None] = mapped_column(
        String(500), nullable=True, unique=True, index=True
    )
    # Raw email headers (for debugging thread issues)
    raw_headers: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relationship
    ticket: Mapped[Ticket] = relationship("Ticket", back_populates="messages")

    def __repr__(self) -> str:
        return f"<Message {self.id} [{self.direction}] from {self.sender_email}>"


class TicketEnrichment(Base):
    """
    Enrichment data pulled from Sentry, PostHog, and the Studyflash Postgres DB.
    Stored as JSONB blobs — schema is intentionally flexible.
    Refreshed on demand or on ticket open.
    """
    __tablename__ = "ticket_enrichments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    # Data from the main Studyflash DB (plan, signup date, usage stats, etc.)
    sf_user_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Sentry: recent errors for this user
    sentry_events: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # PostHog: recent session recordings + key events
    posthog_recordings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    posthog_events: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Similar past tickets (resolved, for agent reference)
    similar_tickets: Mapped[list | None] = mapped_column(JSON, nullable=True)

    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationship
    ticket: Mapped[Ticket] = relationship("Ticket", back_populates="enrichment")


class AIDraft(Base):
    """
    AI-generated draft reply for a ticket.
    Agents can accept, edit, or regenerate.
    We log all drafts for quality tracking and future fine-tuning.
    """
    __tablename__ = "ai_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    draft_body: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0.0–1.0
    model_used: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Agent feedback
    was_accepted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # None = not yet acted on
    was_edited: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    ticket: Mapped[Ticket] = relationship("Ticket", back_populates="ai_draft")


class GraphSubscription(Base):
    """
    Tracks active Microsoft Graph API webhook subscriptions.
    Subscriptions expire every 3 days and must be renewed.
    """
    __tablename__ = "graph_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # The subscription ID returned by Graph API
    graph_subscription_id: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    resource: Mapped[str] = mapped_column(String(500), nullable=False)  # e.g. "users/support@.../messages"
    change_types: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "created"
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

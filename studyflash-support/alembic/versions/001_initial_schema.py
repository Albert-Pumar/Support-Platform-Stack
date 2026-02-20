"""initial schema

Revision ID: 001
Create Date: 2026-01-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enums
    op.execute("CREATE TYPE ticket_status AS ENUM ('open', 'pending', 'in_progress', 'resolved', 'closed')")
    op.execute("CREATE TYPE ticket_priority AS ENUM ('low', 'medium', 'high', 'urgent')")
    op.execute("CREATE TYPE ticket_category AS ENUM ('refund_request', 'bug_report', 'billing', 'question', 'feature_request', 'account', 'other')")
    op.execute("CREATE TYPE message_direction AS ENUM ('inbound', 'outbound')")
    op.execute("CREATE TYPE message_source AS ENUM ('outlook', 'platform')")

    # support_agents
    op.create_table("support_agents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_support_agents_email", "support_agents", ["email"])

    # tickets
    op.create_table("tickets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("ticket_number", sa.Integer, nullable=False, unique=True),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("status", sa.Enum("open","pending","in_progress","resolved","closed", name="ticket_status"), nullable=False, server_default="open"),
        sa.Column("priority", sa.Enum("low","medium","high","urgent", name="ticket_priority"), nullable=False, server_default="medium"),
        sa.Column("category", sa.Enum("refund_request","bug_report","billing","question","feature_request","account","other", name="ticket_category"), nullable=True),
        sa.Column("sender_email", sa.String(255), nullable=False),
        sa.Column("sender_name", sa.String(255), nullable=True),
        sa.Column("detected_language", sa.String(10), nullable=True),
        sa.Column("assignee_id", UUID(as_uuid=True), sa.ForeignKey("support_agents.id"), nullable=True),
        sa.Column("outlook_conversation_id", sa.String(500), nullable=True, unique=True),
        sa.Column("outlook_internet_message_id", sa.String(500), nullable=True),
        sa.Column("tags", JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tickets_status", "tickets", ["status"])
    op.create_index("ix_tickets_sender_email", "tickets", ["sender_email"])
    op.create_index("ix_tickets_outlook_conversation_id", "tickets", ["outlook_conversation_id"])
    op.create_index("ix_tickets_created_at", "tickets", ["created_at"])

    # messages
    op.create_table("messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("ticket_id", UUID(as_uuid=True), sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_email", sa.String(255), nullable=False),
        sa.Column("sender_name", sa.String(255), nullable=True),
        sa.Column("body_html", sa.Text, nullable=True),
        sa.Column("body_text", sa.Text, nullable=False),
        sa.Column("direction", sa.Enum("inbound","outbound", name="message_direction"), nullable=False),
        sa.Column("source", sa.Enum("outlook","platform", name="message_source"), nullable=False),
        sa.Column("outlook_message_id", sa.String(500), nullable=True, unique=True),
        sa.Column("raw_headers", JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_messages_ticket_id", "messages", ["ticket_id"])
    op.create_index("ix_messages_outlook_message_id", "messages", ["outlook_message_id"])

    # ticket_enrichments
    op.create_table("ticket_enrichments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("ticket_id", UUID(as_uuid=True), sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("sf_user_data", JSON, nullable=True),
        sa.Column("sentry_events", JSON, nullable=True),
        sa.Column("posthog_recordings", JSON, nullable=True),
        sa.Column("posthog_events", JSON, nullable=True),
        sa.Column("similar_tickets", JSON, nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ai_drafts
    op.create_table("ai_drafts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("ticket_id", UUID(as_uuid=True), sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("draft_body", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("model_used", sa.String(100), nullable=False),
        sa.Column("prompt_tokens", sa.Integer, nullable=True),
        sa.Column("completion_tokens", sa.Integer, nullable=True),
        sa.Column("was_accepted", sa.Boolean, nullable=True),
        sa.Column("was_edited", sa.Boolean, default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # graph_subscriptions
    op.create_table("graph_subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("graph_subscription_id", sa.String(500), nullable=False, unique=True),
        sa.Column("resource", sa.String(500), nullable=False),
        sa.Column("change_types", sa.String(100), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("graph_subscriptions")
    op.drop_table("ai_drafts")
    op.drop_table("ticket_enrichments")
    op.drop_table("messages")
    op.drop_table("tickets")
    op.drop_table("support_agents")
    op.execute("DROP TYPE IF EXISTS message_source")
    op.execute("DROP TYPE IF EXISTS message_direction")
    op.execute("DROP TYPE IF EXISTS ticket_category")
    op.execute("DROP TYPE IF EXISTS ticket_priority")
    op.execute("DROP TYPE IF EXISTS ticket_status")

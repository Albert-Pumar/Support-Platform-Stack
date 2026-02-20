"""
Microsoft Graph API Service
============================
Handles all communication with the Graph API:
  - OAuth2 token management (client credentials flow)
  - Webhook subscription lifecycle (create, renew, delete)
  - Reading emails from the shared mailbox
  - Sending replies that land in the correct Outlook thread

Graph API docs: https://learn.microsoft.com/en-us/graph/api/overview
"""

import hashlib
import hmac
import json
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL = f"https://login.microsoftonline.com/{settings.azure_tenant_id}/oauth2/v2.0/token"


# ── Token Management ───────────────────────────────────────────────────────────

class GraphTokenCache:
    """Simple in-process token cache. Refreshes before expiry."""
    _token: str | None = None
    _expires_at: datetime = datetime.min.replace(tzinfo=timezone.utc)

    @classmethod
    async def get_token(cls) -> str:
        now = datetime.now(timezone.utc)
        # Refresh 5 minutes before actual expiry
        if cls._token and cls._expires_at > now + timedelta(minutes=5):
            return cls._token

        log.info("graph.token.refreshing")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.azure_client_id,
                    "client_secret": settings.azure_client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

        cls._token = data["access_token"]
        cls._expires_at = now + timedelta(seconds=data["expires_in"])
        log.info("graph.token.refreshed", expires_in=data["expires_in"])
        return cls._token


async def _graph_headers() -> dict[str, str]:
    token = await GraphTokenCache.get_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


# ── Webhook Subscription ───────────────────────────────────────────────────────

async def create_webhook_subscription() -> dict[str, Any]:
    """
    Register a Graph API webhook subscription to receive notifications
    when new emails arrive in the shared mailbox.

    Subscriptions expire after 3 days max (Graph API limit for mail resources).
    We store them in the DB and renew via a Celery beat task.

    Returns the subscription object from Graph API.
    """
    # Subscription expires in 3 days (Graph API max for mail)
    expiry = datetime.now(timezone.utc) + timedelta(days=3)

    payload = {
        "changeType": "created",
        # Monitor the inbox of the shared support mailbox
        "resource": f"users/{settings.outlook_mailbox}/mailFolders/inbox/messages",
        "notificationUrl": settings.graph_webhook_url,
        "expirationDateTime": expiry.strftime("%Y-%m-%dT%H:%M:%S.0000000Z"),
        # clientState is sent back in every notification — we use it to verify authenticity
        "clientState": settings.graph_webhook_secret,
        "latestSupportedTlsVersion": "v1_3",
    }

    headers = await _graph_headers()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GRAPH_BASE}/subscriptions",
            headers=headers,
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

    log.info(
        "graph.subscription.created",
        subscription_id=data["id"],
        expires_at=data["expirationDateTime"],
    )
    return data


async def renew_webhook_subscription(subscription_id: str) -> dict[str, Any]:
    """Extend an existing subscription by another 3 days."""
    expiry = datetime.now(timezone.utc) + timedelta(days=3)
    payload = {"expirationDateTime": expiry.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")}

    headers = await _graph_headers()
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{GRAPH_BASE}/subscriptions/{subscription_id}",
            headers=headers,
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

    log.info("graph.subscription.renewed", subscription_id=subscription_id)
    return data


async def delete_webhook_subscription(subscription_id: str) -> None:
    """Delete a subscription (called on shutdown or re-registration)."""
    headers = await _graph_headers()
    async with httpx.AsyncClient() as client:
        await client.delete(
            f"{GRAPH_BASE}/subscriptions/{subscription_id}",
            headers=headers,
            timeout=10,
        )
    log.info("graph.subscription.deleted", subscription_id=subscription_id)


# ── Reading Email ──────────────────────────────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
async def fetch_message(message_id: str) -> dict[str, Any]:
    """
    Fetch a single email message by its Graph API message ID.
    Called when a webhook notification arrives — the notification only
    gives us the message ID, not the full content.

    We request specific fields to keep the payload lean.
    """
    fields = ",".join([
        "id",
        "conversationId",
        "subject",
        "bodyPreview",
        "body",
        "from",
        "toRecipients",
        "ccRecipients",
        "receivedDateTime",
        "internetMessageId",
        "internetMessageHeaders",
        "isRead",
        "hasAttachments",
    ])

    headers = await _graph_headers()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GRAPH_BASE}/users/{settings.outlook_mailbox}/messages/{message_id}",
            headers=headers,
            params={"$select": fields},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_conversation_messages(conversation_id: str) -> list[dict[str, Any]]:
    """
    Fetch all messages in a conversation thread.
    Used when we need to reconstruct a full thread (e.g. ticket was created
    after some back-and-forth had already happened in Outlook).
    """
    headers = await _graph_headers()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GRAPH_BASE}/users/{settings.outlook_mailbox}/messages",
            headers=headers,
            params={
                "$filter": f"conversationId eq '{conversation_id}'",
                "$orderby": "receivedDateTime asc",
                "$select": "id,conversationId,subject,body,from,receivedDateTime,internetMessageId",
                "$top": "50",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("value", [])


# ── Sending Reply ──────────────────────────────────────────────────────────────

async def send_reply(
    original_message_id: str,
    body_html: str,
    sender_name: str = "Studyflash Support",
) -> None:
    """
    Send a reply to an email using Graph API's /reply endpoint.

    This is the key to Outlook parity:
    - The reply goes into the SAME Outlook conversation thread
    - The user sees it as a normal email reply
    - Other Outlook users also see it in the shared mailbox Sent Items
    - Any further replies from Outlook will trigger our webhook

    Args:
        original_message_id: The Graph API ID of the message we're replying to.
                             We always reply to the latest message in the thread.
        body_html: HTML content of the reply.
        sender_name: Display name shown as the sender (the mailbox address is automatic).
    """
    payload = {
        "message": {
            "body": {
                "contentType": "html",
                "content": body_html,
            }
        },
        "comment": "",  # comment is ignored when message.body is set
    }

    headers = await _graph_headers()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GRAPH_BASE}/users/{settings.outlook_mailbox}/messages/{original_message_id}/reply",
            headers=headers,
            json=payload,
            timeout=20,
        )
        resp.raise_for_status()

    log.info("graph.reply.sent", original_message_id=original_message_id)


# ── Webhook Validation ─────────────────────────────────────────────────────────

def validate_webhook_notification(client_state: str) -> bool:
    """
    Verify that an incoming notification is from Graph API and not spoofed.
    Graph API sends back the clientState we set during subscription creation.
    """
    return hmac.compare_digest(client_state, settings.graph_webhook_secret)


# ── Email Parsing Helpers ──────────────────────────────────────────────────────

def parse_graph_message(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize a raw Graph API message into a clean dict our ingestion
    pipeline can work with.
    """
    sender = raw.get("from", {}).get("emailAddress", {})
    body = raw.get("body", {})

    return {
        "outlook_message_id": raw["id"],
        "outlook_conversation_id": raw.get("conversationId"),
        "internet_message_id": raw.get("internetMessageId"),
        "subject": raw.get("subject", "(no subject)"),
        "sender_email": sender.get("address", "").lower().strip(),
        "sender_name": sender.get("name"),
        "body_html": body.get("content") if body.get("contentType") == "html" else None,
        "body_text": _html_to_text(body.get("content", "")) if body.get("contentType") == "html"
                     else body.get("content", ""),
        "received_at": raw.get("receivedDateTime"),
        "has_attachments": raw.get("hasAttachments", False),
        "raw_headers": {
            h["name"]: h["value"]
            for h in raw.get("internetMessageHeaders", [])
        },
    }


def _html_to_text(html: str) -> str:
    """
    Very simple HTML → plain text conversion.
    In production consider using html2text or bleach.
    """
    import re
    # Remove style and script blocks
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Convert <br> and <p> to newlines
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"</p>", "\n\n", html, flags=re.IGNORECASE)
    # Strip remaining tags
    html = re.sub(r"<[^>]+>", "", html)
    # Decode common HTML entities
    html = html.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
    # Collapse whitespace
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()

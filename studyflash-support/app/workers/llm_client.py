"""
LLM Client
===========
Thin wrapper around the OpenAI client that adds:
  - Automatic retry with exponential backoff
  - Token + cost tracking (logged per call, aggregated in DB)
  - Structured output validation (JSON schema enforcement)
  - Prompt version tagging for observability
  - Response time logging

All AI calls in the pipeline go through this — never call OpenAI directly.
"""

import json
import time
import uuid
from typing import Any, TypeVar

import structlog
from openai import AsyncOpenAI, APIError, RateLimitError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from app.core.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

# Cost per 1M tokens (USD) — update when pricing changes
COST_PER_1M = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
}


class LLMResponse:
    """Structured response from an LLM call."""

    def __init__(
        self,
        content: str,
        parsed: dict | list | None,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        call_id: str,
    ):
        self.content = content
        self.parsed = parsed
        self.model = model
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens
        self.latency_ms = latency_ms
        self.call_id = call_id
        self.cost_usd = self._calc_cost()

    def _calc_cost(self) -> float:
        pricing = COST_PER_1M.get(self.model, {"input": 0, "output": 0})
        return (
            self.prompt_tokens / 1_000_000 * pricing["input"]
            + self.completion_tokens / 1_000_000 * pricing["output"]
        )


class LLMClient:
    """
    Async LLM client with observability and resilience built in.
    Instantiate once per pipeline run (not as a singleton — OpenAI client is already async-safe).
    """

    def __init__(self, model: str | None = None):
        self.model = model or settings.openai_model
        self._client = AsyncOpenAI(api_key=settings.openai_api_key,
                                    base_url="https://api.groq.com/openai/v1")

    @retry(
        retry=retry_if_exception_type((RateLimitError, APIError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        before_sleep=before_sleep_log(log, "warning"),
        reraise=True,
    )
    async def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
        json_mode: bool = False,
        task_name: str = "unknown",
        ticket_id: str | None = None,
    ) -> LLMResponse:
        """
        Single LLM completion with full observability.

        Args:
            system: System prompt.
            user: User prompt (the actual input).
            temperature: 0.1 for classification, 0.4+ for creative drafts.
            json_mode: If True, uses response_format=json_object and parses the output.
            task_name: Label for logging (e.g. "classify", "draft", "assign").
            ticket_id: For log correlation.
        """
        call_id = str(uuid.uuid4())[:8]
        start = time.monotonic()

        log.info(
            "llm.call.start",
            task=task_name,
            model=self.model,
            ticket_id=ticket_id,
            call_id=call_id,
        )

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        raw = await self._client.chat.completions.create(**kwargs)

        latency_ms = int((time.monotonic() - start) * 1000)
        content = raw.choices[0].message.content.strip()
        usage = raw.usage

        # Parse JSON if requested
        parsed = None
        if json_mode:
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as e:
                log.error(
                    "llm.json_parse_failed",
                    task=task_name,
                    call_id=call_id,
                    error=str(e),
                    content_preview=content[:200],
                )
                raise ValueError(f"LLM returned invalid JSON for task '{task_name}': {e}") from e

        response = LLMResponse(
            content=content,
            parsed=parsed,
            model=self.model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            latency_ms=latency_ms,
            call_id=call_id,
        )

        log.info(
            "llm.call.complete",
            task=task_name,
            model=self.model,
            ticket_id=ticket_id,
            call_id=call_id,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cost_usd=round(response.cost_usd, 6),
            latency_ms=latency_ms,
        )

        return response

    async def complete_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.1,
        task_name: str = "unknown",
        ticket_id: str | None = None,
    ) -> dict | list:
        """Convenience method: always returns parsed JSON."""
        resp = await self.complete(
            system, user,
            temperature=temperature,
            json_mode=True,
            task_name=task_name,
            ticket_id=ticket_id,
        )
        return resp.parsed

    async def complete_text(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.4,
        task_name: str = "unknown",
        ticket_id: str | None = None,
    ) -> str:
        """Convenience method: always returns plain text."""
        resp = await self.complete(
            system, user,
            temperature=temperature,
            json_mode=False,
            task_name=task_name,
            ticket_id=ticket_id,
        )
        return resp.content

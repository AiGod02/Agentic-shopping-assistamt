"""
LLM Router — abstraction layer for invoking LLMs with function calling.

Supports OpenAI, Gemini, and Groq with unified interface.
Groq uses the OpenAI-compatible API with a custom base_url.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from agent_server.config import settings
from shared.middleware.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from shared.observability.logging import get_logger

logger = get_logger(__name__)


@dataclass
class LLMMessage:
    role: str  # system, user, assistant, tool
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class ToolCall:
    """Parsed tool call from LLM response."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Unified LLM response."""
    content: str | None
    tool_calls: list[ToolCall]
    finish_reason: str  # stop, tool_calls
    usage: dict[str, int]  # prompt_tokens, completion_tokens, total_tokens


class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.1,
    ) -> LLMResponse:
        ...


class OpenAICompatibleProvider(LLMProvider):
    """Provider for any OpenAI-compatible API (OpenAI, Groq, Together, etc).

    Works with any service that implements the OpenAI chat completions API.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
        provider_name: str = "openai",
    ) -> None:
        import openai
        key = (api_key or "").strip(" \t\r\n'\"")
        client_kwargs: dict[str, Any] = {"api_key": key or "missing-key"}
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = openai.AsyncOpenAI(**client_kwargs)
        self.model = model
        self._breaker = CircuitBreaker(
            provider_name, CircuitBreakerConfig(failure_threshold=5, timeout_seconds=60)
        )

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.1,
    ) -> LLMResponse:
        formatted = []
        for m in messages:
            msg: dict[str, Any] = {"role": m.role}
            if m.content is not None:
                msg["content"] = m.content
            if m.tool_calls:
                msg["tool_calls"] = m.tool_calls
            if m.tool_call_id:
                msg["tool_call_id"] = m.tool_call_id
            if m.name:
                msg["name"] = m.name
            formatted.append(msg)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": formatted,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        @self._breaker.protect
        async def _call():
            return await self.client.chat.completions.create(**kwargs)

        response = await _call()
        choice = response.choices[0]

        parsed_calls = []
        if choice.message.tool_calls:
            import json
            for tc in choice.message.tool_calls:
                parsed_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                ))

        return LLMResponse(
            content=choice.message.content,
            tool_calls=parsed_calls,
            finish_reason=choice.finish_reason or "stop",
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            },
        )


class GeminiProvider(LLMProvider):
    """Google Gemini provider with function calling support."""

    def __init__(self) -> None:
        import google.generativeai as genai
        genai.configure(api_key=settings.gemini_api_key)
        self.model_name = settings.gemini_model
        self._genai = genai
        self._breaker = CircuitBreaker("gemini", CircuitBreakerConfig(failure_threshold=5, timeout_seconds=60))

    async def complete(
        self,
        messages: list[LLMMessage],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.1,
    ) -> LLMResponse:
        import asyncio
        import json

        contents = []
        system_instruction = None
        for m in messages:
            if m.role == "system":
                system_instruction = m.content
                continue
            role = "model" if m.role == "assistant" else "user"
            if m.content:
                contents.append({"role": role, "parts": [{"text": m.content}]})

        generation_config = {"temperature": temperature}

        model_kwargs: dict[str, Any] = {
            "model_name": self.model_name,
            "generation_config": generation_config,
        }
        if system_instruction:
            model_kwargs["system_instruction"] = system_instruction

        if tools:
            from google.generativeai.types import FunctionDeclaration, Tool
            func_declarations = []
            for tool_def in tools:
                func_declarations.append(FunctionDeclaration(**tool_def))
            model_kwargs["tools"] = [Tool(function_declarations=func_declarations)]

        model = self._genai.GenerativeModel(**model_kwargs)

        @self._breaker.protect
        async def _call():
            return await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: model.generate_content(contents),
            )

        response = await _call()

        parsed_calls = []
        content = None

        if response.candidates:
            candidate = response.candidates[0]
            for part in candidate.content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    parsed_calls.append(ToolCall(
                        id=f"gemini-{fc.name}-{id(fc)}",
                        name=fc.name,
                        arguments=dict(fc.args) if fc.args else {},
                    ))
                elif hasattr(part, "text") and part.text:
                    content = part.text

        finish_reason = "tool_calls" if parsed_calls else "stop"

        return LLMResponse(
            content=content,
            tool_calls=parsed_calls,
            finish_reason=finish_reason,
            usage={
                "prompt_tokens": response.usage_metadata.prompt_token_count if hasattr(response, "usage_metadata") and response.usage_metadata else 0,
                "completion_tokens": response.usage_metadata.candidates_token_count if hasattr(response, "usage_metadata") and response.usage_metadata else 0,
                "total_tokens": response.usage_metadata.total_token_count if hasattr(response, "usage_metadata") and response.usage_metadata else 0,
            },
        )


class LLMRouter:
    """Routes LLM requests to the configured provider.

    Supported providers:
    - "groq"   → Groq Cloud (Llama 3.3 70B, Mixtral, etc.) — free tier available
    - "openai" → OpenAI (GPT-4o, etc.)
    - "gemini" → Google Gemini
    """

    def __init__(self, provider: str | None = None) -> None:
        self.provider_name = provider or settings.default_llm_provider
        self._provider: LLMProvider | None = None

    @property
    def provider(self) -> LLMProvider:
        if self._provider is None:
            if self.provider_name == "groq":
                self._provider = OpenAICompatibleProvider(
                    api_key=settings.groq_api_key,
                    model=settings.groq_model,
                    base_url="https://api.groq.com/openai/v1",
                    provider_name="groq",
                )
            elif self.provider_name == "openai":
                self._provider = OpenAICompatibleProvider(
                    api_key=settings.openai_api_key,
                    model=settings.openai_model,
                    provider_name="openai",
                )
            elif self.provider_name == "gemini":
                self._provider = GeminiProvider()
            else:
                raise ValueError(f"Unsupported LLM provider: {self.provider_name}")
        return self._provider

    async def complete(
        self, messages: list[LLMMessage], tools: list[dict[str, Any]] | None = None, temperature: float = 0.1
    ) -> LLMResponse:
        logger.info("llm_request", provider=self.provider_name, messages=len(messages), has_tools=bool(tools))
        response = await self.provider.complete(messages, tools, temperature)
        logger.info(
            "llm_response",
            provider=self.provider_name,
            finish_reason=response.finish_reason,
            tool_calls=len(response.tool_calls),
            tokens=response.usage.get("total_tokens", 0),
        )
        return response

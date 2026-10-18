"""
Tool Registry — dynamic registration and discovery of commerce tools.

Each tool has a JSON Schema definition for structured function calling.
The registry supports LLM-agnostic tool definitions that can be serialized
for OpenAI, Gemini, or any other function-calling model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

from shared.observability.logging import get_logger

logger = get_logger(__name__)


class ToolCategory(str, Enum):
    SEARCH = "search"
    CART = "cart"
    ORDER = "order"
    BOOKING = "booking"
    PAYMENT = "payment"
    ACCOUNT = "account"
    SUPPORT = "support"


@dataclass
class ToolParameter:
    """A single parameter of a tool."""
    name: str
    type: str  # string, integer, number, boolean, array, object
    description: str
    required: bool = True
    enum: list[str] | None = None
    default: Any = None


@dataclass
class ToolDefinition:
    """Complete tool definition — name, description, parameters, handler."""
    name: str
    description: str
    category: ToolCategory
    parameters: list[ToolParameter] = field(default_factory=list)
    handler: Callable[..., Coroutine[Any, Any, Any]] | None = None
    requires_confirmation: bool = False
    idempotent: bool = True

    def to_openai_schema(self) -> dict[str, Any]:
        """Convert to OpenAI function calling schema."""
        properties = {}
        required = []
        for p in self.parameters:
            p_type = [p.type, "null"] if not p.required else p.type
            prop: dict[str, Any] = {"type": p_type, "description": p.description}
            if p.type == "array":
                prop["items"] = {"type": "string"}
            if p.enum:
                prop["enum"] = p.enum
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def to_gemini_schema(self) -> dict[str, Any]:
        """Convert to Gemini function declaration."""
        type_mapping = {
            "string": "STRING",
            "integer": "INTEGER",
            "number": "NUMBER",
            "boolean": "BOOLEAN",
            "array": "ARRAY",
            "object": "OBJECT",
        }
        properties = {}
        required = []
        for p in self.parameters:
            properties[p.name] = {
                "type": type_mapping.get(p.type, "STRING"),
                "description": p.description,
            }
            if p.enum:
                properties[p.name]["enum"] = p.enum
            if p.required:
                required.append(p.name)

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "OBJECT",
                "properties": properties,
                "required": required,
            },
        }


class ToolRegistry:
    """Singleton registry for all available commerce tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        logger.info("tool_registered", name=tool.name, category=tool.category.value)

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list_tools(self, category: ToolCategory | None = None) -> list[ToolDefinition]:
        if category:
            return [t for t in self._tools.values() if t.category == category]
        return list(self._tools.values())

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Get all tools as OpenAI function calling schemas."""
        return [t.to_openai_schema() for t in self._tools.values()]

    def to_gemini_tools(self) -> list[dict[str, Any]]:
        """Get all tools as Gemini function declarations."""
        return [t.to_gemini_schema() for t in self._tools.values()]


# Global registry
tool_registry = ToolRegistry()

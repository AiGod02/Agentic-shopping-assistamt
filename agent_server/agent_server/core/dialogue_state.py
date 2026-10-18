"""
Dialogue State Object — persistent state tracking per session for ACP Conversational Commerce.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


from enum import Enum


class FunnelStage(str, Enum):
    GREETING = "greeting"
    DISCOVERY = "discovery"        # gathering needs/preferences
    BROWSING = "browsing"          # viewing options, not yet narrowed
    EVALUATING = "evaluating"      # comparing specific items, asking details
    OBJECTION = "objection"        # hesitating on price/fit/trust
    READY_TO_BUY = "ready_to_buy"  # decided, needs a nudge to close
    POST_PURCHASE = "post_purchase" # order placed, tracking/support


@dataclass
class DialogueState:
    session_id: str = ""
    merchant_id: str = ""
    last_shown_listings: list[dict[str, Any]] = field(default_factory=list)  # [{id, title, price, rating, ...}]
    focused_listing_id: str | None = None
    focused_listing_data: dict[str, Any] | None = None
    last_search_query: str | None = None
    last_search_filters: dict[str, Any] | None = None
    cart_id: str | None = None
    turn_history: list[dict[str, Any]] = field(default_factory=list)  # [{role, intent, entities, text}]
    pending_clarification: dict[str, Any] | None = None  # {question_type: str, context: dict}
    user_preferences: dict[str, Any] = field(default_factory=dict)  # persisted preferences (e.g. color, budget)
    
    # Funnel Stage & Escalation Tracking fields
    stage: FunnelStage = FunnelStage.GREETING
    stage_confidence: float = 1.0
    known_preferences: dict[str, Any] = field(default_factory=dict)
    objections_raised: list[str] = field(default_factory=list)
    upsell_attempted: bool = False
    consecutive_unclear_turns: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["stage"] = self.stage.value if isinstance(self.stage, FunnelStage) else self.stage
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DialogueState:
        if not data:
            return cls()
        raw_stage = data.get("stage", FunnelStage.GREETING)
        try:
            stage_enum = FunnelStage(raw_stage)
        except ValueError:
            stage_enum = FunnelStage.GREETING

        return cls(
            session_id=data.get("session_id", ""),
            merchant_id=data.get("merchant_id", ""),
            last_shown_listings=data.get("last_shown_listings", []),
            focused_listing_id=data.get("focused_listing_id"),
            focused_listing_data=data.get("focused_listing_data"),
            last_search_query=data.get("last_search_query"),
            last_search_filters=data.get("last_search_filters"),
            cart_id=data.get("cart_id"),
            turn_history=data.get("turn_history", []),
            pending_clarification=data.get("pending_clarification"),
            user_preferences=data.get("user_preferences", {}),
            stage=stage_enum,
            stage_confidence=data.get("stage_confidence", 1.0),
            known_preferences=data.get("known_preferences", {}),
            objections_raised=data.get("objections_raised", []),
            upsell_attempted=data.get("upsell_attempted", False),
            consecutive_unclear_turns=data.get("consecutive_unclear_turns", 0),
        )

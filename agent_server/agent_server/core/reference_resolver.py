"""
Reference Resolution Layer — evaluates implicit references, ordinals, pronouns, and comparative re-rankings against DialogueState.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent_server.core.dialogue_state import DialogueState
from shared.observability.logging import get_logger

logger = get_logger(__name__)

POSITIONAL_MAP: dict[str, int] = {
    "first": 0, "1st": 0, "one": 0,
    "second": 1, "2nd": 1, "two": 1,
    "third": 2, "3rd": 2, "three": 2,
    "fourth": 3, "4th": 3, "four": 3,
    "fifth": 4, "5th": 4, "five": 4,
    "last": -1,
}

PRONOUN_RE = re.compile(r"\b(?:this|that|it|the\s+item|the\s+product|the\s+listing|this\s+one|that\s+one)\b", re.I)
ORDINAL_RE = re.compile(
    r"\b(?:the\s+)?(" + "|".join(re.escape(k) for k in POSITIONAL_MAP) + r")\s*(?:one|item|product|listing|result|option)?\b",
    re.I,
)
DIGIT_ORDINAL_RE = re.compile(r"\b(\d+)(?:st|nd|rd|th)?\s*(?:one|item|product|listing|result|option)?\b", re.I)

COMPARATIVE_RE = re.compile(
    r"\b(?:cheaper|cheapest|less\s+expensive|lower\s+price|best\s+rated|highest\s+rated|better\s+reviews|top\s+rated|most\s+popular)\b",
    re.I,
)

SHOW_MORE_RE = re.compile(
    r"\b(?:show\s+other\s+options|other\s+options|show\s+more|something\s+else|what\s+else|anything\s+similar|more\s+products|other\s+products)\b",
    re.I,
)

OVERRIDE_RE = re.compile(
    r"\b(?:instead|never\s+mind|actually|rather|search\s+for|find\s+me|show\s+me\s+something)\b",
    re.I,
)


@dataclass
class ResolvedReference:
    intent: str | None = None
    target_listing_id: str | None = None
    target_listing_ids: list[str] | None = None
    search_query: str | None = None
    filters: dict[str, Any] | None = None
    is_override: bool = False
    requires_clarification: bool = False
    clarification_question: str | None = None
    reason: str = ""
    confidence: float = 0.0


class ReferenceResolver:
    """Resolves implicit user references against the persistent DialogueState."""

    def resolve(self, user_message: str, state: DialogueState) -> ResolvedReference:
        msg = user_message.strip()

        # 1. Check for explicit override phrases ("instead", "never mind", "show me blue shoes instead")
        has_override = bool(OVERRIDE_RE.search(msg))
        if has_override and not ("compare" in msg.lower() or "cheaper" in msg.lower()):
            logger.info("reference_resolution_explicit_override", query=msg)
            return ResolvedReference(is_override=True, reason="Explicit override detected")

        # 2. Check for multi-item comparison ("compare the first two", "compare 1 and 2")
        if "compare" in msg.lower():
            ids = self._extract_multiple_ordinals(msg, state.last_shown_listings)
            if len(ids) >= 2:
                return ResolvedReference(
                    intent="compare_products",
                    target_listing_ids=ids,
                    reason=f"Resolved comparison set of {len(ids)} items from ordinals",
                )
            elif len(state.last_shown_listings) >= 2:
                # Default to first 2 items
                ids = [p["id"] for p in state.last_shown_listings[:2]]
                return ResolvedReference(
                    intent="compare_products",
                    target_listing_ids=ids,
                    reason="Resolved top 2 items for comparison",
                )

        # 3. Check for comparative/superlative selection ("add the cheaper one", "the highest rated")
        if COMPARATIVE_RE.search(msg):
            candidates = state.last_shown_listings
            if not candidates and state.focused_listing_data:
                candidates = [state.focused_listing_data]
            if candidates:
                if re.search(r"\b(?:cheaper|cheapest|less\s+expensive|lower\s+price)\b", msg, re.I):
                    sorted_cand = sorted(candidates, key=lambda x: float(x.get("base_price", x.get("price", 0))))
                    best = sorted_cand[0]
                    return ResolvedReference(
                        target_listing_id=best["id"],
                        reason=f"Resolved cheaper item: {best.get('title', best.get('name'))} (${best.get('price', best.get('base_price'))})",
                    )
                elif re.search(r"\b(?:best\s+rated|highest\s+rated|better\s+reviews|top\s+rated)\b", msg, re.I):
                    sorted_cand = sorted(candidates, key=lambda x: float(x.get("rating_avg", x.get("rating", 0))), reverse=True)
                    best = sorted_cand[0]
                    return ResolvedReference(
                        target_listing_id=best["id"],
                        reason=f"Resolved top rated item: {best.get('title', best.get('name'))}",
                    )

        # 4. Check for ordinals ("the second one", "3rd option")
        ordinal_id = self._extract_single_ordinal(msg, state.last_shown_listings)
        if ordinal_id:
            return ResolvedReference(
                target_listing_id=ordinal_id,
                reason="Resolved via ordinal positional index into last_shown_listings",
            )

        # 5. Check for pronouns ("it", "this", "that one")
        if PRONOUN_RE.search(msg):
            target_id = state.focused_listing_id or (state.last_shown_listings[0]["id"] if state.last_shown_listings else None)
            if target_id:
                return ResolvedReference(
                    target_listing_id=target_id,
                    reason="Resolved pronoun against focused_listing_id or top active listing",
                )

        # 6. Check for implicit continuation / pagination ("show other options", "what else do you have")
        if SHOW_MORE_RE.search(msg):
            return ResolvedReference(
                intent="show_more_results",
                search_query=state.last_search_query,
                filters=state.last_search_filters,
                reason="Resolved to show_more_results using prior search query and excluding last_shown_listings",
            )

        # No explicit reference detected — let the LLM resolve from conversational context
        return ResolvedReference(reason="No explicit reference detected")

    def _extract_single_ordinal(self, text: str, listings: list[dict[str, Any]]) -> str | None:
        if not listings:
            return None
        match = ORDINAL_RE.search(text)
        if match:
            word = match.group(1).lower().strip()
            idx = POSITIONAL_MAP.get(word)
            if idx is not None:
                if idx == -1:
                    idx = len(listings) - 1
                if 0 <= idx < len(listings):
                    return listings[idx]["id"]

        digit_match = DIGIT_ORDINAL_RE.search(text)
        if digit_match:
            idx = int(digit_match.group(1)) - 1
            if 0 <= idx < len(listings):
                return listings[idx]["id"]

        return None

    def _extract_multiple_ordinals(self, text: str, listings: list[dict[str, Any]]) -> list[str]:
        if not listings:
            return []
        ids = []
        # Check digit matches like "1 and 2", "first and second"
        for m in DIGIT_ORDINAL_RE.finditer(text):
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(listings):
                ids.append(listings[idx]["id"])

        if not ids:
            for word, idx in POSITIONAL_MAP.items():
                if re.search(r"\b" + re.escape(word) + r"\b", text, re.I):
                    pos_idx = idx if idx >= 0 else len(listings) - 1
                    if 0 <= pos_idx < len(listings) and listings[pos_idx]["id"] not in ids:
                        ids.append(listings[pos_idx]["id"])
        return ids

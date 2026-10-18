"""
Expanded Intent Classifier & Taxonomy for ACP Conversational Commerce.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from agent_server.core.llm_router import LLMMessage, LLMRouter
from agent_server.core.nlu import QueryExtractor
from shared.observability.logging import get_logger
from shared.observability.request_context import trace_log

logger = get_logger(__name__)

# Full Expanded Intent Taxonomy per Part 3
VALID_INTENTS = {
    # Discovery
    "SEARCH_PRODUCTS", "BROWSE_CATEGORY", "FILTER_REFINE", "SHOW_MORE_RESULTS", "SHOW_SIMILAR_ITEMS",
    # Product Detail
    "GET_PRODUCT_DETAILS", "GET_REVIEWS", "CHECK_AVAILABILITY", "GET_PRICE", "COMPARE_PRODUCTS",
    # Preference & Clarification
    "STATE_PREFERENCE", "ANSWER_CLARIFICATION", "REJECT_OPTION",
    # Cart & Checkout
    "ADD_TO_CART", "REMOVE_FROM_CART", "VIEW_CART", "MODIFY_CART_QUANTITY", "CHECKOUT", "APPLY_PROMO",
    # Orders
    "TRACK_ORDER", "ORDER_HISTORY", "CANCEL_ORDER", "REQUEST_RETURN_REFUND",
    # Merchant / Meta
    "MERCHANT_INFO", "ESCALATE_TO_HUMAN",
    # Conversational
    "GREETING", "CHITCHAT_OUT_OF_SCOPE", "UNCLEAR_INTENT",
}

CLASSIFIER_SYSTEM = """You are a commerce intent classifier AND query rewriter.
Given a user message and dialogue context, respond ONLY with a single JSON object — no explanation, no markdown, no extra text.

JSON schema:
{
  "intent": "<one of: SEARCH_PRODUCTS | BROWSE_CATEGORY | FILTER_REFINE | SHOW_MORE_RESULTS | SHOW_SIMILAR_ITEMS | GET_PRODUCT_DETAILS | GET_REVIEWS | CHECK_AVAILABILITY | GET_PRICE | COMPARE_PRODUCTS | STATE_PREFERENCE | ANSWER_CLARIFICATION | REJECT_OPTION | ADD_TO_CART | REMOVE_FROM_CART | VIEW_CART | MODIFY_CART_QUANTITY | CHECKOUT | APPLY_PROMO | TRACK_ORDER | ORDER_HISTORY | CANCEL_ORDER | REQUEST_RETURN_REFUND | MERCHANT_INFO | ESCALATE_TO_HUMAN | GREETING | CHITCHAT_OUT_OF_SCOPE | UNCLEAR_INTENT>",
  "product_keyword": "<extracted product name/category, null if not applicable>",
  "search_query": "<clean search-engine keyword(s), null if not a search intent>",
  "listing_id": "<UUID matching product, null if not applicable>",
  "resolved_listing_ids": ["<list of UUIDs for comparisons/multi-selects>"],
  "filters": {"price_max": null, "price_min": null, "color": null, "category": null},
  "disambiguation_needed": <true if message is genuinely ambiguous and context cannot resolve it, false otherwise>,
  "confidence": "<high | medium | low>"
}

CRITICAL TAXONOMY RULES:
- SEARCH_PRODUCTS: user searching for products ("shoes under $100", "find laptops")
- SHOW_MORE_RESULTS: user asking for other/more products ("show other options", "what else do you have")
- COMPARE_PRODUCTS: user comparing items ("compare the first two")
- GET_REVIEWS: user asking for reviews/opinions ("what do people say about it?")
- GET_PRODUCT_DETAILS: user asking specs/details ("tell me about the second one")
- ADD_TO_CART: user adding item to cart ("add the cheaper one to cart", "buy this")
- STATE_PREFERENCE: user expressing a preference ("I prefer battery life over gaming")
- UNCLEAR_INTENT: message cannot be understood even with context
"""


@dataclass
class IntentResult:
    intent: str
    product_keyword: str | None = None
    listing_id: str | None = None
    resolved_listing_id: str | None = None
    resolved_listing_ids: list[str] = field(default_factory=list)
    search_query: str | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    disambiguation_needed: bool = False
    clarification_question: str | None = None
    confidence: str = "low"
    nlu_tier: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict)


def _extract_json(text: str) -> dict[str, Any]:
    start = text.find("{")
    if start == -1:
        return {}
    depth = 0
    for i, c in enumerate(text[start:], start):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


class IntentClassifier:
    """Classifier utilizing the expanded taxonomy."""

    def __init__(self, llm: LLMRouter) -> None:
        self.llm = llm
        self._fallback = QueryExtractor()

    async def classify(
        self,
        user_message: str,
        dialogue_state: Any | None = None,
        last_seen_listings: list[dict[str, Any]] | None = None,
        conversation_tail: list[dict[str, Any]] | None = None,
    ) -> IntentResult:
        try:
            result = await self._classify_with_llm(
                user_message, dialogue_state, last_seen_listings, conversation_tail
            )
            if result is not None:
                return result
        except Exception as e:
            trace_log("intent_classifier.llm_failed_using_rules", error=str(e))
            logger.warning("intent_classifier_llm_failed", error=str(e))

        trace_log("intent_classifier.rule_based_fallback")
        return self._classify_with_rules(user_message, last_seen_listings)

    async def _classify_with_llm(
        self,
        user_message: str,
        dialogue_state: Any | None = None,
        last_seen_listings: list[dict[str, Any]] | None = None,
        conversation_tail: list[dict[str, Any]] | None = None,
    ) -> IntentResult | None:
        parts: list[str] = []

        if last_seen_listings:
            listing_lines = "\n".join(
                f"  - id={item['id']} | {item.get('title', item.get('name'))} | ${item.get('price', item.get('base_price'))}"
                for item in last_seen_listings
            )
            parts.append(f"Active listings in context:\n{listing_lines}")

        if conversation_tail:
            recent = "\n".join(
                f"{m.get('role', 'user').upper()}: {m.get('content', '')}"
                for m in conversation_tail[-3:]
            )
            parts.append(f"Recent conversation:\n{recent}")

        parts.append(f"User message: {user_message}")
        classify_prompt = "\n\n".join(parts)

        import time as _time
        _t0 = _time.perf_counter()
        trace_log("intent_classifier.llm_call_start",
                  listings_in_ctx=len(last_seen_listings) if last_seen_listings else 0,
                  history_turns=len(conversation_tail) if conversation_tail else 0)

        response = await self.llm.complete(
            messages=[
                LLMMessage(role="system", content=CLASSIFIER_SYSTEM),
                LLMMessage(role="user", content=classify_prompt),
            ],
            tools=None,
            temperature=0.1,
        )

        _llm_ms = (_time.perf_counter() - _t0) * 1000
        data = _extract_json(response.content or "")
        if not data:
            trace_log("intent_classifier.llm_bad_json", llm_ms=f"{_llm_ms:.0f}ms", raw=str(response.content)[:100])
            return None

        intent = str(data.get("intent", "UNCLEAR_INTENT")).upper().strip()
        if intent not in VALID_INTENTS:
            intent = "UNCLEAR_INTENT"

        trace_log("intent_classifier.llm_call_done",
                  llm_ms=f"{_llm_ms:.0f}ms",
                  intent=intent,
                  confidence=data.get("confidence"),
                  keyword=data.get("product_keyword"))
        return IntentResult(
            intent=intent,
            product_keyword=data.get("product_keyword") or None,
            listing_id=data.get("listing_id") or None,
            resolved_listing_id=data.get("listing_id") or None,
            resolved_listing_ids=data.get("resolved_listing_ids") or [],
            search_query=data.get("search_query") or None,
            filters=data.get("filters") or {},
            disambiguation_needed=bool(data.get("disambiguation_needed", False)),
            confidence=data.get("confidence", "high"),
            nlu_tier="llm",
            raw=data,
        )

    def _classify_with_rules(
        self,
        user_message: str,
        last_seen_listings: list[dict[str, Any]] | None = None,
    ) -> IntentResult:
        data = self._fallback.detect_intent_fallback(user_message, last_seen_listings)
        
        mapping = {
            "SEARCH": "SEARCH_PRODUCTS",
            "REVIEW": "GET_REVIEWS",
            "DETAIL": "GET_PRODUCT_DETAILS",
            "CART_ADD": "ADD_TO_CART",
            "CART_VIEW": "VIEW_CART",
            "CHECKOUT": "CHECKOUT",
            "ORDER": "TRACK_ORDER",
            "CANCEL_ORDER": "CANCEL_ORDER",
            "CHECK_AVAILABILITY": "CHECK_AVAILABILITY",
            "COMPARE": "COMPARE_PRODUCTS",
            "CHITCHAT": "GREETING",
        }
        intent = mapping.get(data.get("intent", ""), "UNCLEAR_INTENT")

        return IntentResult(
            intent=intent,
            product_keyword=data.get("product_keyword"),
            listing_id=data.get("listing_id"),
            resolved_listing_id=data.get("resolved_listing_id"),
            resolved_listing_ids=data.get("resolved_listing_ids", []),
            search_query=data.get("search_query"),
            confidence="medium",
            nlu_tier="rule_based",
            raw=data,
        )


INTENT_DIRECTIVES: dict[str, str] = {
    "SEARCH_PRODUCTS": "Call search_listings with the clean search_query.",
    "SHOW_MORE_RESULTS": "Call search_listings excluding previous last_shown_listings.",
    "COMPARE_PRODUCTS": "Call compare_products or get_listing_details for each target listing ID and construct a comparative summary.",
    "GET_REVIEWS": "Call get_listing_reviews(listing_id=...).",
    "GET_PRODUCT_DETAILS": "Call get_listing_details(listing_id=...).",
    "CHECK_AVAILABILITY": "Call check_availability(listing_id=...).",
    "ADD_TO_CART": "Call add_to_cart(listing_id=...).",
    "VIEW_CART": "Call view_cart().",
    "CHECKOUT": "Call checkout().",
    "TRACK_ORDER": "Call list_orders() or get_order_status(order_id=...).",
    "CANCEL_ORDER": "Call cancel_order(order_id=...).",
    "GREETING": "Respond politely to the user greeting.",
    "UNCLEAR_INTENT": "Ask a polite clarifying question.",
}


def build_intent_directive(result: IntentResult) -> str:
    lines = [
        f"[INTENT PRE-CLASSIFIED — NLU Tier: {result.nlu_tier.upper()} — Confidence: {result.confidence.upper()}]",
        f"Intent : {result.intent}",
    ]
    if result.product_keyword:
        lines.append(f"Product : {result.product_keyword}")
    if result.search_query:
        lines.append(f"search_query : {result.search_query}")
    if result.resolved_listing_id:
        lines.append(f"resolved_listing_id : {result.resolved_listing_id}")
    elif result.resolved_listing_ids:
        lines.append(f"resolved_listing_ids : {', '.join(result.resolved_listing_ids)}")

    directive = INTENT_DIRECTIVES.get(result.intent, "")
    lines.append("")
    lines.append(directive)
    return "\n".join(lines)

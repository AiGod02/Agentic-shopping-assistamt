"""
NLU Fallback — rule-based keyword extraction and intent detection.

This is the Tier-2 fallback used when the LLM intent classifier is
unavailable (timeout, rate-limit, downtime).  It is NOT meant to be
perfect; it covers the ~80 % common patterns so the app stays functional.

Tier 1: LLM-based classifier (primary — handles any language/phrasing)
Tier 2: This module (fallback — pattern-based, always available)
Tier 3: Raw passthrough (last resort)
"""

from __future__ import annotations

import re
from typing import Any

from shared.observability.logging import get_logger

logger = get_logger(__name__)


# ────────────────────────────────────────────────────────────────
#  Conversational prefixes & suffixes to strip
# ────────────────────────────────────────────────────────────────

# Ordered from longest to shortest so the longest match wins first.
_STRIP_PREFIXES: list[re.Pattern] = [
    # "can you tell me about / show me / find me ..."
    re.compile(r"^(?:can|could|would)\s+you\s+(?:please\s+)?(?:tell\s+me\s+(?:more\s+)?(?:about)?|show\s+me|find\s+(?:me)?|get\s+me|search\s+(?:for)?|look\s+(?:for|up))\s*", re.I),
    # "tell me more about / tell me about ..."
    re.compile(r"^tell\s+me\s+(?:more\s+)?(?:about|regarding)\s*", re.I),
    # "I want to buy / I'd like to see / I'm looking for ..."
    re.compile(r"^(?:i(?:'m|\s+am)\s+(?:looking|searching|interested)\s+(?:for|in)|i(?:'d|\s+would)\s+(?:like|love)\s+(?:to\s+)?(?:see|buy|find|get|view|browse)|i\s+(?:want|need|wanna)\s+(?:to\s+)?(?:see|buy|find|get|view|browse)?)\s*", re.I),
    # "show me / find me / get me / search for ..."
    re.compile(r"^(?:show|find|get|fetch|search|look\s+up|look\s+for|browse|display|list|give\s+me)\s+(?:me\s+)?(?:some\s+)?(?:the\s+)?", re.I),
    # "what / which ... do you have / are available"
    re.compile(r"^(?:what|which)\s+(?:kind\s+of\s+|type\s+of\s+|sort\s+of\s+)?", re.I),
    # "do you have / got any ..."
    re.compile(r"^(?:do\s+you\s+have|have\s+you\s+got|got\s+any|any)\s+", re.I),
    # "recommend me / suggest me ..."
    re.compile(r"^(?:recommend|suggest)\s+(?:me\s+)?(?:some\s+)?(?:a\s+)?", re.I),
    # "I want / I need ..."
    re.compile(r"^(?:i\s+(?:want|need|wanna))\s+(?:a\s+|an\s+|some\s+|the\s+)?", re.I),
    # "what about / how about ..."
    re.compile(r"^(?:what|how)\s+about\s+", re.I),
]

_STRIP_SUFFIXES: list[re.Pattern] = [
    re.compile(r"\s+(?:please|thanks|thank\s+you|for\s+me|pls|plz|thx)\s*[.!?]*$", re.I),
    re.compile(r"\s+(?:do\s+you\s+have|are\s+available|you\s+(?:have|got)|is\s+available)\s*[?]*$", re.I),
]


# ────────────────────────────────────────────────────────────────
#  Pronoun / positional resolvers
# ────────────────────────────────────────────────────────────────

_POSITIONAL: dict[str, int] = {
    "first": 0, "1st": 0, "one": 0,
    "second": 1, "2nd": 1, "two": 1,
    "third": 2, "3rd": 2, "three": 2,
    "fourth": 3, "4th": 3, "four": 3,
    "fifth": 4, "5th": 4, "five": 4,
    "last": -1,
}

_PRONOUN_RE = re.compile(
    r"\b(?:this|that|it|the)\s+(?:one|item|product|listing|thing)\b"
    r"|\b(?:this|that|it)\b",
    re.I,
)

_POSITIONAL_RE = re.compile(
    r"\b(?:the\s+)?("
    + "|".join(re.escape(k) for k in _POSITIONAL)
    + r")\s*(?:one|item|product|listing|result|option)?\b",
    re.I,
)

# Patterns that indicate user is asking about a SPECIFIC product (DETAIL/REVIEW)
# rather than searching for a category (SEARCH)
_DETAIL_INDICATORS = re.compile(
    r"\b(?:detail|details|spec|specs|specification|specifications|feature|features"
    r"|weight|dimension|dimensions|price|how\s+much"
    r"|more\s+(?:info|information|about)|what(?:'s|\s+is)\s+the)\b",
    re.I,
)

_AVAILABILITY_INDICATORS = re.compile(
    r"\b(?:available|in\s+stock|out\s+of\s+stock|stock\s+status|availability|is\s+(?:this|that|it)\s+available)\b",
    re.I,
)

_REVIEW_INDICATORS = re.compile(
    r"\b(?:review|reviews|opinion|opinions|feedback|rating|ratings"
    r"|worth\s+(?:it|buying)|is\s+it\s+good|how\s+is|what\s+do\s+(?:people|users|customers)\s+(?:say|think)"
    r"|user\s+(?:experience|feedback)|recommend|recommended)\b",
    re.I,
)

_CART_ADD_INDICATORS = re.compile(
    r"\b(?:add\s+(?:(?:this|that|it)\s+)?to\s+(?:my\s+)?cart|add\s+(?:it|this|that)|buy\s+(?:it|this|that)"
    r"|i(?:'ll|\s+will)\s+(?:take|get|buy|grab)|put\s+(?:it|this|that)\s+in\s+(?:my\s+)?(?:cart|bag))\b",
    re.I,
)

_CART_VIEW_INDICATORS = re.compile(
    r"\b(?:(?:view|show|see|check|what(?:'s|\s+is)\s+in)\s+(?:my\s+)?(?:shopping\s+)?cart|(?:my|the)\s+(?:shopping\s+)?cart|cart\s+total|shopping\s+cart)\b",
    re.I,
)

_CHECKOUT_INDICATORS = re.compile(
    r"\b(?:check\s*out|pay\s+now|place\s+(?:my\s+)?order|done\s+shopping|buy\s+now|proceed\s+to\s+(?:payment|checkout))\b",
    re.I,
)

_CANCEL_ORDER_INDICATORS = re.compile(
    r"\b(?:cancel\s+(?:my\s+)?order|stop\s+(?:my\s+)?order|abort\s+(?:my\s+)?order)\b",
    re.I,
)

_ORDER_INDICATORS = re.compile(
    r"\b(?:(?:my\s+)?order|track|tracking|where(?:'s|\s+is)\s+my\s+(?:order|package|delivery)"
    r"|order\s+(?:status|history)|previous\s+orders|show\s+(?:my\s+)?orders)\b",
    re.I,
)

_COMPARE_INDICATORS = re.compile(
    r"\b(?:compare|comparison|versus|vs\.?)\b",
    re.I,
)

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

_GREETING_RE = re.compile(
    r"^(?:hi|hello|hey|yo|sup|good\s+(?:morning|afternoon|evening)|howdy|hola|namaste)\s*[!.?]*$",
    re.I,
)


_INDICATOR_PHRASES = {
    "reviews", "the reviews", "are the reviews", "what are the reviews", "show reviews",
    "details", "the details", "more details", "specs", "specifications", "features",
    "price", "rating", "ratings", "feedback", "opinions", "user reviews", "customer reviews",
}


class QueryExtractor:
    """Rule-based keyword extraction — Tier 2 fallback.

    Usage:
        extractor = QueryExtractor()
        clean = extractor.extract_keywords("tell me about gaming laptops please")
        # → "gaming laptops"
    """

    def extract_keywords(self, user_message: str) -> str:
        """Strip conversational filler and return core product keywords.

        Returns the cleaned string, or empty string if message is an indicator/filler.
        """
        text = user_message.strip()

        # Check if entire message is just an indicator phrase
        if text.lower() in _INDICATOR_PHRASES:
            return ""

        # Strip prefixes
        clean = text
        for pattern in _STRIP_PREFIXES:
            clean = pattern.sub("", clean).strip()

        # Strip suffixes
        for pattern in _STRIP_SUFFIXES:
            clean = pattern.sub("", clean).strip()

        if clean.lower() in _INDICATOR_PHRASES or len(clean) < 2:
            return ""

        return clean

    def resolve_reference(
        self,
        user_message: str,
        last_seen_listings: list[dict[str, Any]] | None = None,
    ) -> str | None:
        """Try to resolve a pronoun, positional, or implicit follow-up reference to a listing ID.

        Returns the listing UUID if resolved, None otherwise.
        """
        if not last_seen_listings:
            return None

        # Check for positional ("the first one", "second", etc.)
        pos_match = _POSITIONAL_RE.search(user_message)
        if pos_match:
            word = pos_match.group(1).lower().strip()
            idx = _POSITIONAL.get(word)
            if idx is not None:
                if idx == -1:
                    idx = len(last_seen_listings) - 1
                if 0 <= idx < len(last_seen_listings):
                    return last_seen_listings[idx].get("id")

        # Check for ordinal numbers ("1st", "3rd" — covered above, but also handle raw digits)
        digit_match = re.search(r"\b(\d+)(?:st|nd|rd|th)?\s*(?:one|item|product|listing|result|option)?\b", user_message, re.I)
        if digit_match:
            idx = int(digit_match.group(1)) - 1  # 1-indexed to 0-indexed
            if 0 <= idx < len(last_seen_listings):
                return last_seen_listings[idx].get("id")

        # Check for pronoun ("this", "that", "it") OR implicit follow-up question ("what are the reviews", "specs", "is it good")
        is_implicit_followup = bool(
            _PRONOUN_RE.search(user_message) or
            _REVIEW_INDICATORS.search(user_message) or
            _DETAIL_INDICATORS.search(user_message) or
            user_message.strip().lower() in _INDICATOR_PHRASES
        )
        if is_implicit_followup:
            return last_seen_listings[0].get("id")

        return None

    def detect_intent_fallback(
        self,
        user_message: str,
        last_seen_listings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Rule-based intent detection — Tier 2 fallback.

        Returns a dict matching the IntentResult fields:
            intent, product_keyword, listing_id, search_query,
            resolved_listing_id, disambiguation_needed, confidence
        """
        msg = user_message.strip()

        # Greeting — return early
        if _GREETING_RE.match(msg):
            return {
                "intent": "CHITCHAT",
                "product_keyword": None,
                "listing_id": None,
                "search_query": None,
                "resolved_listing_id": None,
                "disambiguation_needed": False,
                "confidence": "medium",
            }

        # Resolve references
        resolved_id = self.resolve_reference(msg, last_seen_listings)

        # Compare products / listings
        if _COMPARE_INDICATORS.search(msg):
            uuids = _UUID_RE.findall(msg)
            return self._result(
                "COMPARE",
                resolved_listing_id=uuids[0] if uuids else resolved_id,
                resolved_listing_ids=uuids,
            )

        # Cancel order
        if _CANCEL_ORDER_INDICATORS.search(msg):
            return self._result("CANCEL_ORDER", resolved_listing_id=resolved_id)

        # Cart add (check before cart view to prevent 'add to my cart' matching 'my cart')
        if _CART_ADD_INDICATORS.search(msg):
            return self._result("CART_ADD", resolved_listing_id=resolved_id or (last_seen_listings[0].get("id") if last_seen_listings else None))

        # Cart view
        if _CART_VIEW_INDICATORS.search(msg):
            return self._result("CART_VIEW", resolved_listing_id=resolved_id)

        # Checkout
        if _CHECKOUT_INDICATORS.search(msg):
            return self._result("CHECKOUT", resolved_listing_id=resolved_id)

        # Order / track
        if _ORDER_INDICATORS.search(msg):
            return self._result("ORDER", resolved_listing_id=resolved_id)

        # Availability — check stock / availability
        if _AVAILABILITY_INDICATORS.search(msg):
            keyword = self.extract_keywords(msg)
            return self._result(
                "CHECK_AVAILABILITY",
                product_keyword=keyword if keyword != msg else None,
                search_query=keyword if keyword != msg else None,
                resolved_listing_id=resolved_id,
            )

        # Review — asking about opinions/reviews of something
        if _REVIEW_INDICATORS.search(msg):
            keyword = self.extract_keywords(msg)
            return self._result(
                "REVIEW",
                product_keyword=keyword if keyword != msg else None,
                search_query=keyword if keyword != msg else None,
                resolved_listing_id=resolved_id,
            )

        # Detail — asking about specs/features of something
        if _DETAIL_INDICATORS.search(msg):
            keyword = self.extract_keywords(msg)
            return self._result(
                "DETAIL",
                product_keyword=keyword if keyword != msg else None,
                search_query=keyword if keyword != msg else None,
                resolved_listing_id=resolved_id,
            )

        # If the user refers to "this/that/it" and has context → DETAIL (not SEARCH)
        if resolved_id and _PRONOUN_RE.search(msg):
            return self._result("DETAIL", resolved_listing_id=resolved_id)

        # Default: treat as SEARCH
        keyword = self.extract_keywords(msg)
        return self._result(
            "SEARCH",
            product_keyword=keyword,
            search_query=keyword,
            resolved_listing_id=resolved_id,
        )

    def _result(
        self,
        intent: str,
        product_keyword: str | None = None,
        search_query: str | None = None,
        resolved_listing_id: str | None = None,
        resolved_listing_ids: list[str] | None = None,
        disambiguation_needed: bool = False,
    ) -> dict[str, Any]:
        return {
            "intent": intent,
            "product_keyword": product_keyword,
            "listing_id": resolved_listing_id,
            "search_query": search_query,
            "resolved_listing_id": resolved_listing_id,
            "resolved_listing_ids": resolved_listing_ids or [],
            "disambiguation_needed": disambiguation_needed,
            "confidence": "low",  # Always low for rule-based
        }

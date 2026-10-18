Fix the intent routing / multi-turn reference problem in this conversational
commerce agent. The symptom (e.g. "tell me about reviews" or "show other
products" failing) is a dialogue-state and reference-resolution gap, not
purely a classification gap — implement both pieces below, in order.

GROUND RULES:
- Show me the actual current `intent_classifier.py` and orchestrator flow
  before changing anything — I want to see whether a dialogue state object
  already exists in any form before you build a new one.
- Every fix must include a runnable multi-turn test transcript, not just a
  description of the intended behavior.
- Do not silently change the existing single-turn intents that already work
  (e.g. plain "search for X") — only add reference resolution and expand
  the taxonomy.

---

## PART 1 — Dialogue State Object (this is likely the actual root cause)

Before touching intent classification, check whether a persistent per-session
state object exists that tracks, at minimum:

```python
class DialogueState:
    session_id: str
    merchant_id: str
    last_shown_listings: list[str]      # IDs of products just displayed
    focused_listing_id: str | None      # the specific item currently "in focus"
    last_search_query: str | None
    last_search_filters: dict | None
    cart_id: str | None
    turn_history: list[dict]            # last N turns, role + intent + entities
    pending_clarification: dict | None  # if we asked the user a question, what for
```

If nothing like this exists, that is almost certainly why "show reviews" and
"show other products" fail — there's no context to resolve "reviews of what"
or "other than what" against. Build this as a proper object, persisted per
session (Redis or in-memory per session_id, your call given what's already
in the stack), updated after every agent turn — not reconstructed from
scratch by re-reading raw message history each time.

## PART 2 — Reference Resolution Layer

Before intent routing, add a resolution step that runs on every user message
and attempts to resolve implicit references against `DialogueState`:

**Reference types to handle:**
- **Pronoun/demonstrative**: "it", "that one", "this" → resolve to
  `focused_listing_id`
- **Ordinal**: "the second one", "the third option" → resolve to index into
  `last_shown_listings`
- **Comparative/superlative on prior set**: "the cheaper one", "the one with
  better reviews" → requires re-ranking `last_shown_listings` by the
  mentioned attribute, not a fresh search
- **Implicit continuation**: "show other products", "what else do you have",
  "anything similar" → resolve to: re-run last search excluding
  `last_shown_listings`, or run a similarity search seeded from
  `focused_listing_id`
- **Bare follow-up with no explicit subject**: "tell me about reviews", "what
  about the price", "is it in stock" → resolve subject to `focused_listing_id`
  if one exists; if none exists (nothing has been shown/focused yet), this
  must trigger a clarification response ("Which product would you like
  reviews for?"), not a silent failure or a generic/wrong answer
- **Explicit override**: if the user names a specific product or search term
  in the same message, that always takes priority over any resolved
  reference — don't let stale context clobber an explicit new request

Output of this layer should be a resolved, fully-specified intent + entity
set that gets handed to the existing tool-calling layer — e.g. "tell me
about reviews" becomes `{intent: get_reviews, listing_id: <resolved_id>}`,
not a raw string.

## PART 3 — Full Intent Taxonomy for ACP Conversational Commerce

Expand `intent_classifier.py` to cover this full set. Group as shown —
each needs required/optional entities and whether it depends on
`DialogueState` context:

**Discovery**
- `search_products` — entities: query, filters (price, category, etc.)
- `browse_category` — entities: category
- `filter_refine` — entities: filter changes; depends on last search context
- `show_more_results` — depends on `last_shown_listings` + `last_search_query`
- `show_similar_items` — depends on `focused_listing_id`

**Product Detail**
- `get_product_details` — entities: listing_id (resolved via reference layer)
- `get_reviews` — entities: listing_id (resolved)
- `check_availability` — entities: listing_id (resolved), quantity
- `get_price` — entities: listing_id (resolved)
- `compare_products` — entities: 2+ listing_ids (resolved from ordinals/last set)

**Preference & Clarification**
- `state_preference` — entities: attribute, value (e.g. "I don't care about
  gaming, prioritize battery life") — persists into user preference memory
- `answer_clarification` — user responding to a clarifying question the
  agent asked; resolve against `pending_clarification`
- `reject_option` — "not that one", "none of these work" — removes item(s)
  from consideration, may trigger a refined search

**Cart & Checkout**
- `add_to_cart` — entities: listing_id (resolved), quantity
- `remove_from_cart` — entities: listing_id or "all"
- `view_cart`
- `modify_cart_quantity`
- `checkout` — depends on cart state
- `apply_promo` — entities: promo_code

**Orders**
- `track_order` — entities: order_id (or resolve to most recent order if
  user says "my order" with no ID and only one exists)
- `order_history`
- `cancel_order` — entities: order_id
- `request_return_refund` — entities: order_id, reason

**Merchant/Meta**
- `merchant_info` — hours, policies, shipping, location
- `escalate_to_human` — user frustration or explicit request

**Conversational**
- `greeting`
- `chitchat_out_of_scope` — respond briefly, redirect to commerce
- `unclear_intent` — genuinely ambiguous even after reference resolution;
  must trigger a clarifying question, never a guess presented as fact

For every intent above that says "resolved" — that resolution must happen
via the Part 2 reference layer, not by re-classifying the raw sentence
without context.

## PART 4 — Test Transcripts (write these as actual multi-turn test cases)

At minimum, implement and pass these sequences end to end:

```
Turn 1: "Show me running shoes under $100"
  → search_products, results shown, last_shown_listings populated

Turn 2: "Tell me about the second one"
  → get_product_details, listing_id resolved via ordinal → last_shown_listings[1]
  → focused_listing_id updated to that ID

Turn 3: "What do people say about it?"
  → get_reviews, listing_id resolved via focused_listing_id (pronoun "it")

Turn 4: "Show me other options"
  → show_more_results, re-search excluding last_shown_listings

Turn 5: "Compare the first two"
  → compare_products, listing_ids resolved via ordinals against new
    last_shown_listings from Turn 4

Turn 6: "Add the cheaper one to my cart"
  → requires comparative resolution: rank the currently focused comparison
    set by price, resolve to lowest, then add_to_cart

Turn 7: "Actually never mind, show me something in blue instead"
  → explicit override: ignore prior focus, run new search with new filter
```

Run all 7 turns as one continuous session. Paste the actual resolved
intent + entities + response for each turn. Any turn that fails to resolve
correctly must be fixed before moving on.

## PART 5 — Failure Mode Handling

- If a reference can't be resolved (e.g. "tell me about reviews" with an
  empty `last_shown_listings` and no `focused_listing_id`), the agent must
  ask a clarifying question — never guess, never silently pick an arbitrary
  product, never return a generic non-answer.
- If the reference resolution layer itself errors, log it with full session
  state attached — don't let it fail silently and fall through to a raw
  unresolved intent.

---

## FINAL OUTPUT

1. Show the diff for the DialogueState object and where it's persisted.
2. Show the diff for the reference resolution layer.
3. Show the expanded intent taxonomy in `intent_classifier.py`.
4. Paste the full 7-turn test transcript with actual resolved output per turn.
5. State clearly: does this dialogue state persist correctly across
   reconnects/session resume, or does it reset if the session drops?
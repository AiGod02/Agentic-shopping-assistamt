# Full Functional Verification — Every Component, Real Execution Only

Goal: confirm every capability this agent claims to have is backed by a
REAL, tested handler — not just present in a classifier's vocabulary or a
spec document. The checkout/compare bug proved that a capability can be
"planned" without ever being "built." This prompt exists to catch every
other instance of that gap, plus verify actual behavior once a handler is
confirmed real.

GROUND RULES:
- For every single item below, first answer: "Does a real handler exist for
  this, yes or no — show me the code." Only if yes, proceed to test it.
- If no handler exists, say so plainly and list it under a "NOT YET BUILT"
  section at the end — do not let anything silently fall through to a
  different tool and get marked as tested.
- Every test needs real, pasted output — request/response, or actual
  database state read back independently of the chat response text.
- Work through this in the sections given, in order.

---

## SECTION 1 — Intent Inventory: Vocabulary vs Real Handler

Go through every intent that exists in the classifier/taxonomy right now
(search, get_details, get_reviews, check_availability, compare_products,
add_to_cart, remove_from_cart, view_cart, checkout, track_order,
state_preference, answer_clarification, escalate_to_human, and any others
present in the actual code — enumerate them from the real classifier, don't
use this list as the ground truth, use it as a minimum checklist).

For each one, produce a table row:

| Intent | Handler exists? | File/function | Falls back to search if unhandled? |
|---|---|---|---|

Anything marked "no handler" or "falls back to search" is broken by
definition — list these prominently before doing any further testing.

## SECTION 2 — Per-Intent Functional Test (only for confirmed real handlers)

For each intent confirmed to have a real handler, test:
1. **Happy path** — normal expected input, confirm correct tool fires and
   response matches the request.
2. **Empty/edge state** — e.g. `get_reviews` on a product with zero reviews,
   `compare_products` with only one relevant item available,
   `check_availability` on an out-of-stock item, `view_cart` on an empty
   cart. Confirm honest, specific responses — never a generic fallback.
3. **Invalid reference** — e.g. "compare it" or "add it to cart" with no
   prior context (`focused_listing_id` is null) — confirm this triggers a
   clarifying question, not a guess or a crash.

Paste actual output for all three cases, per intent.

## SECTION 3 — Persistence Read-Back (every write must be independently verified)

For every action that writes data (add_to_cart, remove_from_cart, checkout/
order creation, state_preference), do not trust the chat response text.
Instead:
1. Perform the action through the conversation.
2. Independently query the database (or a direct API call, not the chat
   response) to confirm the write actually happened and matches what was
   claimed.
3. If any action reports success in chat but the independent check shows
   no corresponding write, that is a critical bug — flag it immediately,
   fix it, and do not proceed to other sections until it's resolved.

Cover explicitly: add_to_cart, remove_from_cart, cart quantity update,
checkout → order creation, checkout → payment record creation,
state_preference → preference memory storage.

## SECTION 4 — Full Realistic Multi-Turn Journeys

Run each of these as one continuous session, pasting real output per turn.
These are meant to resemble how an actual confused/indecisive real customer
talks, not a clean scripted happy path.

**Journey A — Full purchase, no detours:**
```
"hi, looking for a laptop"
"tell me more about it"
"what do reviews say"
"add it to cart"
[independently verify cart state]
"checkout"
[independently verify order + payment state]
"track my order"
```

**Journey B — Comparison and indecision:**
```
"show me laptops"
"compare it with something cheaper"
[if only one match exists, confirm honest response — not silent re-search]
"actually show me something else instead"
"never mind, add the first one to cart"
```

**Journey C — Objection and recovery:**
```
"show me a MacBook"
"that's too expensive"
[confirm objection-handling response — alternative or value justification]
"okay fine, add it anyway"
"wait, remove it, I changed my mind"
[independently verify cart is actually empty again]
```

**Journey D — Ambiguous and broken references:**
```
"tell me about reviews" [with no prior product discussed at all —
  fresh session, first message]
[must trigger a clarifying question, never guess]
"the second one" [also with no prior search — same requirement]
```

**Journey E — Repeated/contradicted requests:**
```
"show me laptops"
"show me laptops" [exact repeat — confirm it doesn't break or duplicate
  cart/state]
"add it to cart"
"add it to cart" [repeat — confirm this doesn't create two cart entries
  instead of updating quantity or being a no-op, decide and confirm
  intended behavior]
```

**Journey F — Mid-conversation topic switch:**
```
"show me laptops"
"actually, do you have any monitors"
[confirm this is treated as a genuine new search, not incorrectly
  resolved as a reference to the laptop conversation]
```

## SECTION 5 — Failure Injection (what happens when something breaks)

1. Temporarily simulate the vector search (Chroma) being unavailable —
   what does the agent say? It should degrade honestly ("I'm having
   trouble searching right now"), never crash uncaught or return a
   fabricated/generic answer.
2. Simulate the payment provider (Razorpay test mode) returning an error
   during checkout — confirm the agent reports this honestly and does NOT
   claim the order succeeded.
3. Simulate a database connection drop mid-conversation — confirm the
   session doesn't silently lose all context, or if it must reset, that
   it tells the user clearly rather than continuing with corrupted state.

## SECTION 6 — Cross-Session and Reconnect Behavior

1. Start a conversation, add items to cart, then simulate a disconnect/
   reconnect (new request with the same session ID). Confirm cart and
   dialogue state are still correctly present.
2. Confirm a genuinely new session (new session ID) starts completely
   clean — no bleed-through from a previous unrelated session.

---

## FINAL OUTPUT

1. Section 1 table — this is the most important output. Anything without a
   real handler goes in a clearly labeled "NOT YET BUILT" list.
2. Section 2 results per confirmed-real intent.
3. Section 3 persistence verification results — flag any success-without-
   a-write immediately and separately, these are the highest-severity finds.
4. All 6 journey transcripts (Section 4), full and real.
5. Section 5 and 6 results.
6. A final honest paragraph: given everything above, what is genuinely
   solid, what is fragile, and what should NOT be demoed or relied on yet.
   Do not round this up to sound better than the evidence supports.
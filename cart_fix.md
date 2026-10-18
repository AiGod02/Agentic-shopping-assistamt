CRITICAL: checkout does not work, and add_to_cart may be reporting false
success. This blocks everything else — fix this before any other queued
work.

Actual failing transcript:
```
User: "compare it"       → fell back to search_listings, same single result
User: "add it to cart"   → add_to_cart reported success
User: "no just checkout" → fell back to search_listings (no checkout ran at all)
User confirms: cart never actually updated
```

GROUND RULES:
- Diagnose before fixing. Show me the actual intent classifier output for
  "compare it" and "no just checkout" — what intent was it classified as,
  and what made it fall through to search_listings specifically?
- For every claim of "fixed," show a real before/after transcript, not a
  description.

---

## PART 1 — Diagnose the Fallback Behavior (root cause, likely shared by both bugs)

1. Show me what happens in the orchestrator when a message's classified
   intent has no matching handler, or when classification itself fails/is
   low-confidence. Is there an explicit fallback path, and what does it do?
2. State clearly: is `search_listings` literally the default fallback tool
   for anything unclassified or unhandled? If so, this is the root cause —
   an unhandled intent must NEVER silently execute an unrelated tool and
   present its output as if it answered the question. The correct fallback
   is a clarifying question ("I'm not sure I follow — could you rephrase?"
   or similar), never a different tool's output disguised as an answer.
3. Confirm whether `compare_products` and `checkout` intents were actually
   implemented with real handlers anywhere in the codebase, or only added
   to a taxonomy/spec document without corresponding tool implementations.
   Show me the actual code, or its absence.

## PART 2 — Fix: Real Handlers for Compare and Checkout

1. `compare_products`: when triggered, resolve against `DialogueState`
   (focused item + last shown listings, per the reference resolution work).
   If there is genuinely only one relevant item to compare (e.g. catalog
   has one laptop), respond honestly — "I only have one laptop matching
   that right now — want me to check similar categories, or is there
   something specific you'd want in an alternative?" — never silently
   re-run search and present the same single item as if comparison happened.
2. `checkout`: when triggered, this must actually read the current cart
   state and proceed through the real checkout flow (payment intent
   creation, order creation) — not fall through to search under any
   circumstance. If cart is empty, say so explicitly.
3. Add both intents to whatever explicit routing table/classifier exists,
   with test coverage confirming they no longer fall through to the
   search fallback.

## PART 3 — Verify Cart Persistence End to End (the more dangerous bug)

1. Trace `add_to_cart` from tool call to actual database write. Show me:
   does it insert/update a real cart record tied to the session/customer
   identity, or does it return a hardcoded success message without a
   corresponding write?
2. If the write is real: show me why "checkout" or a "view cart" call
   afterward doesn't reflect it — is there a session/identity mismatch
   (e.g. cart written under one session key, checkout reading a different
   one)? This would tie directly to the customer identity work from the
   auth-model fix — verify the same session/identity is used consistently
   across add_to_cart, view_cart, and checkout.
3. If the write is NOT real: this is a fabricated success response — fix
   it so add_to_cart never reports success without a confirmed, verifiable
   write. Add an explicit read-back check: after writing, read the cart
   back and confirm the item is actually present before returning success
   to the user.
4. Add a `view_cart` test: add an item, then immediately fetch the cart
   directly (bypassing conversation) and confirm the item is actually
   there at the data layer, not just in the chat response text.

## PART 4 — Regression Test: Full Realistic Conversation

Re-run this exact sequence end to end and paste the real output for every
turn:
```
1. "i am looking for a laptop"
2. "what do users say about this"
3. "compare it" [or, if catalog has only one laptop, confirm the honest
    response described in Part 2.1]
4. "give me more details"
5. "add it to cart"
6. [Independently verify cart state at the DB level — not just the chat
    response]
7. "checkout"
8. [Confirm this actually proceeds through payment/order creation, or
    fails with a real, honest reason — never silently re-searches]
```

Every turn must produce output that actually matches what was asked, not a
generic "recommend + add to cart" response reused regardless of intent.

---

## FINAL OUTPUT

1. Root cause explanation for the fallback-to-search behavior.
2. Diffs for compare_products and checkout handlers.
3. Diff/explanation for the cart persistence fix (or confirmation of what
   was already correct, with evidence).
4. Full Part 4 transcript, real output per turn.
5. State explicitly: is checkout now capable of completing a real purchase
   end to end, yes or no, with evidence either way.
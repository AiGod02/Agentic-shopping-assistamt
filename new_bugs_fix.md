Four items, in strict priority order. Do not proceed to the next until the
current one has real evidence, not a code-review claim. Item 1 is the most
urgent — treat it as a potential live data leak until proven otherwise.

GROUND RULES:
- "The code has a check for X" is not evidence. Evidence is: I ran it,
  here's the actual output/state.
- If item 1 confirms a real collision, fix it before touching anything else
  in this list.

---

## ITEM 1 — Guest Cart Collision Test (do this first, treat as urgent)

The guest/unauthenticated fallback identity in `commerce_tools.py` appears
to use a single hardcoded UUID (`905e50a3-80b9-4a96-a10c-56ef92989fe7`) for
ALL unauthenticated requests, rather than a fresh identity per session.

1. Show me the actual code where this fallback UUID is generated/assigned.
   Confirm: is it a hardcoded constant, or dynamically generated per session
   and just happened to repeat across my earlier tests because I reused a
   session? Show the literal source, not a description.
2. Live test: open two separate, fully anonymous sessions (no auth token,
   two distinct session IDs if session IDs are used at all for guests).
   Add a different item to cart in each. Independently query both carts
   (direct DB/API read-back, not chat response) and report:
   - Are they the same cart / same underlying identity?
   - Does session A see session B's item, or vice versa?
3. If they collide: this is confirmed as a critical cross-customer data
   leak. Fix it by generating a unique guest identity per session (e.g. a
   session-scoped UUID created at session start, stored in DialogueState,
   never shared across sessions) — not a single fallback constant.
4. Re-run the test after the fix. Confirm two anonymous sessions now have
   fully independent carts. Paste both independent read-backs.

## ITEM 2 — Order Status Propagation (payments.status → orders.status)

Confirmed gap: `payment_server/api/v1/webhooks.py` updates `payments.status`
to `captured` on a successful Stripe/Razorpay webhook, but nothing updates
the linked `orders.status` from `pending_payment` to `paid`.

1. Show me the current webhook handler code.
2. Add the missing update: on successful payment webhook, also update the
   corresponding order's status (`pending_payment` → `paid`), scoped
   correctly to the right order via whatever FK/reference links payment to
   order.
3. Handle the failure case too: if a webhook indicates payment failure
   (`payment_intent.payment_failed` or equivalent), update order status to
   reflect that honestly (e.g. `payment_failed`), not leave it silently at
   `pending_payment` forever either.
4. Test end to end: create an order, trigger a real test-mode Stripe
   payment success webhook (or simulate it accurately), confirm order
   status actually transitions. Paste the before/after order state from an
   independent query.

## ITEM 3 — How Does a Conversation Currently Know Its Merchant?

Store routing (subdomain/slug) doesn't exist yet. Before deciding whether
that's needed now, answer clearly:

1. Right now, when a chat session starts, where does `merchant_id` actually
   come from — a hardcoded config value, a request parameter, something
   else? Show the actual code path from "conversation starts" to
   "merchant_id is known."
2. State plainly: does the current setup support more than one merchant
   running simultaneously today, or is it effectively single-merchant until
   store routing is built? This determines whether store routing is
   pilot-blocking or safely deferrable.
3. Do not build store routing yet — just answer the above clearly so this
   can be a deliberate decision, not an unknown.

## ITEM 4 — Merchant Dashboard Isolation, Live Test (not code review)

The prior audit confirmed JWT + merchant_id filtering exists in code. Now
prove it live:

1. Create or use two real merchant accounts (Merchant A, Merchant B).
2. Log in as Merchant A. Walk through: catalog, orders, analytics,
   settings. Note what's visible.
3. Log in as Merchant B (separate session). Walk through the same pages.
4. Confirm explicitly: at no point does Merchant A's data appear in
   Merchant B's session or vice versa, across every page tested — not just
   the listings/orders endpoints already tested earlier, but the full
   dashboard UI experience.
5. Paste actual screenshots or response payloads per page, per merchant —
   not a summary claim.

---

## FINAL OUTPUT

1. Item 1: collision confirmed yes/no, fix applied if needed, before/after
   evidence.
2. Item 2: diff + before/after order status transition evidence.
3. Item 3: clear answer on current merchant-binding mechanism and whether
   it supports multi-merchant today.
4. Item 4: full live walkthrough evidence, both merchants, every page.
5. Update `acp_status.md` to reflect the real state of each — including
   moving Item 1 to a documented "critical fix, verified" entry given its
   severity.
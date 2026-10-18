Critical regression: customer-facing search is now requiring authentication.
This is wrong — search/browse must be public. Diagnose and fix the root
cause: likely conflation between two distinct auth models that got merged
during the recent security fixes.

GROUND RULES:
- Diagnose first. Show me every route currently behind
  `Depends(get_current_user)` (or any auth dependency) across all three
  services, categorized by whether it SHOULD require merchant auth,
  SHOULD require some form of customer identity, or SHOULD be fully public.
- Do not just remove auth from search — determine the correct auth model
  for every endpoint type and apply it consistently and explicitly.

---

## PART 1 — Diagnose: Two Auth Domains That Must Be Distinguished

Establish and document explicitly, as a table, which category every
existing endpoint falls into:

**Category A — Merchant Auth Required** (dashboard actions, business owner
managing their own data):
- Listing create/update/delete
- Order status update (merchant side)
- Payment capture/refund
- Bulk upload
- Analytics/dashboard views
- Any merchant settings/team/billing endpoint

**Category B — Public / No Auth** (customer browsing, before any commitment):
- `search_listings` / semantic search
- `get_listing_details`
- `get_reviews`
- `check_availability`
- Anything the conversational agent calls just to answer questions or show
  products — a shopper should never need to log in to browse or ask
  questions.

**Category C — Customer Identity Required, But NOT Merchant Auth** (this is
a THIRD category, distinct from A — do not conflate it with merchant auth):
- Checkout / payment submission (needs to know who's paying, but this is a
  customer identity/session, not a merchant JWT)
- Order tracking (needs to know it's the right customer's order — this
  should probably be scoped by session ID, order confirmation token, or a
  lightweight customer account, NOT the same `get_current_user` used for
  merchant dashboard auth)
- Cart persistence across a session

Show me: does a distinct customer identity mechanism exist at all right
now, or has `get_current_user` (built for merchants) been the only auth
primitive available, causing it to get reused incorrectly for customer-side
needs too? If the latter, that's the actual root cause — state this
explicitly.

## PART 2 — Fix: Correct Auth Per Category

1. For every Category B endpoint: remove any auth dependency entirely.
   Confirm these work with zero auth headers.
2. For Category A: confirm `Depends(get_current_user)` (merchant auth)
   remains correctly applied — this should be unchanged from the recent
   fixes.
3. For Category C: implement (or confirm if already implemented) a
   lightweight customer session/identity mechanism, separate from merchant
   auth — e.g. a session token issued at conversation start, used to scope
   cart/checkout/order-tracking, without requiring a login. Do not reuse
   `get_current_user` (merchant auth) for this — build or confirm a
   distinct dependency, e.g. `get_current_session` or similar, so the two
   systems can never be accidentally conflated again.

## PART 3 — Regression Check

1. Confirm this didn't silently break anything else — re-run the full
   pytest suite, paste actual output.
2. Manually test: an anonymous request (no auth header at all) hitting
   search, get_listing_details, get_reviews, check_availability — all
   should succeed.
3. Manually test: an anonymous request hitting listing update/delete,
   payment capture/refund, bulk upload — all should still correctly return
   401/403.
4. Run one full conversation end to end with zero auth headers attached to
   the customer-facing session, from "show me laptops" through to
   checkout, and confirm nothing incorrectly demands merchant-style login
   at any point along the way.

## PART 4 — Prevent This From Recurring

Add a code comment or short doc note at the top of the merchant auth
dependency (`get_current_user`) explicitly stating: "This is MERCHANT
dashboard auth only. Do not apply to customer-facing/public endpoints —
see [Category B/C table above] for the correct pattern." This is cheap
insurance against the same conflation happening again in a future session.

---

## FINAL OUTPUT

1. The categorized endpoint table (Part 1).
2. Root cause statement: confirm explicitly whether merchant auth was
   incorrectly applied to public endpoints, and where.
3. Diffs for every endpoint that needed correcting.
4. Full pytest output + the 4 manual test results from Part 3.
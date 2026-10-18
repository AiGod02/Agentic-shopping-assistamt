Convert every manually-verified finding in `acp_status.md` into a real,
committed pytest suite. This is the permanent regression net — once this
exists, future changes get checked automatically instead of requiring a
full manual re-audit like the one that's been happening across recent
sessions.

GROUND RULES:
- Use fixtures/factories (shared `conftest.py`), not copy-pasted setup code
  per test.
- Tests run against a dedicated test database only — never dev or prod data.
- Every test must be independently runnable, no dependency on state left by
  a previous test (use transactions/rollback or fresh fixtures per test).
- After writing the full suite, run it, paste the complete output, and fix
  anything that fails before calling this done.
- Reuse the exact real request/response shapes already proven in this
  project's manual verification — don't invent new expected behavior.

---

## conftest.py — Shared Fixtures

Build fixtures for:
- Two distinct merchant accounts (Merchant A, Merchant B) with valid JWTs
- A seeded listing per merchant
- A seeded order per merchant, in `pending_payment` status
- A seeded payment record linked to an order
- An anonymous/guest client (no auth header)
- A test DB session with transaction rollback per test (or equivalent
  isolation strategy)
- A helper to generate a signed guest JWT with a fresh UUID, matching the
  fix already implemented in `agent.py`/`cart.py`

---

## test_auth.py

- Unauthenticated `POST /api/v1/payments/create` → 401
- Unauthenticated `POST /{payment_id}/capture` → 401
- Unauthenticated `POST /{payment_id}/refund` → 401
- Unauthenticated `POST /escrow/hold` → 401
- Merchant A token used to capture/refund Merchant B's payment → 403
- Merchant A token used successfully on their own payment → 200
- App fails to start / raises clear error if `JWT_SECRET_KEY` is unset —
  test via config validation, not full app boot if that's impractical
- Search, listing details, reviews, availability — all succeed with NO
  auth header (public endpoints must never require auth)
- Direct `POST /api/v1/cart` with no JWT → 401 (per the guest cart fix)

## test_listing_idor.py

- Merchant B attempts `PATCH` on Merchant A's listing → 403
- Merchant B attempts `DELETE` on Merchant A's listing → 403
- Merchant A on their own listing → 200, change persists
- Merchant A's `GET /listings` never includes Merchant B's items, and vice
  versa

## test_order_isolation.py

- Merchant A listing orders never includes Merchant B's orders
- Merchant A fetching Merchant B's order by ID directly → expect whatever
  status code (403 or 404) was decided as the standard — confirm and use it
  consistently
- Query-level scoping: assert the repository method itself requires
  merchant_id, not just the route handler

## test_bulk_upload.py

- Valid CSV row → imported successfully
- Row with `"$19.99"` (currency symbol) → correctly parsed
- Row with `"N/A"` price → row fails gracefully, included in `errors`,
  does not abort the batch
- Row with missing title → row fails gracefully, included in `errors`
- File over 10MB → 413
- Response shape matches: `imported_count`, `failed_count`, `errors[]`,
  `search_indexing_triggered`
- Duplicate SKU/title handling — confirm and test whatever behavior is
  intended (reject duplicate, or allow and flag)

## test_search_isolation.py

- Seed a listing only under Merchant B. `semantic_search`/`keyword_search`
  called with Merchant A's `merchant_id` → empty result
- Calling either search function with `merchant_id=None` or empty string
  → raises the expected error, never silently searches unfiltered
- Category relevance: query "laptop" against a catalog containing laptops
  and unrelated categories (e.g. TV, tablet) → only laptop-category items
  returned, no duplicates in the result set

## test_checkout_idempotency.py

- Two checkout calls with an identical cart → identical idempotency key
  both times
- Checkout call after modifying cart contents (different item or quantity,
  same item count) → different idempotency key — this specifically tests
  the fix for the count-based key bug found earlier
- Assert the key is derived from actual cart contents (hash), not from
  item count alone

## test_guest_cart_isolation.py

- Two separate anonymous sessions (no auth), each with a freshly generated
  guest JWT → adding different items to each results in two fully separate
  carts (query both, assert zero cross-contamination) — this is the
  regression test for the critical guest cart collision bug
- Confirm no hardcoded fallback UUID is used anywhere — if a guest JWT is
  missing/malformed, cart operations should fail cleanly (401), never
  silently fall back to a shared identity

## test_order_payment_status_propagation.py

- Create an order in `pending_payment`. Simulate a successful payment
  webhook (`payment_intent.succeeded` / `captured`) with the correct
  signature. Assert `orders.status` transitions to `paid`.
- Simulate a failed payment webhook. Assert `orders.status` transitions to
  `payment_failed`.
- Assert the payment record's own status also updates correctly alongside
  the order (`captured`/`failed`)
- Test with an invalid/missing webhook signature → request rejected,
  no status change occurs (ties to the webhook signature verification
  requirement)

## test_merchant_dashboard_isolation.py

- Merchant A's `/api/v1/listings`, `/api/v1/orders`, `/api/v1/analytics/*`,
  `/api/v1/merchants/me` never return Merchant B's data, and vice versa —
  test each endpoint explicitly, not just one representative example

## test_reference_resolution.py

- Fresh session, "tell me about reviews" with no prior context → triggers
  a clarifying question, not a crash or a guess
- Fresh session, "the second one" with no prior search → triggers
  clarification
- After a search, "the second one" correctly resolves to the second item
  in the last shown results
- After viewing a product, "it" / "that one" correctly resolves to the
  focused item

## test_intent_handlers.py

- Parametrized test across every intent confirmed to have a real handler
  (per the Section 1 inventory already done): confirm each fires its
  correct tool, not a fallback to search_listings
- Specifically test `compare_products` and `checkout` — these previously
  fell through to search_listings incorrectly; this is the regression test
  for that bug

---

## FINAL OUTPUT

1. Full file tree of the new test suite.
2. Full `conftest.py` contents.
3. Complete pytest run output — pass/fail count per file, full tracebacks
   for any failures, fixed before this is considered done.
4. Confirm this suite is added to whatever CI/pre-commit process exists (or
   flag that none exists yet, as a separate follow-up item — don't silently
   skip mentioning it).
5. Update `acp_status.md`: add a new row noting the manual verifications
   above are now backed by a committed automated suite, with the file path
   for each.
Work through this in two phases, in order. Do not start Phase 2 until every
item in Phase 1 shows a real PASS with actual evidence (response body, log
output, or diff) — not a description of expected behavior.

GROUND RULES FOR THIS SESSION:
- Every test result must include actual output (status code + response body,
  or actual log/console output). "This should now work" is not a result.
- If something fails, fix it and re-run — don't move to the next item with
  a known failure still open.
- If you can't verify something (e.g. infra not available yet), say
  UNVERIFIED and explain why — don't mark it PASS anyway.

---

## PHASE 1 — Close out existing remediation (no new infra required)

### 1.1 Payment ownership IDOR test

This was built (`_verify_payment_ownership` in `payment_server/api/v1/payments.py`)
but never actually tested. Write and run a test that:
1. Creates/seeds a payment record belonging to Merchant A.
2. Authenticates as a user belonging to Merchant B.
3. Attempts `POST /{payment_id}/capture` and `POST /{payment_id}/refund` on
   Merchant A's payment using Merchant B's token.
4. Expect HTTP 403 on both calls.

Paste the actual request/response for each call.

### 1.2 Order data isolation check

This has never been checked — all prior isolation work covered listings and
search only, not orders.
1. Grep the orders repository/query layer (`merchant_server`) for every read
   path (`list orders`, `get order`, `get order by id`) and confirm
   `merchant_id` is enforced in the query itself.
2. Seed one order under Merchant A and one under Merchant B.
3. Authenticate as Merchant A, call whatever endpoint lists/fetches orders.
   Confirm Merchant B's order is never returned or accessible by ID.
4. If Merchant A can fetch Merchant B's order by guessing/passing its ID
   directly, that's a FAIL — fix it with the same ownership-check pattern
   used for listings and payments.

### 1.3 Full regression suite

1. Run the complete existing pytest suite across all three services
   (`merchant_server`, `payment_server`, `agent_server`).
2. Paste the actual output — pass/fail count, and full detail on any failures.
3. If anything broke because of the auth, IDOR, bulk-upload response shape,
   or idempotency changes from the prior fixes, fix the regression — don't
   skip or disable the failing test.

---

## PHASE 2 — New infrastructure integration (Stripe, Weaviate, Redis)

Do not treat these as "just add the key" — each one is new/first-time
runtime behavior that needs its own verification, even if the code already
exists.

### 2.1 Stripe integration verification

Before wiring in the real test-mode key, answer and show evidence for:
1. Has this payment code path ever actually executed against Stripe's API
   before, or only against a mock/stub? State which.
2. Does the webhook handler (if one exists) verify the `Stripe-Signature`
   header against the webhook signing secret before trusting any event? If
   not, this is a critical gap — fix it before proceeding. Show the
   verification code.
3. Does the actual Stripe charge/PaymentIntent call pass Stripe's own
   `Idempotency-Key` parameter on the request (separate from our internal
   cart-hash idempotency key)? These solve different problems — our key
   prevents duplicate orders in our system, Stripe's key prevents duplicate
   charges on the customer's card if the network request itself is retried.
   Confirm both exist independently.
4. Confirm the key being used is `sk_test_...` (test mode), and that there's
   no code path or fallback that could resolve to a live key.

Then:
5. Put the test-mode key in env, run a real test charge through the full
   checkout flow (agent → commerce_tools → payment_server → Stripe test API).
6. Paste the actual Stripe test dashboard confirmation or API response
   showing the PaymentIntent/charge succeeded.
7. Deliberately trigger a duplicate request (call checkout twice with the
   same cart) and confirm only one charge appears in Stripe test mode, not two.

### 2.2 Weaviate cutover verification

1. Once the Weaviate cluster is live and connected, re-run the exact
   merchant-isolation test that previously passed against Chroma
   (semantic_search for a Merchant B item using Merchant A's merchant_id),
   this time explicitly against `WeaviateSearch`, not `ChromaSearch`.
   Confirm which class was actually instantiated for this test — show it.
2. Confirm the `merchant_id` filter syntax was correctly adapted to
   Weaviate's filter format (Weaviate uses GraphQL-style `where` filters,
   which are not the same shape as Chroma's metadata filter dict) — don't
   assume a copy-pasted filter works identically. Show the actual filter
   being sent to Weaviate.
3. Paste the actual empty-result response confirming isolation holds on
   Weaviate specifically.

### 2.3 Redis Cloud verification

1. State clearly what Redis is being used for in this deploy: Celery broker,
   session storage, caching, or some combination — confirm from actual config,
   don't assume.
2. Confirm the connection string/credentials are read from env vars, not
   hardcoded, and that the app fails to start with a clear error if the
   Redis URL is missing (same pattern as the JWT secret fix).
3. Test graceful degradation: temporarily point the app at an invalid Redis
   URL (or stop the Redis connection) and observe what happens. Does the app
   crash entirely, or does it degrade gracefully (e.g. Celery tasks queue
   fail loudly and get logged, rather than silently vanishing)? Paste the
   actual behavior observed.

---

## FINAL OUTPUT

After both phases, give me a single status table:

| Item | Status | Evidence |
|---|---|---|

Then answer directly: "Is this safe to demo live with real merchant accounts
in the room, yes or no, and what — if anything — is still open."
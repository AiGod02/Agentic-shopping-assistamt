Implement the following 5 fixes exactly as specified. Work through them in
this order — do not skip ahead if an earlier one is incomplete. After each
fix, show me the actual diff before moving to the next one.

RULES FOR THIS SESSION:
- Do not mark anything as done without showing the actual code change.
- Do not use bare `except Exception: pass` anywhere in this work — every
  except block must log the error with context (row number, merchant_id,
  request id — whatever is relevant) at minimum.
- After all 5 fixes, run the automated verification tests listed at the
  bottom and paste the actual output, not a summary of what should happen.
- If any existing test breaks because of these changes, fix it — don't
  disable or skip it.

---

## FIX 1 — Payment server authentication

File: `payment_server/payment_server/api/v1/payments.py`

- Import `get_current_user` (and `require_permission` if used elsewhere in
  this file) from `shared.auth.rbac`.
- Add `user=Depends(get_current_user)` to every write endpoint: `/create`,
  `/{payment_id}/capture`, `/{payment_id}/refund`, `/escrow/hold`,
  `/escrow/{escrow_id}/release`.
- Confirm the payment record being captured/refunded actually belongs to
  the authenticated user's merchant (same IDOR pattern as Fix 2) — don't
  just add auth, add ownership verification too.
- Before writing code: also check the JWT_SECRET config in both
  `merchant_server/config.py` and `payment_server/config.py`. If either
  has a hardcoded fallback default (e.g. "change-me-jwt-secret"), change it
  to raise a startup error if the env var isn't set, instead of silently
  falling back. Show me this fix too — it's as important as the auth
  dependency itself.

## FIX 2 — IDOR protection on listings

File: `merchant_server/merchant_server/api/v1/listings.py`

- In `update_listing` and `delete_listing`: after fetching the listing,
  verify `str(listing.merchant_id) == user.merchant_id` (or the user has
  an admin/superuser role). If not, raise `HTTPException(status_code=403)`.
- Apply this same ownership check pattern to any other write/delete
  endpoint in this file that takes a listing ID — check the whole file,
  not just the two named methods.

## FIX 3 — Bulk upload robustness

File: `merchant_server/merchant_server/api/v1/listings.py`, function
`bulk_upload_catalog`

- Enforce a 10MB max payload size. Check this before fully reading the
  file into memory — reject early with HTTP 413 if `Content-Length`
  exceeds the limit, don't just check after loading it.
- Write a safe price parser that handles: currency symbols ("$19.99"),
  thousands separators ("1,299.00"), "N/A"/blank/null, and genuinely
  invalid strings. Invalid strings should mark that row as failed, not
  crash the request.
- Wrap each row's processing (both CSV and JSON paths) in its own
  try/except. On failure, record `{"row": <line number>, "error": <message>}`
  and continue to the next row — do not abort the batch.
- Change the response shape to:
  ```json
  {
    "status": "completed",
    "imported_count": <int>,
    "failed_count": <int>,
    "errors": [{"row": <int>, "error": "<string>"}],
    "search_indexing_triggered": <bool>
  }
  ```
- Fix the existing silent `except Exception: pass` around the Celery
  `sync_search_index` dispatch — log the failure and set
  `search_indexing_triggered: false` in the response instead of hiding it.

## FIX 4 — Chroma vector search merchant isolation

File: `agent_server/agent_server/core/chroma_search.py`

- Update `semantic_search(query, limit, merchant_id)` and
  `keyword_search(query, limit, merchant_id)` to require `merchant_id`
  as a mandatory parameter (not optional/default None) — a search with
  no merchant_id should fail loudly, not silently search everything.
- Pass `merchant_id` into the Chroma query's metadata `where` filter, and
  confirm it's also applied on the SQL side of the hybrid search.
- Update every caller of these two functions across the codebase to pass
  `merchant_id` — grep for all call sites, don't just fix the function
  signature and leave callers broken.

## FIX 5 — Deterministic checkout idempotency + merchant context propagation

File: `agent_server/agent_server/tools/commerce_tools.py`

- Replace the `str(uuid.uuid4())` idempotency key in the checkout tool
  with a deterministic key derived from actual cart contents, not just
  item count. Use something like:
  ```python
  import hashlib
  cart_signature = hashlib.sha256(
      "|".join(sorted(f"{item.id}:{item.qty}" for item in cart.items)).encode()
  ).hexdigest()
  idempotency_key = f"checkout-{session_id}-{cart_signature}"
  ```
  This way, an identical cart retried after a network failure reuses the
  same key (safe to dedupe), but a genuinely different cart (even with the
  same item count) gets a new key.
- Ensure `active_merchant_id` is threaded as an explicit parameter into
  `search_listings`, `get_listing_details`, and `check_availability` —
  not inferred from anywhere implicit. Trace back to where merchant
  context originates in the conversation session and confirm it's passed
  down at every tool-call site.

---

## VERIFICATION — run these after all 5 fixes, paste actual output

1. `POST /api/v1/payments/create` with no auth header → expect HTTP 401.
2. Authenticate as Merchant B, attempt `PATCH` on a listing owned by
   Merchant A → expect HTTP 403.
3. Upload a CSV with at least one row containing `"$19.99"`, one row with
   `"N/A"` as price, and one row with a missing title → expect HTTP 200
   with `imported_count` for good rows and `errors` listing the bad ones,
   not a 500.
4. Call `semantic_search("test query", merchant_id="merchant-a-id")` after
   seeding a product only under `merchant-b-id` → expect empty/no match.
5. Call the checkout tool twice in a row with an identical cart → expect
   the second call to return the same order/idempotency result, not a
   duplicate order. Then change the cart contents and call again → expect
   a new order to be created.

Report each result as PASS/FAIL with the actual response body, not a
description of expected behavior.
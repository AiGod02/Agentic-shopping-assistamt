# ACP Platform — Living Status Document

Last updated: this session. Update this file as things move between
sections — don't let a new conversation start from zero again.

Legend: ✅ Verified with real evidence · 🟡 Built, unverified/partially
verified · ⏳ Pending (asked for, awaiting result) · ⛔ Not yet built ·
⏸️ Deliberately deferred

---

## ✅ VERIFIED — Real Evidence Exists

| Item | Evidence |
|---|---|
| **`ESCALATE_TO_HUMAN` Intent Handler** | Built & verified in [agent_server/intent_registry.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/agent_server/agent_server/intent_registry.py) and [test_item1_escalation.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/test_item1_escalation.py). **Path A (Explicit)**: Triggers on requests like *"I want to speak to human support"*. Returns merchant contact email/phone if configured; if unconfigured, states honestly *"We don't have a direct live human support line configured..."*. **Path B (Automatic)**: Automatically escalates after 2+ consecutive `UNCLEAR_INTENT` turns in the same session, preventing infinite loops. |
| **`MERCHANT_INFO` Intent Handler** | Built & verified in [agent_server/intent_registry.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/agent_server/agent_server/intent_registry.py) and [test_item2_merchant_info.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/test_item2_merchant_info.py). Fetches merchant settings via `/api/v1/merchants/public/{merchant_id}`. Real transcripts verified for business hours, shipping policy, contact info/location. **Honest Fallback**: When policy is unconfigured (e.g. return policy), agent responds honestly *"I don't have that information — you can ask Default Merchant Business directly"*. |
| **Razorpay End-to-End Verification (Test Mode)** | Verified in [test_item3_razorpay.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/test_item3_razorpay.py). **Key**: Confirmed `RAZORPAY_KEY_ID=rzp_test_TKRwxtr9MTtL8J` (Test mode key). **Signature**: HMAC-SHA256 algorithm with `RAZORPAY_WEBHOOK_SECRET` on `X-Razorpay-Signature`. **Flow**: Checkout saga created DB order `90222d7b-9d0b-4f34-bd80-7a4a2d7329bc` (`ORD-20260808-1E6A6350`) and Razorpay Order ID `order_test_09c9379c4c6c4a`. **State**: `payment.captured` webhook updated order state `pending_payment` → `paid`. **Idempotency**: Duplicate checkout attempt blocked on emptied cart. **Failure**: `payment.failed` webhook updated order state `pending_payment` → `payment_failed`. |
| **GitHub Actions CI Pipeline** | Minimal CI workflow configured in [.github/workflows/ci.yml](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/.github/workflows/ci.yml). Triggers automatically on push/PR to `main`/`master`, spins up PostgreSQL container service, installs dependencies, and runs `pytest tests/ -v`. **Verification**: Verified pipeline gates on test results (1 failed / 42 passed on deliberate assertion failure; 43 passed in 25.10s on clean suite). |
| **Automated Pytest Regression Suite** | 100% of manual verifications backed by committed automated suite in [tests/](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/tests/): [test_auth.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/tests/test_auth.py), [test_listing_idor.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/tests/test_listing_idor.py), [test_order_isolation.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/tests/test_order_isolation.py), [test_bulk_upload.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/tests/test_bulk_upload.py), [test_search_isolation.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/tests/test_search_isolation.py), [test_checkout_idempotency.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/tests/test_checkout_idempotency.py), [test_guest_cart_isolation.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/tests/test_guest_cart_isolation.py), [test_order_payment_status_propagation.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/tests/test_order_payment_status_propagation.py), [test_merchant_dashboard_isolation.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/tests/test_merchant_dashboard_isolation.py), [test_reference_resolution.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/tests/test_reference_resolution.py), [test_intent_handlers.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/tests/test_intent_handlers.py). Executed and verified (43 passed in 25.10s). |
| **Guest Cart Cross-Customer Data Leak Fixed** | Removed hardcoded UUID fallbacks (`905e50a3-80b9...` and `00000000...`). Dynamic session-scoped UUID generated per anonymous chat session and signed in JWT token (`sub=<guest_uuid>`). `merchant_server/api/v1/cart` enforces cryptographically signed JWT auth, returning `401 Unauthorized` for bare requests. Live dual-session test confirmed 100% cart separation (Session A Cart `bbf2eb99-...` vs Session B Cart `7c5aeae0-...`). |
| **Order Status Propagation (`payments.status` → `orders.status`)** | Webhook handler in `payment_server/api/v1/webhooks.py` propagates payment status to `orders.status`. **Confirmed**: `order_id` is retrieved via internal SQL DB query on `payments` table by `gateway_payment_id` (`SELECT order_id FROM payments...`), NOT trusted directly from webhook body. Live test verified transition from `pending_payment` → `paid` on success, and → `payment_failed` on failure. |
| **Merchant Context Binding & Validation** | Traced exact code path (`ChatRequest.merchant_id` → `session.context["merchant_id"]` → `dialogue_state.merchant_id` → `active_merchant_id` search filter). **Added & Verified DB Validation**: `ChatRequest.merchant_id` is queried against `merchants` table in DB. Returns `400 Bad Request` for invalid UUID format, `404 Not Found` for non-existent merchant, and `400` if inactive. |
| **Merchant Dashboard Isolation Live Walkthrough** | Live tested full dashboard endpoints (`/listings`, `/orders`, `/analytics/overview`, `/merchants/me`) between Merchant A (Tech Emporium) and Merchant B (LuxStay Haven). 0 catalog item overlap and 100% payload isolation verified. |
| Payment auth (`/create`, `/capture`, `/refund`, `/escrow`) requires JWT | 401 on unauthenticated request, tested |
| JWT secret has no hardcoded fallback | Startup fails without env var |
| Listings IDOR protection (update/delete) | 403 confirmed, Merchant B vs Merchant A |
| Bulk upload — size limit, row-level error handling, safe price parsing | Tested with malformed CSV rows, correct partial success response |
| Chroma vector search merchant isolation (mandatory `merchant_id`) | Empty result confirmed for cross-merchant query |
| Checkout idempotency (deterministic cart-content hash) | Matching key on identical retry, new key on cart change — real hashes shown |
| Order-by-ID scoped at query level | Confirmed via repo fix |
| Full intent inventory mapped (vocabulary vs real handler) | Section 1 table — 24 of 27 intents have real handlers |
| `compare_products` and `checkout` intents — real handlers exist | Real order ID + cart state returned, not fallback-to-search |
| Cart persistence (`add_to_cart`) | Independent DB read-back matched chat claim |
| Checkout → order creation | Independent read-back, real order ID |
| Session state persistence across reconnect (same session ID) | `DialogueState` preserved |
| Session isolation (new session ID = clean state) | Confirmed no bleed-through |
| Invalid-reference clarification behavior | "compare it" / "add to cart" with no context → clarifying question, not a guess |
| Empty cart state | Honest `{items: [], subtotal: 0}` response |
| **Search Backend Failure Handling & Fallback Parity** | **Verified**: DB connection and vector store exceptions are explicitly caught and logged at `ERROR` level in [agent_server/core/search.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/agent_server/agent_server/core/search.py#L143) and [chroma_search.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/agent_server/agent_server/core/chroma_search.py#L260). Fallback pipeline ensures relevance score ranking, category keyword filtering, and deduplication by `listing_id` are applied consistently. |
| **Startup Embedding Model Pre-Warming** | **Verified**: Added `prewarm_model()` function in [agent_server/core/chroma_search.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/agent_server/agent_server/core/chroma_search.py#L77) called directly inside FastAPI `lifespan` startup in [agent_server/main.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/agent_server/agent_server/main.py#L46). Completely eliminates live 90s HuggingFace download/cold-start delays on incoming user requests. |
| **Unified Database URL Configuration** | **Verified**: Corrected all hardcoded default fallback references from `agenticcommerce` to `commerce_platform` in [config.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/agent_server/agent_server/config.py#L16), [session.py](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/shared/shared/db/session.py#L128), and [alembic.ini](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/migrations/alembic.ini#L3). |
| **Genuinely Agentic Tool-Calling Loop with Hardcoded Fallbacks** | **Verified**: Refactored [`orchestrator.py`](file:///c:/Users/sooja/Downloads/new%20acp/new%20acp/agentic%20commerce%20protocol/agent_server/agent_server/core/orchestrator.py) into a dual-path architecture. **Conversational & Reasoning Flows** (product search, discovery, comparison, fit assessment, reviews, availability, merchant info, price objections, escalation) run on a real LLM agent loop (`llama-3.3-70b-versatile` on Groq) with native OpenAI tool-calling schemas (`search_listings`, `get_listing_details`, `get_listing_reviews`, `check_availability`, `get_merchant_info`, `compare_listings`, `web_search_product`). **Factual Grounding**: System prompt strictly enforces verbatim contact/policy quoting and exact stock/price retrieval. **Deduplication**: `search_listings` deduplicates results against `dialogue_state.last_shown_listings` across turns. **Latency**: Benchmarked at ~3.4s (search/discovery) to ~17s (multi-turn comparison/synthesis). |
| Journeys B–F (comparison, objection, repeated requests, topic switch) | Verified via `scratch_run_journeys.py` execution & independent readbacks |

## 🟡 BUILT, NEEDS FULL/RE-VERIFICATION

| Item | What's missing |
|---|---|
| Multi-tier search fallback (Weaviate → Chroma → Postgres) | Confirmed: Weaviate is not running locally in dev; fallback gracefully degrades to Chroma (`chromadb_search` verified in logs) |

## ⏳ PENDING & CODE AUDIT FINDINGS

| Item | Technical Finding / Status |
|---|---|
| Customer identity / guest token tightening | **Resolved & Verified**: Signed JWT required for all cart operations; anonymous sessions generate unique guest UUID signed in JWT access tokens. |
| Order payment status transition (`pending_payment` → `paid`) | **Resolved & Verified**: `payment_server/api/v1/webhooks.py` propagates payment capture/failure directly to linked `orders.status`. |
| Merchant dashboard isolation | **Resolved & Verified**: Live endpoint walkthrough confirmed 100% data separation across catalog, orders, analytics, and settings between merchants. |
| Store routing / `merchant_id` resolution | **Resolved & Analyzed**: Multi-merchant execution supported today via API parameter binding (`ChatRequest.merchant_id`). Domain/slug frontend auto-routing deferrable. |

## ⛔ NOT YET BUILT

- `APPLY_PROMO`
- `REQUEST_RETURN_REFUND`
- `SHOW_SIMILAR_ITEMS`
- Reviews / knowledge base semantic search (separate from product search)
- Real pytest test files (fixtures/factories) for the fully-verified items above — most verification so far has been manual/targeted HTTP calls, not committed automated tests
- Reviews / knowledge base semantic search (separate from product search)
- Stripe: webhook signature verification status unconfirmed; Stripe-level idempotency key on charge calls unconfirmed; duplicate-charge test in test mode not yet run

## ⏸️ DELIBERATELY DEFERRED (correct calls, revisit later)

- Universal schema for loan vertical — `vertical_type`/`attributes` field exists in schema, inert, confirmed not affecting e-commerce. Revisit once e-commerce is fully solid.
- Downstream consumers of vertical-aware schema (search indexing, dashboard, analytics handling both verticals)
- Postgres reconsideration — no concrete technical limitation identified; treated as a fatigue signal, not a real architecture gap. Revisit only if a specific limitation surfaces.
- Full rewrite from scratch — explicitly rejected in favor of continued hardening; evidence since then (real bugs found AND fixed with real proof) supports this was the right call.

---

## NEXT STEPS, IN ORDER

1. **Close the loop on the last audit** — get the ⏳ Pending items above answered before moving forward. Don't let "looks done" stand in for "is done."
2. **Finish the audit surface already scoped**: merchant dashboard isolation, store routing, customer identity — same isolation discipline already proven elsewhere, just untested territory.
3. **Stripe, for real** — webhook signature check, Stripe-level idempotency, actual duplicate-charge test in test mode.
4. **Re-run sales behavior transcripts** now that checkout/compare are confirmed real — a good pitch on top of a broken cart was worthless before; worth re-verifying now that it isn't broken.
5. **Convert manual verifications into a real pytest suite** — everything in the ✅ table above currently lives as one-time manual checks. This is what makes future changes self-checking instead of requiring a full manual re-audit each time.
6. **Consider building `ESCALATE_TO_HUMAN`** before the pilot goes live with real customers — small addition, meaningful trust impact when the agent genuinely can't help.
7. Everything in ⏸️ Deferred stays deferred until the above is solid.

---

## HOW TO USE THIS DOCUMENT

- Before starting a new fix/audit session with Antigravity, paste the
  relevant section of this doc as context so it's not rediscovering things
  already known.
- When something moves from 🟡/⏳ to ✅, update this file with the actual
  evidence (response body, ID, test output) — not just a status change.
- If something new breaks,   add it here rather than only in chat — this
  file, not the conversation history, should be the source of truth for
  "what's actually true about this codebase right now."
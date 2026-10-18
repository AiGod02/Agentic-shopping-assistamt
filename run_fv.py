"""
Full Functional Verification — hits live servers via HTTP.
Covers all 6 sections from functional_verification.md.
"""

import asyncio
import httpx
import json
import uuid
import time

AGENT_URL  = "http://127.0.0.1:8001"
MERCHANT_URL = "http://127.0.0.1:8002"

RESULTS = []

# -----------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------

def banner(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)

def sub(title):
    print(f"\n-- {title} --")

async def login(client) -> str:
    r = await client.post(f"{MERCHANT_URL}/api/v1/merchants/login",
                          json={"email": "customer@example.com", "password": "password"})
    if r.status_code == 200:
        return r.json()["access_token"]
    r = await client.post(f"{MERCHANT_URL}/api/v1/merchants/login",
                          json={"email": "admin@example.com", "password": "password"})
    if r.status_code == 200:
        return r.json()["access_token"]
    raise RuntimeError(f"Login failed: {r.status_code} {r.text[:200]}")

async def chat(client, token, session_id, message, merchant_id=None):
    body = {"session_id": session_id, "message": message}
    if merchant_id:
        body["merchant_id"] = merchant_id
    r = await client.post(
        f"{AGENT_URL}/api/v1/agent/chat",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )
    if r.status_code != 200:
        return {"response": f"[HTTP {r.status_code}] {r.text[:300]}", "tool_calls": []}
    return r.json()

def show_turn(label, msg, result):
    print(f"\n  [{label}] USER: {msg!r}")
    print(f"  [{label}] AGENT: {result.get('response', '')[:400]}")
    calls = result.get("tool_calls", [])
    if calls:
        print(f"  [{label}] TOOLS: {[t.get('tool') for t in calls]}")

async def direct_get(client, token, path):
    r = await client.get(f"{MERCHANT_URL}{path}",
                         headers={"Authorization": f"Bearer {token}"})
    if r.status_code == 200:
        return r.json()
    return {"error": r.status_code, "body": r.text[:200]}

# -----------------------------------------------------------------
# SECTION 1 - Intent Inventory
# -----------------------------------------------------------------

INTENT_TABLE = {
    "SEARCH_PRODUCTS":        (True,  "orchestrator.py L566 -> commerce_tools.py::search_listings", False),
    "BROWSE_CATEGORY":        (True,  "orchestrator.py L566 -> commerce_tools.py::search_listings", False),
    "FILTER_REFINE":          (True,  "orchestrator.py L566 -> commerce_tools.py::search_listings", False),
    "SHOW_MORE_RESULTS":      (True,  "orchestrator.py L363 - re-searches excluding prior results", False),
    "SHOW_SIMILAR_ITEMS":     (False, "NO DEDICATED HANDLER - falls to generic search fallback", True),
    "GET_PRODUCT_DETAILS":    (True,  "orchestrator.py L402 -> commerce_tools.py::get_listing_details", False),
    "GET_REVIEWS":            (True,  "orchestrator.py L382 -> commerce_tools.py::get_listing_reviews", False),
    "CHECK_AVAILABILITY":     (True,  "commerce_tools.py::check_availability exists BUT no orchestrator branch -> fallback", True),
    "GET_PRICE":              (False, "No dedicated branch -> falls to generic search fallback", True),
    "COMPARE_PRODUCTS":       (True,  "orchestrator.py L446 -> get_listing_details per ID", False),
    "STATE_PREFERENCE":       (True,  "orchestrator.py L566 branch -> commerce_tools.py::remember_user_preference", False),
    "ANSWER_CLARIFICATION":   (False, "No dedicated handler -> generic fallback", True),
    "REJECT_OPTION":          (False, "No dedicated handler -> generic fallback", True),
    "ADD_TO_CART":            (True,  "orchestrator.py L485 -> commerce_tools.py::add_to_cart", False),
    "REMOVE_FROM_CART":       (True,  "commerce_tools.py::remove_from_cart EXISTS but NO orchestrator branch -> generic fallback!", True),
    "VIEW_CART":              (True,  "commerce_tools.py::view_cart EXISTS but NO orchestrator branch -> generic fallback!", True),
    "MODIFY_CART_QUANTITY":   (False, "No dedicated handler -> generic fallback", True),
    "CHECKOUT":               (True,  "orchestrator.py L523 -> commerce_tools.py::checkout", False),
    "APPLY_PROMO":            (False, "NOT BUILT - no handler anywhere", False),
    "TRACK_ORDER":            (True,  "orchestrator.py (track section) -> commerce_tools.py::list_orders/get_order_status", False),
    "ORDER_HISTORY":          (True,  "commerce_tools.py::list_orders EXISTS but no dedicated orchestrator branch", True),
    "CANCEL_ORDER":           (True,  "commerce_tools.py::cancel_order EXISTS but no dedicated orchestrator branch", True),
    "REQUEST_RETURN_REFUND":  (False, "NOT BUILT - no handler", False),
    "MERCHANT_INFO":          (True,  "orchestrator.py L289 -> commerce_tools.py::get_merchant_info", False),
    "ESCALATE_TO_HUMAN":      (True,  "orchestrator.py L247 - fetches merchant contact info", False),
    "GREETING":               (True,  "orchestrator.py - LLM generic response path", False),
    "CHITCHAT_OUT_OF_SCOPE":  (True,  "orchestrator.py - consecutive_unclear_turns counter", False),
    "UNCLEAR_INTENT":         (True,  "orchestrator.py - clarifying question fallback", False),
}

def section1():
    banner("SECTION 1 - INTENT INVENTORY: VOCABULARY vs REAL HANDLER")
    print(f"\n{'Intent':<28} {'Handler?':<10} {'Falls to search?':<18} Location")
    print("-" * 110)
    not_built = []
    falls_back = []
    for intent, (exists, location, fallback) in INTENT_TABLE.items():
        h = "YES" if exists else "NO"
        fb = "YES (BROKEN)" if fallback else "no"
        flag = "!!" if fallback else ""
        print(f"{intent:<28} {h:<10} {fb:<18} {location}")
        if not exists:
            not_built.append(intent)
        if fallback:
            falls_back.append(intent)

    print(f"\n--- NOT YET BUILT ({len(not_built)}) ---")
    for i in not_built:
        print(f"  * {i}")
    print(f"\n--- FALLS BACK TO SEARCH/GENERIC = BROKEN BY SPEC ({len(falls_back)}) ---")
    for i in falls_back:
        print(f"  * {i}")

# -----------------------------------------------------------------
# SECTION 2 - Per-Intent Tests
# -----------------------------------------------------------------

async def section2(client, token):
    banner("SECTION 2 - PER-INTENT FUNCTIONAL TESTS")

    sub("SEARCH_PRODUCTS happy path")
    sid = str(uuid.uuid4())
    r = await chat(client, token, sid, "show me laptops")
    show_turn("SEARCH", "show me laptops", r)
    tools = [t["tool"] for t in r.get("tool_calls", [])]
    print(f"  RESULT: {'PASS - search_listings fired' if 'search_listings' in tools else 'FAIL - expected search_listings, got: ' + str(tools)}")

    sub("GET_PRODUCT_DETAILS - after context (tell me more)")
    sid = str(uuid.uuid4())
    await chat(client, token, sid, "show me laptops")
    r = await chat(client, token, sid, "tell me more about it")
    show_turn("DETAILS", "tell me more about it", r)
    tools = [t["tool"] for t in r.get("tool_calls", [])]
    print(f"  RESULT: {'PASS - get_listing_details fired' if 'get_listing_details' in tools else 'FAIL/WARN - tools: ' + str(tools)}")

    sub("GET_REVIEWS - after context")
    sid = str(uuid.uuid4())
    await chat(client, token, sid, "show me MacBook")
    r = await chat(client, token, sid, "what do reviews say")
    show_turn("REVIEWS", "what do reviews say", r)
    tools = [t["tool"] for t in r.get("tool_calls", [])]
    print(f"  RESULT: {'PASS - get_listing_reviews fired' if 'get_listing_reviews' in tools else 'FAIL/WARN - tools: ' + str(tools)}")

    sub("GET_REVIEWS - COLD SESSION (must ask clarification, not guess)")
    sid = str(uuid.uuid4())
    r = await chat(client, token, sid, "tell me about reviews")
    show_turn("REVIEWS COLD", "tell me about reviews", r)
    resp = r.get("response", "").lower()
    clarified = any(w in resp for w in ["which product", "search", "what product", "which item", "first"])
    print(f"  RESULT: {'PASS - asked clarification' if clarified else 'FAIL - did not clarify: ' + resp[:150]}")

    sub("ADD_TO_CART - happy path")
    sid = str(uuid.uuid4())
    await chat(client, token, sid, "show me laptops")
    r = await chat(client, token, sid, "add it to cart")
    show_turn("ADD_CART", "add it to cart", r)
    tools = [t["tool"] for t in r.get("tool_calls", [])]
    print(f"  RESULT: {'PASS - add_to_cart fired' if 'add_to_cart' in tools else 'FAIL - tools: ' + str(tools)}")

    sub("ADD_TO_CART - cold session (no product context - must not fire blindly)")
    sid = str(uuid.uuid4())
    r = await chat(client, token, sid, "add it to cart")
    show_turn("ADD_CART COLD", "add it to cart [cold]", r)
    tools = [t["tool"] for t in r.get("tool_calls", [])]
    print(f"  RESULT: {'PASS - did not blindly add' if 'add_to_cart' not in tools else 'FAIL - fired add_to_cart with no context!'}")

    sub("VIEW_CART - orchestrator branch check")
    sid = str(uuid.uuid4())
    r = await chat(client, token, sid, "show my cart")
    show_turn("VIEW_CART", "show my cart", r)
    tools = [t["tool"] for t in r.get("tool_calls", [])]
    print(f"  RESULT: {'PASS - view_cart fired' if 'view_cart' in tools else 'FAIL - view_cart NOT fired. Tools: ' + str(tools)}")

    sub("REMOVE_FROM_CART - orchestrator branch check")
    sid = str(uuid.uuid4())
    await chat(client, token, sid, "show me laptops")
    await chat(client, token, sid, "add it to cart")
    r = await chat(client, token, sid, "remove it from cart")
    show_turn("REMOVE_CART", "remove it from cart", r)
    tools = [t["tool"] for t in r.get("tool_calls", [])]
    print(f"  RESULT: {'PASS - remove_from_cart fired' if 'remove_from_cart' in tools else 'FAIL - remove_from_cart NOT fired. Tools: ' + str(tools)}")

    sub("CHECKOUT - happy path")
    sid = str(uuid.uuid4())
    await chat(client, token, sid, "show me laptops")
    await chat(client, token, sid, "add it to cart")
    r = await chat(client, token, sid, "checkout")
    show_turn("CHECKOUT", "checkout", r)
    tools = [t["tool"] for t in r.get("tool_calls", [])]
    print(f"  RESULT: {'PASS - checkout fired' if 'checkout' in tools else 'FAIL - tools: ' + str(tools)}")

    sub("ESCALATE_TO_HUMAN - 2 consecutive unclear turns")
    sid = str(uuid.uuid4())
    await chat(client, token, sid, "xyzabc qwerty noop 11223344")
    r = await chat(client, token, sid, "blorp grazzle noop 998877")
    show_turn("ESCALATE", "2nd unclear msg", r)
    resp = r.get("response", "").lower()
    escalated = any(w in resp for w in ["support", "team", "contact", "human", "reach", "email", "phone"])
    print(f"  RESULT: {'PASS - escalated to human' if escalated else 'FAIL - did not escalate: ' + resp[:150]}")

    sub("COMPARE_PRODUCTS - compare first two")
    sid = str(uuid.uuid4())
    await chat(client, token, sid, "show me laptops")
    r = await chat(client, token, sid, "compare the first two")
    show_turn("COMPARE", "compare the first two", r)
    tools = [t["tool"] for t in r.get("tool_calls", [])]
    activated = "compare_products" in tools or "get_listing_details" in tools
    print(f"  RESULT: {'PASS - comparison logic activated. tools: ' + str(tools) if activated else 'FAIL - tools: ' + str(tools)}")


# -----------------------------------------------------------------
# SECTION 3 - Persistence Read-Back
# -----------------------------------------------------------------

async def section3(client, token):
    banner("SECTION 3 - PERSISTENCE READ-BACK")

    sub("add_to_cart -> direct GET /cart verify")
    sid = str(uuid.uuid4())
    await chat(client, token, sid, "show me laptops")
    r_add = await chat(client, token, sid, "add it to cart")
    show_turn("S3", "add it to cart", r_add)
    cart = await direct_get(client, token, "/api/v1/cart")
    items = cart.get("items", [])
    print(f"  Direct /cart: {len(items)} items")
    print(f"  RESULT: {'PASS - write confirmed' if items else 'FAIL - cart empty after add!'}")

    sub("remove_from_cart -> direct GET /cart verify")
    if items:
        r_rm = await chat(client, token, sid, "remove it from cart")
        show_turn("S3", "remove it from cart", r_rm)
        cart_after = await direct_get(client, token, "/api/v1/cart")
        items_after = cart_after.get("items", [])
        print(f"  Direct /cart after remove: {len(items_after)} items")
        print(f"  RESULT: {'PASS - remove confirmed' if len(items_after) < len(items) else 'FAIL - still ' + str(len(items_after)) + ' items'}")
    else:
        print("  SKIPPED (no items)")

    sub("checkout -> direct GET /orders verify")
    sid2 = str(uuid.uuid4())
    await chat(client, token, sid2, "show me laptops")
    await chat(client, token, sid2, "add it to cart")
    r_co = await chat(client, token, sid2, "checkout")
    show_turn("S3", "checkout", r_co)
    orders = await direct_get(client, token, "/api/v1/orders")
    order_list = orders.get("items", orders.get("orders", orders if isinstance(orders, list) else []))
    if isinstance(order_list, list) and order_list:
        latest = order_list[0] if isinstance(order_list[0], dict) else {}
        print(f"  Direct /orders: found {len(order_list)} orders. Latest: id={latest.get('id')} status={latest.get('status')}")
        print(f"  RESULT: PASS - order write confirmed")
    else:
        print(f"  RESULT: FAIL - no orders in DB. Response: {str(orders)[:200]}")

    sub("Dialogue state survives reconnect (same session_id)")
    sid3 = str(uuid.uuid4())
    await chat(client, token, sid3, "show me MacBook")
    r_r = await chat(client, token, sid3, "tell me more about it")
    show_turn("S3 RECONNECT", "tell me more about it", r_r)
    tools_r = [t["tool"] for t in r_r.get("tool_calls", [])]
    if "get_listing_details" in tools_r:
        print("  RESULT: PASS - context survived reconnect")
    elif "search_listings" in tools_r:
        print("  RESULT: FAIL - state LOST, fell back to search_listings")
    else:
        print(f"  RESULT: WARN - tools={tools_r}, response: {r_r.get('response','')[:200]}")


# -----------------------------------------------------------------
# SECTION 4 - Multi-Turn Journeys
# -----------------------------------------------------------------

async def section4(client, token):
    banner("SECTION 4 - MULTI-TURN REALISTIC JOURNEYS")

    sub("Journey A - Full purchase, no detours")
    sid = str(uuid.uuid4())
    for msg in ["hi, looking for a laptop", "tell me more about it",
                "what do reviews say", "add it to cart", "checkout", "track my order"]:
        r = await chat(client, token, sid, msg)
        show_turn("A", msg, r)
        await asyncio.sleep(0.3)
    cart_a = await direct_get(client, token, "/api/v1/cart")
    orders_a = await direct_get(client, token, "/api/v1/orders")
    order_list_a = orders_a.get("items", orders_a.get("orders", []))
    print(f"\n  [A] Direct cart: {len(cart_a.get('items', []))} items")
    print(f"  [A] Direct orders: {len(order_list_a) if isinstance(order_list_a, list) else '?'} orders")

    sub("Journey B - Comparison and indecision")
    sid = str(uuid.uuid4())
    for msg in ["show me laptops", "compare it with something cheaper",
                "actually show me something else instead", "never mind, add the first one to cart"]:
        r = await chat(client, token, sid, msg)
        show_turn("B", msg, r)
        await asyncio.sleep(0.3)

    sub("Journey C - Objection and recovery")
    sid = str(uuid.uuid4())
    for msg in ["show me a MacBook", "that's too expensive",
                "okay fine, add it anyway", "wait, remove it, I changed my mind"]:
        r = await chat(client, token, sid, msg)
        show_turn("C", msg, r)
        await asyncio.sleep(0.3)
    cart_c = await direct_get(client, token, "/api/v1/cart")
    items_c = cart_c.get("items", [])
    print(f"\n  [C] Cart after remove - direct: {len(items_c)} items (expect 0)")

    sub("Journey D - Ambiguous references cold session")
    sid = str(uuid.uuid4())
    r_d1 = await chat(client, token, sid, "tell me about reviews")
    show_turn("D", "tell me about reviews [COLD]", r_d1)
    resp_d1 = r_d1.get("response", "").lower()
    clarified = any(w in resp_d1 for w in ["which", "search", "product", "first", "what item"])
    print(f"  RESULT: {'PASS - clarification asked' if clarified else 'FAIL - no clarification: ' + resp_d1[:150]}")

    sid2 = str(uuid.uuid4())
    r_d2 = await chat(client, token, sid2, "the second one")
    show_turn("D", "the second one [COLD]", r_d2)
    tools_d2 = [t["tool"] for t in r_d2.get("tool_calls", [])]
    blind = "add_to_cart" in tools_d2 or "get_listing_details" in tools_d2
    print(f"  RESULT: {'FAIL - blindly resolved ordinal with no context! tools=' + str(tools_d2) if blind else 'PASS - did not blindly resolve'}")

    sub("Journey E - Repeated requests (idempotency)")
    sid = str(uuid.uuid4())
    for msg in ["show me laptops", "show me laptops", "add it to cart", "add it to cart"]:
        r = await chat(client, token, sid, msg)
        show_turn("E", msg, r)
        await asyncio.sleep(0.3)
    cart_e = await direct_get(client, token, "/api/v1/cart")
    items_e = cart_e.get("items", [])
    print(f"\n  [E] Cart after 2x add: {len(items_e)} items")
    for item in items_e:
        print(f"      listing_id={item.get('listing_id')} qty={item.get('quantity')}")

    sub("Journey F - Mid-conversation topic switch")
    sid = str(uuid.uuid4())
    r_f1 = await chat(client, token, sid, "show me laptops")
    r_f2 = await chat(client, token, sid, "actually, do you have any monitors")
    show_turn("F", "show me laptops", r_f1)
    show_turn("F", "actually, do you have any monitors", r_f2)
    tools_f2 = [t["tool"] for t in r_f2.get("tool_calls", [])]
    print(f"  Tools on switch: {tools_f2}")
    print(f"  RESULT: {'PASS - new search triggered' if 'search_listings' in tools_f2 else 'FAIL - no new search: response=' + r_f2.get('response','')[:150]}")


# -----------------------------------------------------------------
# SECTION 5 - Failure Injection
# -----------------------------------------------------------------

async def section5(client, token):
    banner("SECTION 5 - FAILURE INJECTION")

    sub("5.1 - Nonsense query (search graceful degradation)")
    sid = str(uuid.uuid4())
    r = await chat(client, token, sid, "show me zzzznonexistent9999xyz products")
    show_turn("5.1", "nonsense search", r)
    print(f"  RESULT: {'PASS - did not crash, responded gracefully' if r.get('response') else 'FAIL'}")

    sub("5.2 - Checkout with empty cart (error handling)")
    sid2 = str(uuid.uuid4())
    r2 = await chat(client, token, sid2, "checkout")
    show_turn("5.2", "checkout [EMPTY CART]", r2)
    resp2 = r2.get("response", "").lower()
    empty_handled = "empty" in resp2 or "nothing" in resp2 or "no items" in resp2 or "add" in resp2
    print(f"  RESULT: {'PASS - empty cart handled' if empty_handled else 'FAIL - unexpected: ' + resp2[:150]}")

    sub("5.3 - Agent health after stress")
    r3 = await client.get(f"{AGENT_URL}/health")
    print(f"  Agent /health: {r3.status_code} {r3.json()}")
    print(f"  RESULT: {'PASS - still healthy' if r3.status_code == 200 else 'FAIL - unhealthy!'}")


# -----------------------------------------------------------------
# SECTION 6 - Cross-Session
# -----------------------------------------------------------------

async def section6(client, token):
    banner("SECTION 6 - CROSS-SESSION AND RECONNECT")

    sub("6.1 - Same session_id preserves state across requests")
    sid = str(uuid.uuid4())
    await chat(client, token, sid, "show me laptops")
    await asyncio.sleep(0.5)
    r2 = await chat(client, token, sid, "tell me more about the first one")
    show_turn("6.1", "tell me more about the first one", r2)
    tools2 = [t["tool"] for t in r2.get("tool_calls", [])]
    if "get_listing_details" in tools2:
        print("  RESULT: PASS - context persisted across requests")
    elif "search_listings" in tools2:
        print("  RESULT: FAIL - state LOST, fell back to search_listings")
    else:
        print(f"  RESULT: WARN - tools={tools2}, resp={r2.get('response','')[:200]}")

    sub("6.2 - Fresh session_id starts clean")
    new_sid = str(uuid.uuid4())
    r3 = await chat(client, token, new_sid, "tell me about reviews")
    show_turn("6.2", "tell me about reviews [new session]", r3)
    resp3 = r3.get("response", "").lower()
    clean = any(w in resp3 for w in ["which", "search", "product", "first", "what item"])
    print(f"  RESULT: {'PASS - new session is clean' if clean else 'FAIL/WARN - unexpected response: ' + resp3[:150]}")


# -----------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------

async def main():
    print("=" * 70)
    print("ACP FULL FUNCTIONAL VERIFICATION")
    print("=" * 70)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            ah = await client.get(f"{AGENT_URL}/health")
            mh = await client.get(f"{MERCHANT_URL}/health")
            print(f"Agent server:    {ah.status_code} -> {ah.json()}")
            print(f"Merchant server: {mh.status_code} -> {mh.json()}")
        except Exception as e:
            print(f"FATAL: Server unreachable: {e}")
            return

        try:
            token = await login(client)
            print(f"Auth: JWT obtained successfully")
        except Exception as e:
            print(f"FATAL: Login failed: {e}")
            return

        section1()
        await section2(client, token)
        await section3(client, token)
        await section4(client, token)
        await section5(client, token)
        await section6(client, token)

        banner("VERIFICATION COMPLETE")

if __name__ == "__main__":
    asyncio.run(main())

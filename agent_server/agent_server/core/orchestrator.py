"""
Agent Orchestrator — integrated with DialogueState, FunnelStage transitions, Sales Persona system prompting, and Agentic Tool Calling.
"""

from __future__ import annotations

import json
import re
from typing import Any

from agent_server.config import settings
from agent_server.core.dialogue_state import DialogueState, FunnelStage
from agent_server.core.intent_classifier import IntentClassifier
from agent_server.core.llm_router import LLMMessage, LLMRouter
from agent_server.core.nlu import QueryExtractor
from agent_server.core.reference_resolver import ReferenceResolver
from agent_server.core.session_manager import SessionManager
from agent_server.core.tool_registry import tool_registry
from shared.observability.logging import get_logger
from shared.observability.request_context import trace_log

logger = get_logger(__name__)

_query_extractor = QueryExtractor()
_reference_resolver = ReferenceResolver()

# Transactional intents: tools are executed deterministically (real API calls),
# but the LLM formats the response naturally instead of using canned templates.
TRANSACTIONAL_INTENTS = {
    "ADD_TO_CART",
    "REMOVE_FROM_CART",
    "VIEW_CART",
    "CHECKOUT",
    "ORDER_HISTORY",
    "CANCEL_ORDER",
    "TRACK_ORDER",
}
# Backward compatibility alias
DETERMINISTIC_INTENTS = TRANSACTIONAL_INTENTS


def update_funnel_stage(user_message: str, intent: str, state: DialogueState) -> None:
    """State transition logic for FunnelStage based on user intent and message content."""
    msg = user_message.lower().strip()

    if intent == "OBJECTION":
        state.stage = FunnelStage.OBJECTION
        state.stage_confidence = 0.9
        return

    # Direct intent mapping
    if intent in ("ADD_TO_CART", "CHECKOUT", "MODIFY_CART_QUANTITY"):
        state.stage = FunnelStage.READY_TO_BUY
        state.stage_confidence = 0.95
        return

    if intent in ("TRACK_ORDER", "ORDER_HISTORY", "CANCEL_ORDER", "REQUEST_RETURN_REFUND"):
        state.stage = FunnelStage.POST_PURCHASE
        state.stage_confidence = 0.95
        return

    if intent in ("GET_PRODUCT_DETAILS", "GET_REVIEWS", "COMPARE_PRODUCTS", "CHECK_AVAILABILITY"):
        state.stage = FunnelStage.EVALUATING
        state.stage_confidence = 0.85
        return

    if intent in ("SEARCH_PRODUCTS", "BROWSE_CATEGORY", "FILTER_REFINE", "SHOW_MORE_RESULTS"):
        has_specifics = bool(re.search(r"\b(?:budget|\$|\d+|gaming|work|portable|fast|i7|m3|pro|max|inch|oled|qled)\b", msg))
        if has_specifics:
            # User gave concrete constraints — skip discovery, go straight to browsing/search
            state.stage = FunnelStage.BROWSING
            state.stage_confidence = 0.85
        elif state.stage == FunnelStage.GREETING or len(msg.split()) <= 4:
            state.stage = FunnelStage.DISCOVERY
            state.stage_confidence = 0.8
        else:
            state.stage = FunnelStage.BROWSING
            state.stage_confidence = 0.85
        return

    if intent == "GREETING":
        state.stage = FunnelStage.GREETING
        state.stage_confidence = 1.0
        return


def build_sales_system_prompt(state: DialogueState) -> str:
    """Builds dynamic system prompt with sales persona, objection handling, stage calibration, and strict grounding rules."""
    base_prompt = (
        "You are an expert, genuinely helpful sales assistant for an e-commerce platform.\n"
        "Your goal is to guide the customer toward making a great purchasing decision with natural, helpful, non-pushy sales guidance.\n\n"
        "CORE SALESMAN RULES:\n"
        "1. Discovery-first: If the user query is broad or ambiguous, ask 1-2 focused qualifying questions before running a listing dump.\n"
        "2. Recommend with reasoning: Lead with clear recommendations based on retrieved product data and state clear trade-offs.\n"
        "3. End each response with a natural next step relevant to the conversation context. Vary your suggestions across turns — don't repeat the same closing question.\n"
        "4. Absolute Honesty: NEVER fabricate fake urgency (e.g., 'Only 1 left!'). If a product doesn't fit the user's stated needs (e.g. asking for a portable coding device and getting a large TV), state honestly why it is unsuitable and suggest a better alternative.\n"
        "5. Post-decision upsell: Only suggest relevant accessories AFTER an item is chosen or added to cart.\n\n"
        "STRICT FACTUAL GROUNDING RULES (MANDATORY):\n"
        "6. Quote Verbatim: Phone numbers, emails, support contact details, business hours, and policy strings returned by tools (e.g. 'get_merchant_info') MUST be quoted verbatim from the tool results. Never invent, alter, or paraphrase phone numbers or policies.\n"
        "7. Exact Prices & Stock: Availability booleans (available: true/false), stock, prices, and ratings MUST match retrieved tool payloads exactly. Do NOT hallucinate prices or inventory numbers.\n"
        "8. Tool Grounding: State facts ONLY from actual tool execution results. If a piece of information was not returned by a tool, state honestly that it is unavailable.\n"
        "9. Search Loop Prevention: If search_listings returns results, present them to the user immediately. Do NOT call search_listings again with a rephrased query hoping for different results — the catalog is the catalog. If no results match perfectly, present the closest matches and explain the difference honestly.\n\n"
    )

    stage_calibration = f"CURRENT FUNNEL STAGE: {state.stage.value.upper()}\n"
    if state.stage == FunnelStage.GREETING or state.stage == FunnelStage.DISCOVERY:
        stage_calibration += (
            "Tone: Warm, curious, welcoming.\n"
            "Action: Ask 1-2 focused qualifying questions to understand budget, use case, or preferences before showing products.\n"
        )
    elif state.stage == FunnelStage.BROWSING:
        stage_calibration += (
            "Tone: Informative, structured, helpful.\n"
            "Action: Call search_listings with the user's constraints (query, price range, type, etc.) to retrieve real products. "
            "Then present top 2-3 choices clearly with brief reasons for each. Highlight key tradeoffs.\n"
        )
    elif state.stage == FunnelStage.EVALUATING:
        stage_calibration += (
            "Tone: Objective, detailed, comparative, patient.\n"
            "Action: Highlight key features, ratings/reviews, and help them evaluate fit against their needs.\n"
        )
    elif state.stage == FunnelStage.OBJECTION:
        stage_calibration += (
            "Tone: Empathetic, direct, reassuring.\n"
            "Action: Address their concern directly. If price is an issue, offer a high-value lower-cost alternative or justify the value. If fit/trust, share verified customer feedback.\n"
        )
    elif state.stage == FunnelStage.READY_TO_BUY:
        stage_calibration += (
            "Tone: Efficient, frictionless, clear.\n"
            "Action: Confirm product details, remove any final friction, and offer a clean next step to add to cart or checkout.\n"
        )
    elif state.stage == FunnelStage.POST_PURCHASE:
        stage_calibration += (
            "Tone: Supportive, reassuring.\n"
            "Action: Provide order details, tracking status, and assist with any post-purchase needs.\n"
        )

    if state.known_preferences:
        stage_calibration += f"\nStated User Preferences: {json.dumps(state.known_preferences)}\n"

    return base_prompt + stage_calibration


class AgentOrchestrator:
    """Orchestrates the agent loop using DialogueState, ReferenceResolver, and Sales Persona."""

    def __init__(
        self,
        session_manager: SessionManager,
        llm_provider: str | None = None,
    ) -> None:
        self.session_manager = session_manager
        self.llm = LLMRouter(llm_provider)
        self.intent_classifier = IntentClassifier(self.llm)
        self.max_iterations = settings.max_tool_calls_per_turn

        from agent_server.tools.commerce_tools import register_all_tools

        register_all_tools()

    async def _run_agent_loop(
        self,
        session_id: str,
        user_message: str,
        dialogue_state: DialogueState,
        conversation_history: list[dict],
        user_token: str = "",
        reference_hints: str = "",
    ) -> dict[str, Any]:
        """Runs the multi-turn LLM agentic tool-calling loop for conversational & reasoning flows."""
        tool_names = [
            "search_listings",
            "get_listing_details",
            "get_listing_reviews",
            "check_availability",
            "get_merchant_info",
            "compare_listings",
            "compare_products",
            "web_search_product",
        ]
        tools = []
        for name in tool_names:
            t = tool_registry.get(name)
            if t:
                tools.append(t.to_openai_schema())

        system_prompt = build_sales_system_prompt(dialogue_state)

        ctx_parts = []
        if dialogue_state.merchant_id:
            ctx_parts.append(f"active_merchant_id: {dialogue_state.merchant_id}")
        if dialogue_state.focused_listing_id:
            ctx_parts.append(f"focused_listing_id: {dialogue_state.focused_listing_id}")
        if dialogue_state.focused_listing_data:
            ctx_parts.append(f"focused_listing_data: {json.dumps(dialogue_state.focused_listing_data)}")
        if dialogue_state.last_shown_listings:
            ctx_parts.append(f"last_shown_listings_count: {len(dialogue_state.last_shown_listings)}")
            ctx_parts.append(
                f"last_shown_ids: {[p.get('id') for p in dialogue_state.last_shown_listings if isinstance(p, dict)]}"
            )
        if dialogue_state.consecutive_unclear_turns > 0:
            ctx_parts.append(f"consecutive_unclear_turns: {dialogue_state.consecutive_unclear_turns}")
        if reference_hints:
            ctx_parts.append(f"REFERENCE HINTS (advisory, not binding): {reference_hints}")

        if ctx_parts:
            system_prompt += "\nCURRENT DIALOGUE STATE CONTEXT:\n" + "\n".join(ctx_parts)

        messages = [LLMMessage(role="system", content=system_prompt)]

        for m in conversation_history[-6:]:
            r = m.get("role", "user")
            if r in ("user", "assistant", "system"):
                messages.append(LLMMessage(role=r, content=m.get("content", "")))

        messages.append(LLMMessage(role="user", content=user_message))

        executed_tool_calls: list[dict[str, Any]] = []
        final_text: str = ""

        for iteration in range(self.max_iterations):
            logger.info("agent_loop_turn", session_id=session_id, iteration=iteration)
            res = await self.llm.complete(messages, tools=tools, temperature=0.45)

            if res.tool_calls:
                tc_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in res.tool_calls
                ]
                messages.append(LLMMessage(role="assistant", content=res.content, tool_calls=tc_dicts))

                for tc in res.tool_calls:
                    tool_def = tool_registry.get(tc.name)
                    tool_result: dict[str, Any] = {}
                    success = True

                    if tool_def and tool_def.handler:
                        kwargs = {k: v for k, v in tc.arguments.items() if v is not None}
                        if "active_merchant_id" not in kwargs and dialogue_state.merchant_id:
                            kwargs["active_merchant_id"] = dialogue_state.merchant_id
                        if tc.name in ("add_to_cart", "view_cart", "checkout", "list_orders", "cancel_order", "remove_from_cart"):
                            kwargs["user_token"] = user_token
                            kwargs["session_id"] = session_id

                        try:
                            tool_result = await tool_def.handler(**kwargs)
                        except Exception as e:
                            logger.error("tool_execution_failed", tool=tc.name, error=str(e))
                            tool_result = {"error": str(e)}
                            success = False
                    else:
                        tool_result = {"error": f"Tool '{tc.name}' not registered."}
                        success = False

                    # Deduplication & State Updates
                    if tc.name == "search_listings" and isinstance(tool_result, dict):
                        raw_results = tool_result.get("results", [])

                        # --- Title-based dedup (collapses duplicate DB rows) ---
                        seen_titles: set[str] = set()
                        title_deduped: list[dict] = []
                        for r in raw_results:
                            title_key = (r.get("title") or "").strip().lower()
                            if title_key and title_key in seen_titles:
                                continue
                            if title_key:
                                seen_titles.add(title_key)
                            title_deduped.append(r)
                        raw_results = title_deduped
                        tool_result["results"] = raw_results
                        tool_result["count"] = len(raw_results)

                        # --- Cross-turn dedup by ID ---
                        prev_ids = {
                            x.get("id")
                            for x in dialogue_state.last_shown_listings
                            if isinstance(x, dict) and x.get("id")
                        }
                        filtered = [r for r in raw_results if r.get("id") not in prev_ids]

                        if filtered:
                            dialogue_state.last_shown_listings = filtered
                            dialogue_state.focused_listing_id = filtered[0].get("id")
                            dialogue_state.focused_listing_data = filtered[0]
                        elif raw_results:
                            dialogue_state.last_shown_listings = raw_results
                            tool_result["notice"] = "These results overlap with previously shown items. Present them with fresh perspective or acknowledge the overlap naturally."

                        if kwargs.get("query"):
                            dialogue_state.last_search_query = kwargs["query"]

                    elif tc.name == "get_listing_details" and isinstance(tool_result, dict):
                        if tool_result.get("id"):
                            dialogue_state.focused_listing_id = tool_result["id"]
                            dialogue_state.focused_listing_data = tool_result

                    executed_tool_calls.append({"tool": tc.name, "args": tc.arguments, "success": success})

                    messages.append(
                        LLMMessage(
                            role="tool",
                            content=json.dumps(tool_result),
                            tool_call_id=tc.id,
                            name=tc.name,
                        )
                    )
            else:
                final_text = res.content or ""
                break

        # If the loop exhausted max_iterations without a final text response,
        # make one last LLM call WITHOUT tools to force a synthesis of all accumulated results.
        if not final_text and executed_tool_calls:
            messages.append(LLMMessage(
                role="user",
                content="You've gathered product data from the tools above. "
                        "Summarize what you found and present it to the customer "
                        "naturally with your honest assessment and recommendation."
            ))
            try:
                synthesis = await self.llm.complete(messages, tools=[], temperature=0.3)
                final_text = synthesis.content or ""
            except Exception:
                logger.warning("synthesis_llm_call_failed", session_id=session_id)

        if not final_text:
            final_text = "I'm here to help you find the best products, check reviews, and answer any questions! How can I assist you today?"

        await self.session_manager.update_dialogue_state(session_id, dialogue_state)
        return {
            "response": final_text,
            "tool_calls": executed_tool_calls,
            "session_id": session_id,
        }

    async def _format_transactional_response(
        self,
        tool_name: str,
        tool_result: dict[str, Any],
        tool_success: bool,
        error_msg: str,
        user_message: str,
        conversation_history: list[dict],
    ) -> str:
        """Format a natural response for a completed transactional action using the LLM.

        The tool has already been executed deterministically. This method only
        controls the *words* used to confirm/report the result to the user,
        grounded on exact data from the tool result.
        """
        action_desc = tool_name.replace("_", " ")
        status_text = "succeeded" if tool_success else f"failed: {error_msg}"

        grounding = (
            f"ACTION COMPLETED: {action_desc}\n"
            f"STATUS: {status_text}\n"
            f"RESULT DATA: {json.dumps(tool_result, default=str)}\n"
        )

        system = (
            "You are a warm, helpful shopping assistant. A transactional action just completed. "
            "Write a natural, concise confirmation (2-4 sentences) using the RESULT DATA below.\n"
            "RULES:\n"
            "- Quote prices, order IDs, item names, and totals EXACTLY from the result data\n"
            "- If the action failed, acknowledge the error honestly and suggest a next step\n"
            "- End with a brief, natural suggestion for what the customer might want to do next\n"
            "- Vary your language — don't use the same opening or closing every time\n"
            "- You may use markdown formatting (bold, bullet points) for readability\n"
        )

        fmt_messages = [LLMMessage(role="system", content=system)]
        for m in conversation_history[-4:]:
            r = m.get("role", "user")
            if r in ("user", "assistant"):
                fmt_messages.append(LLMMessage(role=r, content=m.get("content", "")))
        fmt_messages.append(LLMMessage(role="user", content=grounding))

        try:
            res = await self.llm.complete(fmt_messages, tools=[], temperature=0.5)
            if res.content and len(res.content.strip()) > 10:
                return res.content.strip()
        except Exception as e:
            logger.warning("transactional_format_llm_failed", tool=tool_name, error=str(e))

        # Fallback: simple template if LLM formatting fails
        if tool_success:
            return f"Done! Your {action_desc} was completed successfully. What would you like to do next?"
        else:
            return f"I ran into an issue with {action_desc}: {error_msg}. Would you like to try again?"

    async def process_message(
        self,
        session_id: str,
        user_message: str,
        user_token: str = "",
    ) -> dict[str, Any]:
        session = await self.session_manager.get_session(session_id)
        if not session:
            session = await self.session_manager.create_session()
            session_id = session["id"]
            trace_log("orchestrator.session_created", session_id=session_id)
        else:
            trace_log("orchestrator.session_loaded", session_id=session_id)

        logger.info("orchestrator_process_message_start", session_id=session_id, user_message=user_message)

        # ── PART 1: Load Persistent DialogueState ──
        dialogue_state = await self.session_manager.get_dialogue_state(session_id)
        trace_log(
            "orchestrator.dialogue_state_loaded",
            stage=dialogue_state.stage.value,
            focused_id=dialogue_state.focused_listing_id,
            listings_count=len(dialogue_state.last_shown_listings),
        )

        # ── PART 1b: Load persisted conversation messages for LLM context ──
        messages: list[dict] = session.get("messages") or []
        trace_log("orchestrator.conversation_history", persisted_turns=len(messages) // 2)

        # ── PART 2: Reference Resolution (Advisory — enriches LLM context, does not override) ──
        ref_resolution = _reference_resolver.resolve(user_message, dialogue_state)
        trace_log(
            "orchestrator.reference_resolved",
            ref_intent=ref_resolution.intent,
            target_id=ref_resolution.target_listing_id,
            confidence=ref_resolution.confidence,
            reason=ref_resolution.reason,
        )

        # Build advisory hints for the LLM (not hard overrides)
        reference_hints = ""
        if ref_resolution.target_listing_id:
            hint_item = next(
                (p for p in dialogue_state.last_shown_listings
                 if isinstance(p, dict) and p.get("id") == ref_resolution.target_listing_id),
                None
            )
            hint_name = hint_item.get("title", hint_item.get("name", "")) if hint_item else ""
            reference_hints = (
                f"The user likely refers to listing_id={ref_resolution.target_listing_id}"
                f"{f' ({hint_name})' if hint_name else ''}"
                f" — reason: {ref_resolution.reason}"
            )
        elif ref_resolution.target_listing_ids:
            reference_hints = (
                f"The user likely refers to listings: {ref_resolution.target_listing_ids}"
                f" — reason: {ref_resolution.reason}"
            )

        # ── PART 3: Fast Intent Classification & Routing ──
        history_tail = messages[-6:]
        intent_result = await self.intent_classifier.classify(
            user_message=user_message,
            dialogue_state=dialogue_state,
            last_seen_listings=dialogue_state.last_shown_listings or None,
            conversation_tail=history_tail or None,
        )

        # Use LLM's own resolution, with reference hints as advisory fallback
        effective_id = (
            intent_result.resolved_listing_id
            or intent_result.listing_id
            or ref_resolution.target_listing_id
            or dialogue_state.focused_listing_id
        )

        # Update consecutive unclear turns
        if intent_result.intent in ("UNCLEAR_INTENT", "CHITCHAT_OUT_OF_SCOPE"):
            dialogue_state.consecutive_unclear_turns += 1
        elif intent_result.intent != "ESCALATE_TO_HUMAN":
            dialogue_state.consecutive_unclear_turns = 0

        if dialogue_state.consecutive_unclear_turns >= 2:
            intent_result.intent = "ESCALATE_TO_HUMAN"

        update_funnel_stage(user_message, intent_result.intent, dialogue_state)
        await self.session_manager.update_dialogue_state(session_id, dialogue_state)

        # ── PART 4: Transactional Intents — Deterministic Execution + LLM Formatting ──
        if intent_result.intent in TRANSACTIONAL_INTENTS:
            trace_log("orchestrator.transactional_route", intent=intent_result.intent)

            # ADD_TO_CART
            if intent_result.intent == "ADD_TO_CART" and effective_id:
                tool_def = tool_registry.get("add_to_cart")
                res = {}
                tool_success = False
                error_msg = ""
                try:
                    if tool_def and tool_def.handler:
                        res = await tool_def.handler(listing_id=effective_id, quantity=1, user_token=user_token, session_id=session_id)
                        tool_success = True
                except Exception as e:
                    logger.error("add_to_cart_failed", error=str(e))
                    error_msg = str(e)

                p_name = (
                    dialogue_state.focused_listing_data.get(
                        "title", dialogue_state.focused_listing_data.get("name", "item")
                    )
                    if dialogue_state.focused_listing_data
                    else "item"
                )

                resp_text = await self._format_transactional_response(
                    tool_name="add_to_cart",
                    tool_result={
                        "item_name": p_name, "listing_id": effective_id,
                        "first_add": not dialogue_state.upsell_attempted,
                        **(res if isinstance(res, dict) else {}),
                    },
                    tool_success=tool_success,
                    error_msg=error_msg,
                    user_message=user_message,
                    conversation_history=messages,
                )

                if tool_success:
                    dialogue_state.upsell_attempted = True
                    await self.session_manager.update_dialogue_state(session_id, dialogue_state)
                return {
                    "response": resp_text,
                    "tool_calls": [{"tool": "add_to_cart", "args": {"listing_id": effective_id}, "success": tool_success}],
                    "session_id": session_id,
                }

            # CHECKOUT
            if intent_result.intent == "CHECKOUT":
                try:
                    cart_tool = tool_registry.get("view_cart")
                    cart_info = (
                        await cart_tool.handler(user_token=user_token) if (cart_tool and cart_tool.handler) else {}
                    )
                    items = cart_info.get("items", [])
                    if not items:
                        resp_text = await self._format_transactional_response(
                            tool_name="checkout",
                            tool_result={"error": "empty_cart", "items": []},
                            tool_success=False,
                            error_msg="Cart is empty — nothing to check out",
                            user_message=user_message,
                            conversation_history=messages,
                        )
                        return {
                            "response": resp_text,
                            "tool_calls": [{"tool": "view_cart", "args": {}, "success": True}],
                            "session_id": session_id,
                        }

                    tool_def = tool_registry.get("checkout")
                    gw = "razorpay" if "razorpay" in user_message.lower() else "stripe"
                    res = (
                        await tool_def.handler(payment_gateway=gw, user_token=user_token)
                        if (tool_def and tool_def.handler)
                        else {}
                    )

                    resp_text = await self._format_transactional_response(
                        tool_name="checkout",
                        tool_result={
                            "order_id": res.get("order_id") or res.get("id"),
                            "total_amount": res.get("total_amount") or res.get("amount") or cart_info.get("subtotal", 0),
                            "gateway": gw,
                            "status": "pending_payment",
                            "items_count": len(items),
                            **(res if isinstance(res, dict) else {}),
                        },
                        tool_success=True,
                        error_msg="",
                        user_message=user_message,
                        conversation_history=messages,
                    )
                    return {
                        "response": resp_text,
                        "tool_calls": [{"tool": "checkout", "args": {"payment_gateway": gw}, "success": True}],
                        "session_id": session_id,
                    }
                except Exception as e:
                    logger.error("checkout_failed", error=str(e))
                    err_str = str(e)
                    if "Only logged-in registered users" in err_str or "Authentication token required for checkout" in err_str or "401" in err_str:
                        resp_text = "You have items in your shopping cart! Because you are shopping as a guest, please sign in or register to complete checkout and place your order."
                    else:
                        resp_text = await self._format_transactional_response(
                            tool_name="checkout",
                            tool_result={},
                            tool_success=False,
                            error_msg=err_str,
                            user_message=user_message,
                            conversation_history=messages,
                        )
                    return {
                        "response": resp_text,
                        "tool_calls": [{"tool": "checkout", "args": {}, "success": False}],
                        "session_id": session_id,
                    }

            # VIEW_CART
            if intent_result.intent == "VIEW_CART":
                tool_def = tool_registry.get("view_cart")
                res = {}
                try:
                    if tool_def and tool_def.handler:
                        res = await tool_def.handler(user_token=user_token)
                except Exception as e:
                    logger.error("view_cart_failed", error=str(e))
                    resp_text = await self._format_transactional_response(
                        tool_name="view_cart",
                        tool_result={},
                        tool_success=False,
                        error_msg=str(e),
                        user_message=user_message,
                        conversation_history=messages,
                    )
                    return {
                        "response": resp_text,
                        "tool_calls": [{"tool": "view_cart", "args": {}, "success": False}],
                        "session_id": session_id,
                    }

                resp_text = await self._format_transactional_response(
                    tool_name="view_cart",
                    tool_result=res,
                    tool_success=True,
                    error_msg="",
                    user_message=user_message,
                    conversation_history=messages,
                )
                return {
                    "response": resp_text,
                    "tool_calls": [{"tool": "view_cart", "args": {}, "success": True, "result": res}],
                    "session_id": session_id,
                }

            # REMOVE_FROM_CART
            if intent_result.intent == "REMOVE_FROM_CART":
                cart_tool = tool_registry.get("view_cart")
                cart_res = {}
                try:
                    if cart_tool and cart_tool.handler:
                        cart_res = await cart_tool.handler(user_token=user_token)
                except Exception:
                    pass
                items = cart_res.get("items", [])
                if not items:
                    resp_text = await self._format_transactional_response(
                        tool_name="remove_from_cart",
                        tool_result={"error": "empty_cart"},
                        tool_success=False,
                        error_msg="Cart is already empty",
                        user_message=user_message,
                        conversation_history=messages,
                    )
                    return {
                        "response": resp_text,
                        "tool_calls": [{"tool": "remove_from_cart", "args": {}, "success": False}],
                        "session_id": session_id,
                    }
                target_item = None
                if effective_id:
                    target_item = next((x for x in items if x.get("listing_id") == effective_id), None)
                if not target_item:
                    target_item = items[0]
                item_id = target_item.get("id") or target_item.get("cart_item_id") or target_item.get("listing_id")
                item_name = target_item.get("title", target_item.get("name", "item"))
                tool_def = tool_registry.get("remove_from_cart")
                try:
                    if tool_def and tool_def.handler:
                        await tool_def.handler(item_id=item_id, user_token=user_token)
                    resp_text = await self._format_transactional_response(
                        tool_name="remove_from_cart",
                        tool_result={"removed_item": item_name, "item_id": item_id},
                        tool_success=True,
                        error_msg="",
                        user_message=user_message,
                        conversation_history=messages,
                    )
                    return {
                        "response": resp_text,
                        "tool_calls": [{"tool": "remove_from_cart", "args": {"item_id": item_id}, "success": True}],
                        "session_id": session_id,
                    }
                except Exception as e:
                    resp_text = await self._format_transactional_response(
                        tool_name="remove_from_cart",
                        tool_result={"item_name": item_name},
                        tool_success=False,
                        error_msg=str(e),
                        user_message=user_message,
                        conversation_history=messages,
                    )
                    return {
                        "response": resp_text,
                        "tool_calls": [{"tool": "remove_from_cart", "args": {"item_id": item_id}, "success": False}],
                        "session_id": session_id,
                    }

            # ORDER_HISTORY / TRACK_ORDER
            if intent_result.intent in ("ORDER_HISTORY", "TRACK_ORDER"):
                tool_def = tool_registry.get("list_orders")
                res = {}
                try:
                    if tool_def and tool_def.handler:
                        res = await tool_def.handler(user_token=user_token)
                except Exception as e:
                    resp_text = await self._format_transactional_response(
                        tool_name="list_orders",
                        tool_result={},
                        tool_success=False,
                        error_msg=str(e),
                        user_message=user_message,
                        conversation_history=messages,
                    )
                    return {
                        "response": resp_text,
                        "tool_calls": [{"tool": "list_orders", "args": {}, "success": False}],
                        "session_id": session_id,
                    }
                resp_text = await self._format_transactional_response(
                    tool_name="list_orders",
                    tool_result=res,
                    tool_success=True,
                    error_msg="",
                    user_message=user_message,
                    conversation_history=messages,
                )
                return {
                    "response": resp_text,
                    "tool_calls": [{"tool": "list_orders", "args": {}, "success": True}],
                    "session_id": session_id,
                }

            # CANCEL_ORDER
            if intent_result.intent == "CANCEL_ORDER":
                order_id_match = re.search(
                    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|ORD-\d+)", user_message, re.I
                )
                order_id = order_id_match.group(1) if order_id_match else None
                if not order_id:
                    return {
                        "response": "I'd be happy to help cancel an order. Could you share the order ID? "
                                   "You can say something like 'cancel order ORD-1234', or I can show your recent orders if you'd like.",
                        "tool_calls": [],
                        "session_id": session_id,
                    }
                tool_def = tool_registry.get("cancel_order")
                try:
                    if tool_def and tool_def.handler:
                        await tool_def.handler(order_id=order_id, user_token=user_token)
                    resp_text = await self._format_transactional_response(
                        tool_name="cancel_order",
                        tool_result={"order_id": order_id, "status": "cancelled"},
                        tool_success=True,
                        error_msg="",
                        user_message=user_message,
                        conversation_history=messages,
                    )
                    return {
                        "response": resp_text,
                        "tool_calls": [{"tool": "cancel_order", "args": {"order_id": order_id}, "success": True}],
                        "session_id": session_id,
                    }
                except Exception as e:
                    resp_text = await self._format_transactional_response(
                        tool_name="cancel_order",
                        tool_result={"order_id": order_id},
                        tool_success=False,
                        error_msg=str(e),
                        user_message=user_message,
                        conversation_history=messages,
                    )
                    return {
                        "response": resp_text,
                        "tool_calls": [{"tool": "cancel_order", "args": {"order_id": order_id}, "success": False}],
                        "session_id": session_id,
                    }

        # ── PART 5: Conversational / Search / Reasoning Flows -> Agentic Loop ──
        trace_log("orchestrator.agentic_route", intent=intent_result.intent)
        return await self._run_agent_loop(
            session_id=session_id,
            user_message=user_message,
            dialogue_state=dialogue_state,
            conversation_history=messages,
            user_token=user_token,
            reference_hints=reference_hints,
        )

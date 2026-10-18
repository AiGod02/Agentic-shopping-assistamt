Fix the agent's conversational behavior so it acts like a competent sales
assistant, not a passive Q&A bot. This is primarily a system prompt and
conversation-flow-control problem, not a new feature — implement in this
order.

GROUND RULES:
- Show me the current system prompt(s) used by the orchestrator before
  changing anything — I want to see what persona/instructions already exist.
- Test every change with real multi-turn conversations, paste actual
  transcripts, not descriptions of intended behavior.
- Do not make the agent pushy or manipulative — the goal is genuinely
  helpful sales behavior (discovery, honest tradeoffs, natural next steps),
  not dark-pattern urgency or overselling. Flag anywhere the line is unclear.

---

## PART 1 — Funnel Stage Tracking (add to existing DialogueState)

Add a stage field to the `DialogueState` object already built for reference
resolution:

```python
class FunnelStage(str, Enum):
    GREETING = "greeting"
    DISCOVERY = "discovery"        # gathering needs/preferences
    BROWSING = "browsing"          # viewing options, not yet narrowed
    EVALUATING = "evaluating"      # comparing specific items, asking details
    OBJECTION = "objection"        # hesitating on price/fit/trust
    READY_TO_BUY = "ready_to_buy"  # decided, needs a nudge to close
    POST_PURCHASE = "post_purchase" # order placed, tracking/support

    stage: FunnelStage
    stage_confidence: float  # how sure we are, for logging/debugging
    known_preferences: dict  # budget, priorities, constraints gathered so far
    objections_raised: list[str]  # e.g. ["price", "shipping_time"]
```

Update the stage after each turn based on the resolved intent and message
content (e.g. `add_to_cart` intent → READY_TO_BUY; "that's too expensive" →
OBJECTION with `objections_raised` appended). Show me the actual state
transition logic, not just the enum.

## PART 2 — System Prompt: Sales Persona & Strategy

Rewrite the orchestrator's system prompt to include explicit sales behavior
instructions, not just "you are a helpful shopping assistant." Cover:

1. **Discovery-first behavior**: if a user's first message is broad/vague
   ("show me laptops"), ask 1-2 qualifying questions before running a search
   or dumping results — unless they've already given enough detail (budget,
   use case, specific need) to search meaningfully. Never ask more than 2
   questions before showing something — don't interrogate.

2. **Recommend with reasoning, not lists**: when presenting options, lead
   with a specific recommendation and the reason tied to what the user said,
   then mention alternatives with honest tradeoffs — don't just enumerate
   products with specs.

3. **Objection handling patterns**: define explicit responses for common
   objection types —
   - Price objection → offer a cheaper alternative, mention financing/
     installment options if the merchant supports them, or justify value
     concretely (don't just repeat the price).
   - Uncertainty/trust objection ("is this good quality?") → surface reviews,
     return policy, or guarantees if available.
   - Comparison paralysis ("I don't know which one") → ask one clarifying
     question to break the tie (what matters most: price, quality, speed).

4. **Always end with a forward step**: every response involving a product
   should end with a concrete next action ("want me to add this to your
   cart?", "should I check availability for you?", "want to see reviews
   before deciding?") — never end on pure information with no direction.

5. **Honesty constraint, explicit in the prompt**: the agent must never
   fabricate urgency ("only 2 left!") unless that's real inventory data, never
   claim a product is best for the user if it genuinely isn't a good fit
   based on stated preferences, and must be willing to say "this might not
   be the right fit, here's why" when true. Sales behavior means guiding
   toward a good decision, not toward any decision.

6. **Post-decision upsell, correctly timed**: only after `add_to_cart` or
   clear purchase intent, and only if genuinely relevant (e.g. a commonly
   paired accessory) — never before the user has decided on the core item,
   never more than one upsell attempt per conversation unless the user
   engages with it.

## PART 3 — Tone Calibration by Funnel Stage

The response style should shift with `FunnelStage`:
- `GREETING`/`DISCOVERY`: warm, curious, asking questions
- `BROWSING`/`EVALUATING`: informative, comparative, patient
- `OBJECTION`: empathetic first, then address the specific concern directly
- `READY_TO_BUY`: efficient, remove friction, confirm details clearly, don't
  over-explain or re-pitch something already decided
- `POST_PURCHASE`: supportive, focused on fulfillment/tracking, light
  cross-sell only if natural

Show me how this is implemented — as prompt sections conditionally injected
based on `stage`, or as few-shot examples per stage, whichever fits the
existing orchestrator structure better. State which approach you used and why.

## PART 4 — Test Transcripts

Run and paste these full conversations:

**Transcript A — vague opening, should trigger discovery:**
```
User: "I need a laptop"
[Expect: 1-2 qualifying questions, not an immediate product dump]
User: [answers with budget + use case]
[Expect: a specific recommendation with reasoning, not a flat list]
```

**Transcript B — price objection handling:**
```
User: [after seeing a product] "That's a bit too expensive"
[Expect: cheaper alternative offered, or value justification — not just
 repeating the price or ignoring the concern]
```

**Transcript C — comparison paralysis:**
```
User: "I can't decide between these two"
[Expect: one clarifying question to help decide, not a repeat of both
 products' specs]
```

**Transcript D — ready to buy, should close cleanly:**
```
User: "Okay I'll take the first one"
[Expect: efficient confirmation + move toward cart/checkout, not a fresh
 pitch or unnecessary re-explanation]
```

**Transcript E — honesty check:**
```
User: [describes a need that the currently-focused product genuinely
 doesn't fit well]
[Expect: the agent says so and redirects, does not force-fit a bad
 recommendation to close a sale]
```

---

## FINAL OUTPUT

1. Diff of the DialogueState funnel stage addition.
2. Full before/after system prompt (or the conditional injection logic).
3. All 5 transcripts, full and unedited.
4. One paragraph: what's the failure mode if `stage` classification is wrong
   mid-conversation (e.g. agent thinks user is still browsing when they're
   actually ready to buy) — does it self-correct on the next turn, or does
   it require an explicit signal? This matters for how forgiving the system
   is to inevitable misclassification.
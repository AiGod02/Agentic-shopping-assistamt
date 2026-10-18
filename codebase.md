I need to genuinely understand my own codebase again — not a rewrite, a
comprehension pass. Generate documentation that reflects what the code
ACTUALLY does right now, not what it was originally intended to do. Where
current behavior differs from what any prior README/comments/docs claim,
flag the discrepancy explicitly.

GROUND RULES:
- Every claim must cite the actual file and function it comes from.
- If something is unclear, inconsistent, or you had to guess at intent from
  the code, say so explicitly — don't paper over ambiguity with a confident
  explanation.
- Write for someone who built this over many sessions and genuinely lost
  track of some of it — not for someone new to the domain. Assume I
  understand FastAPI, Postgres, vector search, and LLM orchestration
  conceptually; I need to re-orient on THIS specific implementation.

---

## PART 1 — System Map (one page, high level)

Produce a single diagram-in-text (boxes and arrows described in words, or
an actual Mermaid diagram if that renders better) showing:
- Every service (merchant_server, payment_server, agent_server, frontend)
  and what each one actually owns.
- The real request flow for one end-to-end user action: a customer message
  coming in, through to a response going out. Show every hop — which file,
  which function, in order.
- Which services talk to which, and how (REST call, shared DB, message
  queue) — not how they're supposed to talk, how they actually do right now.

## PART 2 — Data Model Reality Check

- List every table/model that currently exists, with its actual columns
  (not what a migration file from 3 sessions ago intended — the CURRENT
  live schema).
- For each, note: what recently changed (vertical_type, attributes JSONB,
  merchant_id scoping) and whether every consumer of that table has been
  updated to match, or if there are stale assumptions still lingering
  anywhere (grep for old field names, old query patterns).
- Flag any table or model that appears to be dead/unused — referenced
  nowhere, or referenced only by code that's itself unreachable.

## PART 3 — The Orchestrator, Traced Line by Line

This is the part I understand least. Walk through `orchestrator.py`
(and whatever it calls) as a narrated trace, using one real example:

"User says X" → show:
1. Where the message enters the system.
2. What gets attached to it (session state, merchant context, dialogue
   state) before any LLM call happens.
3. The actual sequence of LLM calls / tool calls that happen — in order,
   with what's passed to each and what comes back.
4. Where the intent gets resolved, where reference resolution happens (if
   implemented), where the response finally gets assembled.
5. What state gets updated/persisted at the end of the turn.

Do this narration for TWO examples:
- A simple case: "show me laptops under $1000"
- A stateful case: "tell me more about the second one" (relies on prior
  turn's context)

If any part of this flow is inconsistent, duplicated, or you find dead code
that looks like it should be running but isn't wired in — call it out here
specifically, don't just describe the happy path as if everything is clean.

## PART 4 — Known Fragile Areas (honest inventory)

Based on everything fixed and discussed in recent sessions, list the current
state of each of these, in one line each, PASS/FRAGILE/BROKEN with a reason:
- Merchant data isolation (listings, orders, payments, search)
- Bulk upload robustness
- Checkout idempotency
- Search relevance/ranking
- Intent routing and multi-turn reference resolution
- Vertical schema (ecommerce vs loan attributes)
- Sales behavior / conversation flow
- Test coverage (what's actually covered by the pytest suite vs. not)

## PART 5 — A Reading Order For Me

Given everything above, give me a suggested order to actually read through
the code myself over the next few days — which files, in what order, to
rebuild my own mental model, starting from the entry point of a request and
working outward. Assume I have maybe 1-2 hours a day for this, not a full
day. Break it into 4-5 sessions.

---

## OUTPUT FORMAT

Produce this as a single markdown document I can keep as a living reference,
not a one-time chat answer. Use real file paths and function names
throughout, not generic descriptions.
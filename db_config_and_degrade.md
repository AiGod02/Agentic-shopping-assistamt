Root cause identified: DATABASE_URL points to a database name
("agenticcommerce") that doesn't exist, causing SQL-side hybrid search to
fail entirely and silently fall through to a Chroma-only path using a
cold-loaded, un-tuned generic embedding model — producing irrelevant
results with no user-facing indication anything was wrong. Fix the
immediate cause AND the two structural gaps it exposed — don't stop at
the config fix.

---

## PART 1 — Immediate Fix: Database Configuration

1. Confirm the actual, correct database name and check every place
   `DATABASE_URL`/`database_url` is set (`.env`, config files, CI workflow
   env vars, any deployment config) for consistency. Find where
   "agenticcommerce" came from — a typo, a stale env file, a mismatched
   config between environments.
2. Fix it, confirm the app connects successfully, and confirm SQL-side
   hybrid search runs without error on a fresh request.
3. Re-run the exact failing conversation ("looking for the laptop" →
   "can you tell me more") and confirm correct, relevant, deduplicated
   results now that the SQL path is healthy.

## PART 2 — Honest Degradation on Search Backend Failure (the real gap)

This was asked for earlier and evidently isn't working — fix it properly
now that there's a real reproduction case.

1. When the SQL side of hybrid search fails (DB connection error, timeout,
   or any exception), this must be caught explicitly and logged at ERROR
   level (not silently continuing) — show me the current exception
   handling around the SQL query call, and fix it to not swallow failures.
2. Decide and implement the user-facing behavior: if SQL fails but vector
   fallback succeeds, either (a) proceed with vector-only results but
   apply the SAME relevance/category filtering and dedup as the primary
   path — never a lower bar for degraded mode — or (b) if vector-only
   results don't meet a reasonable confidence threshold, respond honestly
   ("I'm having trouble searching right now, please try again in a
   moment") rather than presenting weak matches as if they were confident
   recommendations.
3. Test this for real: intentionally point at a non-existent database
   again (reproduce today's exact failure), and confirm the agent now
   either produces correctly-filtered fallback results or an honest
   degradation message — never unfiltered garbage presented confidently.

## PART 3 — Fallback Path Parity (dedup + relevance must match primary path)

1. Confirm whether the dedup-by-listing_id and category/relevance
   threshold logic (from the earlier search relevance fix) is applied
   equally on BOTH the SQL+vector hybrid path AND the vector-only fallback
   path, or only on the primary path.
2. If only on the primary path: this is the actual root cause of bug
   recurrence — refactor so dedup and relevance filtering happen once,
   after results are gathered from whichever path(s) succeeded, not
   duplicated per-path (which is how one path ends up missing it).

## PART 4 — Pre-warm the Embedding Model at Startup

1. Move the SentenceTransformer model loading (currently happening lazily
   on first fallback-triggered request, causing the ~90 second delay seen
   in this transcript) to application startup instead — load it once when
   the service boots, not on the first live user request that happens to
   need it.
2. Confirm this removes the cold-start latency: trigger the fallback path
   again after this fix and confirm no HuggingFace download/model-loading
   delay appears in the logs — it should already be in memory.

## PART 5 — Re-verify Against the Earlier Regression Prompt

The previous session's regression prompt (critical-regression-test-gap)
asked whether the orchestrator's real decision-making (search vs.
reference resolution) has actual integration test coverage, not just
unit-level coverage. Revisit that now with this new information: was
today's bad "can you tell me more" behavior ALSO a reference-resolution
failure (should have resolved to the focused MacBook Pro instead of
running a fresh search at all), independent of the DB/embedding issue? Test
this specifically — with the DB now fixed, does "can you tell me more"
correctly resolve via DialogueState, or does it still incorrectly trigger
a fresh search even with everything healthy? This determines whether
today's transcript was ONE bug (infra) or TWO bugs (infra + reference
resolution) that happened to surface together.

---

## FINAL OUTPUT

1. Confirmed root cause and fix for the DB config.
2. Diff + test evidence for honest degradation on search backend failure.
3. Diff + confirmation for fallback-path filtering parity.
4. Diff + confirmation for startup model pre-warming (no more live
   cold-start delay).
5. Answer to Part 5: was reference resolution also broken, independent of
   the infra issue? Test and report honestly either way.
6. Update `acp_status.md` with all findings — including adding "search
   backend failure handling" as its own tracked item, since today proved
   it wasn't actually covered despite being asked for earlier.
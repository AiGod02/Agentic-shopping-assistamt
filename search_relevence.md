Critical bug: searching for "laptop" returns an iPad Pro as the top
recommendation and an OLED TV in the results, with duplicate entries. Fix
this before any other work — a wrong product recommendation is worse than
a robotic response.

Actual transcript that surfaced this:
```
User: "hey i want to buy a laptop"
Agent recommends: iPad Pro 13" M4 (#1), then lists:
  1. iPad Pro 13" M4 — $1299.0
  2. iPad Pro 13" M4 — $1299.0  (duplicate)
  3. LG C4 65" OLED TV — $1796.99  (not a laptop)
  4. LG C4 65" OLED TV — $1796.99  (duplicate, not a laptop)
  5. MacBook Pro 16" M3 Max — $3499.0  (the only actual laptop, ranked last)
```

GROUND RULES:
- Diagnose before fixing — show me the actual query/filter/ranking logic
  currently used for `search_listings`, don't guess.
- Reproduce this exact bug first with a test ("laptop" query against the
  seeded catalog) before claiming it's fixed.
- Fix root cause, not just this one query — I want "laptop" and any other
  category term to reliably return only matching-category items, ranked by
  actual relevance.

---

## PART 1 — Diagnose Duplicate Results

1. Check the catalog data itself: are there genuinely two separate rows for
   "iPad Pro 13" M4" and two for "LG C4 65" OLED TV" in the listings table?
   Run a query and show me. If yes, this is a data problem (duplicate seed
   data or duplicate bulk-upload) — identify and clean it up, and check
   whether bulk-upload has a duplicate-SKU/duplicate-title guard.
2. If the underlying data is NOT duplicated, then the hybrid search (SQL +
   vector merge in `chroma_search.py`) is returning the same listing twice
   from two different retrieval paths without deduplicating by listing_id
   before returning results. Show me the merge logic and add a dedupe step
   (dedupe by listing_id, keep the highest-scoring occurrence) before results
   are returned or ranked.

## PART 2 — Diagnose Category/Relevance Mismatch

1. Show me exactly how `search_listings` currently works: is it pure vector
   similarity search with no category/type filter or minimum relevance
   threshold? Show the actual query construction.
2. Show me what `type` or `category` field exists on the Listing model, and
   whether it's used anywhere in search at all currently.
3. Identify why "laptop" semantically matched an iPad and a TV strongly
   enough to outrank an actual MacBook. Likely causes to check:
   - The embedding model conflating "premium electronics" broadly rather
     than distinguishing device categories — check what text is actually
     being embedded per listing (is `category`/`type` even included in the
     text that gets embedded, or only free-form description text?).
   - No minimum similarity score threshold — low-relevance results are
     being included instead of filtered out.
   - No hard category filter path — even a rough keyword-to-category rule
     ("laptop" → filter category IN ["laptop", "notebook", "computer"])
     would have prevented this, layered on top of semantic search, not
     replacing it.

## PART 3 — Fix: Hybrid Relevance Strategy

Implement, in order of precedence:
1. **Hard category filter when confidently inferable**: if the query clearly
   names a product category ("laptop", "phone", "TV"), apply a category/type
   filter before or alongside vector search — don't rely on embeddings alone
   to enforce category boundaries.
2. **Minimum relevance threshold**: results below a reasonable similarity
   score should be excluded entirely, not padded into a top-5 just to fill
   the list. Returning fewer, correct results is better than 5 results where
   2 are wrong.
3. **Re-rank by relevance first, rating second**: relevance to the query is
   the primary sort key; star rating should only break ties among similarly
   relevant results, not override relevance entirely (which is what's
   currently happening — the TV and iPad are outranking the MacBook purely
   on rating).
4. **Ensure embedded text includes category/type**, not just free-form
   description, so the vector space actually separates "laptop" from
   "tablet" from "TV" meaningfully.

## PART 4 — Verification

1. Re-run the exact failing case: query "laptop" against the seeded catalog.
   Paste the actual results — confirm no duplicates, and confirm only
   genuinely laptop-category items appear (or a correctly reasoned fallback
   if the catalog has zero laptops, which should say so honestly rather than
   substituting unrelated items).
2. Test 2-3 more category queries ("phone", "TV", "tablet") against the same
   catalog to confirm this wasn't a one-off fix for just "laptop."
3. Test a genuinely ambiguous/broad query ("something for work") to confirm
   the fix doesn't over-tighten and now returns nothing for legitimately
   fuzzy requests — there should be a reasonable middle ground, not
   all-or-nothing filtering.
4. Re-run the sales-behavior test transcripts from the prior fix (Transcript
   A specifically — "I need a laptop") to confirm the discovery-question
   behavior now operates on top of correct search results, not on top of
   this bug.

---

## FINAL OUTPUT

1. Root cause explanation for both the duplication and the category mismatch
   — actual diagnosis, not assumptions.
2. Diffs for the dedupe fix and the relevance/ranking fix.
3. All test results from Part 4, pasted in full.
# Findings log (input for the retrieval evaluation report)

Things learned while building, with the evidence. Milestone 2's parsing
spike is written up separately in `runs/spike/spike_notes.md`.

## Milestone 5: loaders

- **Encoding detection guessed wrong.** On `Privacy_Notice_Rev01-2026.txt`, charset_normalizer
  guessed `cp775` (Baltic), which would have garbled every smart quote and dash. The loader now tries
  UTF-8, then Windows-1252, and only falls back to the detector if both fail. The detector's guess is
  still logged in the decision reason.
- **RTF paragraphs.** `striprtf` ends each RTF paragraph with one newline, not a blank line, so the
  whole file first came out as 2 blocks. Each line is now its own paragraph, with table rows kept together.

## Milestone 6: cleaning, dedupe, decision log

**Decisions: 27/27 match the answer key** (layout parser): 22 cleaned, 4 dropped, 1 quarantined.
The naive run quarantines the 4 scans as well ("no text layer; needs OCR"), which the grader counts as
the 4 expected differences.

**Quote survival** (golden quotes found in the full cleaned text, before chunking):

| Parser | Survived | Lost |
|---|---|---|
| layout-aware | **50/50** | none |
| naive | **38/50** | 10 in the quarantined scans (8 table + 2 chart), 2 in the newsletter (interleaved columns) |

4 more quotes point at dropped duplicate copies. Their canonical copy is counted instead.

**Near-duplicate similarity (word 5-gram Jaccard, threshold 0.90):**
FAQ copy 1.00 (exact duplicate anyway), wire DOCX vs PDF **0.956** (dropped), Overdraft v2 vs v3
**0.552**. So v2 and v3 are not near-duplicates, and a version guard also makes sure two different
versions of a policy are never deduplicated.

**Canonical copy:** plain filename order would have kept the wrong copy both times
(`faq (1).html` < `faq.html`; `PAY-WT-004...docx` < `Wire_Transfer...pdf`). The rule prefers no
copy marker, then the published format (pdf > html > docx).

**Design change: the email is unquoted, not stripped.** The spec said to drop `>` quoted lines, but
the member's original complaint exists *only* as a quoted reply, and the reference text keeps it.
Quoted lines are unquoted instead, then address headers, disclaimers (3) and repeated signature
blocks are removed. Two bugs found by tests on the way:
- A quoted blank line is a bare `>`, so the whole quoted message loaded as one paragraph.
  Paragraphs are now split again after unquoting.
- One disclaimer was glued to "Sent from my phone" with no blank line, so disclaimers are matched
  per line.

**Cleaned text vs ground truth** (word-sequence similarity, 1.00 = identical): 16 of 22 documents score
0.99-1.00. The rest are explained:
- **call notes 0.83, email 0.92:** the ground truth is already PII-scrubbed (milestone 7).
- **scans 0.89-0.95:** table header formatting and the chart caption wording differ.
- **newsletter 0.74:** Docling's reading-order recovery is only *partly* right. One sentence ("You
  can also lock your debit card...") lands in the wrong article, and two lines from different columns
  are spliced mid-sentence ("...with coffee month's e-mail update. from local roasters"). Both golden
  quotes still survive, so retrieval scores are unaffected, but an answer quoting that passage could
  be garbled. Accepted as a known limitation; not tuned.

## Milestone 7: PII scrubbing

**Recall vs the planted inventory: 118/118 (100%)** across all 8 types (name 15/15, member 15/15,
account 15/15, address 15/15, email 18/18, phone 14/14, dob 13/13, ssn 13/13). No inventory value
appears in *any* scrubbed document. Golden-quote survival is still 50/50 after scrubbing (0 collateral
damage). The internal Account Closure Procedure's worked example (Dana Whitfield, HCU-004821,
7730-0012-4471, her address) is caught because scrubbing runs on every document, not just
confidential ones.

**Out-of-the-box Presidio gaps, closed with Harbor-specific recognisers:** `HCU-` member numbers
(only half-matched, as a low-score driver's licence), `7730-` account numbers (missed), 9XX SSNs
(Presidio's built-in rejects that never-issued range), "Birch Lane" tagged as a person (the address
match now wins over any PERSON hit inside it), and `example.com` inside an email flagged as a URL
(one merged `[REDACTED-EMAIL]`). Presidio's default regex flags ignore case, which would let the
address pattern's `[A-Z][a-z]+` match lowercase words, so the recognisers run case-sensitive.

**Redactions not in the inventory:**
- "Port Alden Branch" was tagged as a person (a false positive that would remove a branch name).
  Fixed: any name containing an allow-listed Harbor name is kept.
- "Janet Albright" (staff, full name in the complaint email) is redacted. The inventory treats staff
  as non-PII, but NER can't tell a staff member from a member. See the decision below.

**Deliberate choice: over-redact staff full names (decided 2026-09-25).** Every full first + last name
is redacted, including staff. Result: 1 staff name redacted ("Janet Albright", once per mention in
the complaint email), which no golden query depends on. Why: for a credit union, an over-redacted staff
name is a far cheaper mistake than a leaked member name, and the recogniser can't tell the two apart.
Alternatives considered and rejected for now:
- a staff allow-list (it would have to come from Harbor's HR directory and be kept current);
- redacting only names in member contexts ("Member:", "Dear ..."), which is brittle, because a member
  named any other way would leak.

Revisit if answers ever need to cite the staff member who handled a case.

The scrub log stores type, position and a SHA-256 of each value, never the value itself.

## Milestone 8: pipeline runner and stage cache

Each stage's output is cached under a key that chains `sha256(stage, version, params, previous key)`,
starting from a fingerprint of every corpus file. So a change anywhere upstream invalidates everything
after it, and nothing before it.

| Layout run | Time | Why |
|---|---|---|
| Fully cold (no caches) | ~39 s | Docling OCR on 4 scans, plus spaCy for PII |
| Docling cache warm, stages forced | ~17 s | mostly loading the spaCy model |
| Normal rerun | < 1 s | every stage a cache hit |

**Reproducibility bug found and fixed:** two runs with identical inputs wrote *different*
`documents.jsonl` files, because the loader recorded runtime bookkeeping (whether Docling's cache was
hit, and how long parsing took) inside each document. That's now kept out of document content, and
two fully recomputed runs are byte-identical. Also, a parse failure (the corrupt Q2 PDF) is now cached
too; before, every run started Docling's models just to watch that file fail again (~20 s).

## Milestone 9: chunkers A and B

| Parser | Chunker | Chunks | Mean chars | Max chars | Golden quotes inside one chunk |
|---|---|---|---|---|---|
| layout | A_fixed (800 / 150 overlap) | 121 | 731 | 800 | 50/50 |
| layout | B_structure (headings, ≤1200, whole tables) | 151 | 510 | 1389* | 50/50 |
| naive | A_fixed | 107 | 736 | 800 | 38/38 |
| naive | B_structure | 128 | 537 | 1215 | 38/38 |

\*The fee schedule table (21 rows) is kept whole: tables may reach 2000 chars before they are split by
rows with the header repeated. No table in this corpus is that big, so that path is only covered by a
unit test.

**No golden quote is split by either chunker.** For A that's the job of the 150-character overlap:
every quote is 20 words or fewer, so some window always holds it whole. So "quotes lost to chunking"
won't separate A from B here; retrieval ranking will.

**What the chunks look like** (`runs/chunk_review.md`):
- A's chunk holding the $29 overdraft fee starts mid-way through section 3 (Courtesy Pay limits),
  includes all of section 4 (fees), and ends mid-sentence in section 5 ("...transfers from a linked
  Primary Share"). B's chunk is exactly section 4, prefixed with "Harbor Credit Union Overdraft Policy".
- **A cuts a table row in half.** On the Q3 rate sheet, A's first window ends inside
  `Money Market | $2,500 to $24,999 | 2.47%`: that row's APY (2.50%) lands in the next chunk,
  separated from its row label. B keeps each table whole with its header row.
- Caveat on the metric: `all_tokens` only needs each word *somewhere* in the chunk, so a chunk that
  holds a whole table satisfies every row-level query in it. It measures "was the evidence
  retrieved", not "was the right cell read".

## Milestone 10: embeddings and indexes

One command (`src/ingest.py --parser all --chunker all`) builds **4 Chroma collections + 4 BM25
indexes** (naive/layout × A/B), 107-151 chunks each, in about 26 s from cached documents. A rerun is
all cache hits; each index is tagged with its cache key, so "is this index current?" is a lookup, not
a rebuild.

- **Deterministic vectors:** re-embedding every chunk from scratch (CPU, seeded) gives byte-identical
  vectors for all four combinations.
- **Pinned model, enforced:** each collection records the embedding revision it was built with.
  Opening it under a different revision in `model_manifest.json` raises an error, instead of silently
  comparing query vectors from one model against chunk vectors from another.
- **No network:** model loading had quietly contacted the Hugging Face Hub. The code now runs offline
  by default (`HF_HUB_OFFLINE=1`); downloading needs an explicit `HARBOR_ALLOW_DOWNLOADS=1`.
- **Filters hold in both indexes:** with the member-facing filter (retail, not restricted, current
  version), no business, restricted or Overdraft v2 chunk is returned by vector or BM25 search for any
  test query.
- **BM25 filters before truncating:** for "velocity rule VR-3 card transactions" the restricted fraud
  doc ranks first unfiltered. With the filter it disappears and 5 allowed results still come back.
  (Filtering *after* taking the top 5 would have returned fewer.)
- **No PII in any index:** none of the 118 planted values appears in any stored chunk text.
- **Chroma gotcha:** it attaches its own default embedding model to a collection unless told not to
  (`embedding_function=None`); otherwise a stray text query could be embedded by a different, unpinned
  model.

## Milestone 11: query path (filter -> BM25 + vector -> RRF -> rerank)

**Smoke test** (layout / B_structure, top 3):

| Query | BM25 | Vector | Hybrid + rerank |
|---|---|---|---|
| q001 exact term "Form HCU-DSP-114" | rank 1 | rank 1 | rank 1 (rerank 0.998) |
| q009 paraphrase "send money to another bank... go out today" | **not in top 10** (ranks the complaint email first on shared words; the answer is at rank 16) | **rank 1** | **rank 1** (fused rank 3, lifted by the reranker) |
| q028 version trap "current overdraft fee" | | | v3 first with the superseded filter; **v2 first without it** |

- **The paraphrase case is why hybrid exists.** BM25 has no shared keywords to work with ("send money
  to another bank" vs "wire transfer"), and vector search finds it. Fusion keeps both signals, and the
  cross-encoder picks the best of the fused candidates.
- **The version trap is why the superseded filter exists.** Without it, the reranker ranks v2's
  fee clause (0.978) *above* v3's (0.949). Relevance can't tell which version is in force; only
  metadata can.
- **Restricted access works both ways.** q003 (fraud rule VR-3) returns no restricted chunk under the
  member-facing filter, and the fraud doc ranks first when restricted access is allowed. That proves
  the doc is indexed and the filter is what's hiding it.
- **Latency (CPU, per query, excluding one-off model loading):** BM25 < 1 ms, vector ~30-40 ms
  (mostly embedding the query), fusion < 0.1 ms, **rerank ~1.9 s** for 30 candidates. The reranker is
  by far the most expensive stage, so the eval must show it earns that cost.
- **Spec arithmetic error fixed:** the RRF worked example said c2 = 0.03226 by adding rounded parts;
  1/63 + 1/61 = 0.032266, so **0.03227**. The ranking was unaffected.
- Timings first included model loading (the first vector query showed 6.5 s). Models now load when the
  retriever is created, so timings measure search only.

## Milestone 12: the eval matrix (`runs/20260925-112912_eval/`)

`--check-repro` ran the whole matrix twice: **results identical (17 rows)**. **Every row passes every
safety check**: q003 never leaks the restricted doc, clearance finds it, and there are 0 wrong-tenant,
0 restricted and 0 superseded chunks across all top-10s (except row 17, which switches that filter off
on purpose). 41 scored queries; **one query = 0.024 of R@5**, so differences under ~0.05 are one or
two queries.

| Row | Config | P@5 | R@5 | R@10 |
|---|---|---|---|---|
| 1 | naive / A / bm25 | 0.127 | 0.514 | 0.545 |
| 8 | naive / B / hybrid_rerank | 0.146 | 0.585 | 0.691 |
| 12 | layout / A / hybrid_rerank | 0.200 | 0.872 | 0.951 |
| 13 | layout / B / bm25 | 0.180 | 0.756 | 0.813 |
| 14 | layout / B / vector | 0.210 | **0.902** | **0.968** |
| 15 | layout / B / hybrid | 0.210 | 0.902 | 0.935 |
| 16 | layout / B / hybrid_rerank | 0.210 | 0.902 | 0.959 |

(P@5 ceiling averaged over the scored queries: 0.239.)

**Before/after 1: parsing is the big win.** naive → layout (B, hybrid_rerank): **R@5 0.585 → 0.902
(+0.32)**. It comes entirely from the query types the scans hold: scanned_table 0.00 → 1.00 (8
queries), figure 0.00 → 1.00 (2), reading_order 0.00 → 1.00 (2). Every other type is identical.

**Before/after 2: chunking helps a little.** A → B (layout, hybrid_rerank): R@5 0.872 → 0.902,
R@10 0.951 → 0.959. The gain is in paraphrase (0.56 → 0.67) and multi_chunk (0.69 → 0.75).
That's one or two queries, so a small, real-looking but not decisive gain.

**Before/after 3: retrieval stages (layout, B).** BM25 → vector is a large gain (R@5 0.756 → 0.902).
**After that, hybrid and rerank add nothing on average:** R@5 stays at 0.902, and R@10 goes
0.968 (vector) → 0.935 (hybrid) → 0.959 (rerank). Only 5 queries move between those three modes, and
they cancel out:
- rerank rescues q008 and q019 (vs hybrid)
- rerank hurts q013 ("formal gripe": vector rank 6 → rerank rank 11) and q034 (multi-part lost-card question)

Meanwhile the reranker costs **~1.2-1.5 s per query** (p95 ~1.8 s) against ~7 ms for vector search.
**On this golden set the reranker does not justify its latency.** Honest caveats: 41 queries is
small, BM25's strengths (exact identifiers) are already covered, since exact_term is 1.00 for every
mode, and rerank does *reduce* the score of near-miss unanswerable questions (see below).
Recommendation for Harbor: keep hybrid retrieval as the default (BM25 is cheap insurance for
identifiers on real traffic), and make the reranker a measured option to revisit with a bigger golden
set, not a default.

On the naive parser, rerank *hurts*: R@5 0.634 (hybrid) → 0.585 (rerank). With the scans missing,
the fused candidate pool is worse, and the cross-encoder promotes plausible-but-wrong chunks.

**Row 17: superseded filter off** (on row 14, picked mechanically: highest R@5, ties by R@10).
**39 Overdraft v2 chunks** appear across the top-10s, and overall R@5 drops 0.902 → 0.878. The
version_trap type still shows R@5 1.00, because recall only asks "was v3 found", not "was v2 kept
out". **Recall can't see this risk; the intrusion count can**, which is why the eval reports both.

**Unanswerable queries: no score threshold would work.** In every rerank row, 11-12 answerable
queries score *below* the best unanswerable one. The worst is q045 ("prepayment penalty on an RV
loan?") at 0.549: the auto loan sheet says "no prepayment penalty" for *auto* loans, a near-miss that
a relevance score can't tell from an answer. Refusing to answer belongs in the answer step (later in
the week), not in a retrieval threshold.

## Milestone 13: clean re-run (D1 proof), and the run IDs the report cites

`cache/stages/` and `index/` deleted (only the committed `cache/captions/` kept), then everything
rebuilt with **no API key in the environment** and Hugging Face offline:

- **Ingestion from scratch:** 52 s for all four parser × chunker combinations, including Docling re-OCRing
  the 4 scans. Every stage's cache key came out identical to the earlier runs.
- **Eval:** 4 min 20 s for the 17-row matrix. **`results.json` is byte-identical** to milestone 12's
  (`cmp` reports no difference).
- **Ingestion grade:** 27/27 decisions, 50/50 quote survival (layout) vs 38/50 (naive), PII 118/118,
  1 deliberate over-redaction (staff name).
- **Tests:** 130 passed.

**Cited runs:**
- eval: `runs/20260925-114234_eval/` (results.md, results.json, per_query.csv, timings.json)
- ingestion: `runs/20260925-114231_layout_B_structure/` (decisions.csv, ingestion_grade.json, config.json)
  and `runs/20260925-114204_naive_B_structure/` for the naive comparison
- earlier identical runs: `runs/20260925-112912_eval/` and `..._eval_repro/` (the `--check-repro` pair)

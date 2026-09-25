# FDE Xlerate - Week 2, Day 1
Build plan: ingestion pipeline, hybrid retrieval and retrieval eval (Harbor Credit Union)

See `spec.md` for the design (contracts, metadata schema, decision policy,
metric definitions, experiment matrix). This is the build order. Each
milestone should be working and verified before you start the next.

**Why this order:** the two things most likely to blow up the day are
(1) Docling's OCR on the scanned PDFs and (2) the figure-caption API
step. Both are tackled right after a small foundation, so if either
needs a fallback you find out in the first hour, not at 5pm. The
metric code is also written early, because it's pure logic that's easy
to test and everything else is judged by it.

**⏸ PAUSE** marks a point where you should stop, look at the output
yourself, and decide whether to continue, before building on top of it.

All commands run from `labs/week2_day1/`. The venv, `requirements.txt`
and `model_manifest.json` are created separately; this plan assumes they
exist.

## Milestone 0 — Environment and scaffolding

- [x] Confirm the venv works: `uv run python --version` → `Python 3.12.x`
- [x] Confirm the dataset is intact:
      `uv run python data/harbor_rag_dataset/scripts/verify_dataset.py`
- [x] Create folders: `src/`, `tests/`, `config/`, `cache/captions/`,
      `cache/stages/`, `index/`, `runs/`, `artifacts/`
- [x] Lab `.gitignore`: `cache/stages/`, `index/`, `runs/*/tmp/`.
      **Not** `cache/captions/` (committed on purpose, see spec)
- [x] `tests/conftest.py`: put `src/` on `sys.path`
- [x] `config/source_catalog.csv`: 27 rows, columns `filename, doc_id,
      title, tenant, sensitivity, version, effective_date, superseded_by`,
      typed up from the dataset README's corpus table. No defect or
      expected-decision columns.
- [x] `src/config.py`: paths, seed (0), default params for every stage,
      a `load_manifest()` that reads `model_manifest.json`
- [x] One-time model download: a small script (or `config.py` function)
      that loads bge-small and bge-reranker at their manifest revisions,
      then check they load again with `HF_HUB_OFFLINE=1`

**Verify:**
```bash
uv run python data/harbor_rag_dataset/scripts/verify_dataset.py   # ... ALL CHECKS PASSED
uv run python -c "import docling, pymupdf, chromadb, rank_bm25, sentence_transformers, presidio_analyzer, anthropic; print('ok')"
HF_HUB_OFFLINE=1 uv run python -c "import config; config.check_models_offline()"   # prints both model ids + revisions
uv run pytest   # 0 tests collected, no errors
```

**Checkpoint:** every library imports, both models load offline at the
pinned revisions, catalog has 27 rows whose filenames exactly match
`ls data/harbor_rag_dataset/corpus` (write a 3-line test for that:
`tests/test_catalog.py`).

## Milestone 1 — Contracts and golden-set match rules

Small, but needed so that milestone 2's spike can be *measured*.

- [x] `src/models.py`: `Decision`, `Block`, `Document`, `Chunk`
      dataclasses (spec "Data shapes") + `to_dict`/`from_dict`, JSON Lines
      read/write helpers
- [x] `src/golden.py`: load `golden_set.yaml`; `normalise(text)` (lowercase,
      NFKC, curly quotes → ASCII, en/em dash → `-`, collapse whitespace);
      `matches(chunk_text, location)` for `substring` and `all_tokens`;
      `relevant_items(query)` grouping locations by normalised quote

**Verify:** `uv run pytest tests/test_models.py tests/test_golden.py`
- round-trip: `Document` → JSON → `Document` is equal
- `normalise("It’s  a — test")` == `"it's a - test"`
- `all_tokens`: `"24 months 4.05%"` matches `"24 months | 3.95% | 4.00% | 4.05%"`, not `"24 months | 3.95%"`
- golden set loads 45 queries; type counts equal the README's
  (6/9/8/2/2/4/4/2/2/2/1/3)
- `relevant_items`: q009 → 1 item (two locations), q036 → 1, q032 → 4, q043 → 0
- every quote matches its own ground-truth file in `eval/ground_truth_text/`
  (a free sanity check of your matcher: 54/54)

**Checkpoint:** tests green. Your matcher agrees with the dataset's own
verification.

## Milestone 2 — Spike: Docling on the hard PDFs (highest risk)

Goal: find out, before building anything else, whether local
layout-aware parsing recovers the scanned tables and the newsletter's
reading order well enough.

- [x] `src/parse_pdf_layout.py`: run Docling (OCR on, table structure on)
      on one PDF; map its output to `Block`s (heading / paragraph /
      list_item / table as `cell | cell` rows with header first / picture
      placeholder); keep picture bounding boxes + page image crops for
      milestone 3; record Docling version + OCR engine + options in the
      document's history
- [x] `src/parse_pdf_naive.py`: PyMuPDF `get_text("text")` per page (5
      minutes, needed for the comparison)
- [x] Throwaway spike command (becomes part of `grade_ingestion.py`
      later): for the 5 PDFs `fee_schedule_2026`,
      `deposit_rate_sheet_2026q3`, `auto_loan_comparison`,
      `mortgage_heloc_rate_notice`, `newsletter_summer_2026`, parse with
      both parsers, write `Document.text` to `runs/spike/<doc_id>.<parser>.txt`,
      and print **quote survival**: golden quotes for that doc found in
      the full text (using milestone 1's matcher)
- [x] Cache Docling output per file hash (it's slow), so reruns are instant

**Verify:**
```bash
uv run python src/parse_pdf_layout.py --spike
```
Expected shape (your numbers will differ; these are the targets):
```
doc_id                       naive   layout
fee_schedule_2026            0/2     2/2
deposit_rate_sheet_2026q3    0/2     2/2
auto_loan_comparison         0/4     2/4   (the 2 chart quotes need captions, milestone 3)
mortgage_heloc_rate_notice   0/2     2/2
newsletter_summer_2026       0/2*    2/2   (*or partial: interleaved columns)
```

**⏸ PAUSE — review the spike.** Open the `.layout.txt` files next to
`eval/ground_truth_text/<doc_id>.txt` and read them side by side. Check:
table rows kept on one line with their row labels? `%` and `$` kept?
The mortgage notice (150 dpi, 3° skew, stamp) is the likeliest failure.
If a table quote doesn't survive, try in this order, re-measuring each
time: (1) a different Docling OCR engine (default is `ocrmac`; try
RapidOCR); (2) higher page render
resolution for OCR; (3) forced full-page OCR; (4) a deskew
pre-processing step on page images. Record what you tried and the
result; it goes into the report's "ingestion" section. Don't move on
until at least the fee schedule, rate sheet and auto loan table quotes
survive.

**Checkpoint:** layout-aware survival ≥ 8/10 on the non-figure quotes of
these 5 docs, naive clearly worse, and you know Docling's runtime per
document.

## Milestone 3 — Figure captions with a disk cache (second risk)

- [x] `prompts/figure_caption_v1.md`: instruct the model to describe the
      figure factually and list **every label with its value and unit**
      (e.g. "Mobile app 0.6 days"). No speculation, no text outside
      the figure.
- [x] `src/captioning.py`:
  - `cache_key(image_png_bytes, model_id, prompt_version)` →
    `<sha256>__claude-opus-5__v1`
  - `get_caption(image, doc_meta, mode)` → cache hit returns cached;
    miss + `online` calls the API and writes the cache file; miss +
    `offline` raises `CaptionCacheMiss`
  - governance gates **before** any API call: doc `sensitivity` must be
    `public`; picture must be classified as a chart/figure (skip
    logos, stamps, signatures); log every call
  - (from the milestone 2 spike) the spike found exactly 2 pictures: the
    auto loan bar chart and the mortgage manager's **signature**
    (`cache/stages/figures/*.png`). Docling's picture classifier is off
    by default and needs an extra model download, so decide here: enable
    it, or use a cheap rule (e.g. the crop must sit next to a "Figure N."
    caption, or exceed a minimum size). The signature must never reach
    the API.
  - client call: `claude-opus-5`, one image block (base64 PNG) + the
    prompt text; no `temperature` (not accepted by this model);
    read the key from the repo-root `.env`
- [x] Wire into `parse_pdf_layout.py`: each picture becomes a
      `figure_caption` block at its reading-order position, prefixed
      `[Figure caption, model-generated: claude-opus-5, prompt v1]`,
      `generated=True`

**Verify:**
```bash
uv run pytest tests/test_captioning.py
#   fake client: cache miss (online) calls client once and writes file;
#   second call hits cache, client not called; offline miss raises;
#   non-public doc never calls client; key changes when prompt_version changes
uv run python src/captioning.py --doc auto_loan_comparison --mode online    # the ONE live call
ls cache/captions/            # one JSON file per captioned figure
env -u ANTHROPIC_API_KEY uv run python src/parse_pdf_layout.py --spike --captions offline
```
Expected: auto_loan_comparison layout survival goes to 4/4 (q024 tokens
`mobile app 0.6 days`, q025 `dealer 2.8 days`); the offline run works
with no key.

**⏸ PAUSE — read the caption.** Is every bar value present, with
correct numbers? Did any picture get skipped or sent that shouldn't
have (check the call log: the mortgage stamp/signature must be
"skipped")? If a value is wrong, fix the prompt, bump to `v2` (new cache
key, old file kept for the record), and rerun. Commit `cache/captions/`.

**Checkpoint:** captions cached and committed, and the eval path can run
fully offline from here on.

## Milestone 4 — Metrics (pure logic, test-first)

- [x] `src/metrics.py`:
  - `precision_at_k(results, items, k)` with the "each item credited once"
    rule; `recall_at_k(results, items, k)`
  - `aggregate(per_query)` → macro averages + per-type breakdown
  - `leak_counts(results, query)` → restricted chunks, wrong-tenant
    chunks, v2 intrusions
- [x] Results are just lists of `(doc_id, chunk_text)` here, so you can
      test with hand-made chunks, no index needed

**Verify:** `uv run pytest tests/test_metrics.py`
- the spec's worked example: q032, 5 results (I1, none, I2, I1-again,
  I4) → R@5 = 0.75, P@5 = 0.60
- single-item query, hit at rank 3 → R@5 = 1.0, P@5 = 0.2
- duplicate_source q036 with a hit in `member_faq` → R@5 = 1.0
- a chunk with the right quote but the **wrong doc_id** is not a hit
- unanswerable queries rejected by `aggregate` (they're scored separately)

**Checkpoint:** you can explain every number in the worked example
without looking at the code.

## Milestone 5 — Loaders for the remaining formats

- [x] `src/loaders.py`: one function per format returning `Block`s:
  - `.md`: headings from `#`, lists, paragraphs
  - `.txt`: decode (see milestone 6), headings from numbered/ALL-CAPS lines
  - `.html`: BeautifulSoup; `h1-h4` headings, `p`/`li`, tables as rows
    (boilerplate removal happens in cleaning, but tag info must survive
    to there, so keep a `tag`/`class` hint on each block)
  - `.docx`: python-docx; heading styles, numbered lists, tables as rows
  - `.rtf`: RTF-to-text library; table rows as `cell | cell`
  - `.eml`: stdlib `email`; Subject, Date, body parts
  - `.csv`: rows (only ever hits the 0-byte file here)
  - `.pdf`: dispatch to naive or layout parser by config
- [x] `src/catalog.py`: load catalog, attach metadata to each `Document`

**Verify:** `uv run pytest tests/test_loaders.py`. One test per format
against the real corpus file: loads without error, has ≥ 1 block, the
docx closure procedure has a table block containing `HCU-ACL-220`, the
card dispute docx has headings for sections 2-6, the RTF block text
contains no `\par`/`{\rtf` control words.

**Checkpoint:** all 27 files go through the loader without an uncaught
exception (the corrupt Q2 PDF raises a *caught* parse error, turned into
a decision in milestone 6).

## Milestone 6 — Cleaning, dedupe and the decision log

- [x] `src/cleaning.py`: BOM strip; UTF-8 → cp1252 fallback (record
      encoding); `ftfy` mojibake fix; line endings, NBSP, in-sentence
      tabs; PDF running header/footer removal (lines repeating in the
      top/bottom band of ≥ 50% of pages); HTML boilerplate removal; email
      quoted-line / disclaimer / address-header removal; `[DELETED: ...]`
      removal; near-empty rule (< 50 words or placeholder phrase)
- [x] `src/dedupe.py`: exact (SHA-256 of raw bytes, at load) and
      near-duplicate (word 5-gram Jaccard ≥ 0.90 on cleaned text), with
      the canonical-copy rule from the spec
- [x] Decision rules 1-8 from the spec, each setting `Decision(status,
      reason, stage, details)`; nothing ever removed from the list
- [x] `src/grade_ingestion.py` (part 1): read `runs/<id>/decisions.csv`,
      compare with `_answer_key/ingestion_expectations.csv`, print a
      per-file table and a summary; quote-survival table per parser
      (from milestone 2, now over all docs)

**Verify:**
```bash
uv run pytest tests/test_cleaning.py tests/test_dedupe.py
#   privacy notice decodes as cp1252 and contains "’" correctly;
#   debit card text has 0 mojibake sequences (e.g. no "â€™");
#   wire PDF text contains the header string 0 times (was once per page);
#   closure text contains no "[DELETED:";
#   faq.html is canonical over "faq (1).html"; wire PDF over the DOCX
uv run python src/ingest.py --parser layout --stop-after dedupe
uv run python src/grade_ingestion.py --run latest --decisions
```
Expected:
```
decisions: 27 files | cleaned 22 | dropped 4 | quarantined 1
match vs answer key: 27/27
  faq (1).html                 dropped      exact duplicate of member_faq (faq.html)       OK
  PAY-WT-004 ...docx           dropped      near-duplicate of wire_transfer_policy ...     OK
  Rate Sheet Q2 2026 ...pdf    quarantined  unreadable pdf: 0 loadable pages ...           OK
  ...
```
And with `--parser naive`: 4 more quarantined (the scans, "no text
layer"), reported as *expected differences*.

**⏸ PAUSE — read the cleaned text.** Spot-check 4-5 cleaned documents
against their `eval/ground_truth_text/` files (the FAQ, the email, the
RTF, the debit card file). Grading 27/27 decisions doesn't mean the
*text* is clean. Quote survival across all docs should now be at or
near 100% for the layout parser; list every quote that doesn't survive
and why.

**Checkpoint:** 27/27 decisions, every reason readable by a
non-engineer, quote survival table saved.

## Milestone 7 — PII scrubber

- [x] `src/pii.py`: Presidio analyzer with the spaCy model from
      `requirements.txt`; custom `PatternRecognizer`s for member,
      account, SSN (custom: the built-in rejects 9XX), phone, DOB,
      address; email built-in + README regex; `PERSON` kept only for full
      first + last names; allow-list (`1-800-4-HARBOR`, Harbor branch
      names); anonymiser replaces with `[REDACTED-<TYPE>]`; `pii_spans`
      store type/offsets/value SHA-256 only
- [x] Known out-of-the-box gaps from the setup smoke test, each needing a
      test: `HCU-004821` is only half-detected (as a low-score driver's
      licence), `7730-...` account numbers are missed, street names like
      "Birch Lane" are tagged `PERSON`, and the `example.com` inside an
      email is also flagged as a URL (merge overlapping spans so it
      becomes one `[REDACTED-EMAIL]`)
- [x] Runs on **every** cleaned doc, not only confidential ones
- [x] `grade_ingestion.py` (part 2): recall per type vs
      `_answer_key/pii_inventory.csv` (118 values, 3 docs), false-positive
      list, collateral-damage check on golden quotes

**Verify:**
```bash
uv run pytest tests/test_pii.py
#   each Harbor format is redacted in a synthetic sentence;
#   "1-800-4-HARBOR ext. 4417" and "J. Okafor" are NOT redacted;
#   pii_spans contain no raw values
uv run python src/ingest.py --parser layout --stop-after scrub
uv run python src/grade_ingestion.py --run latest --pii
```
Expected: `member/account/ssn/phone/email/dob/address recall: 100%`,
`name recall: x/y` (aim for every name value in the inventory), `collateral: 0`,
`false positives: n` (listed).

**⏸ PAUSE — review false positives and missed names by hand.** A false
positive that destroys a policy fact (say, a product name tagged as a
person) is a retrieval bug; a missed name is a compliance bug. Decide per
case: allow-list, tighter rule, or accept and document. Note that the
closure procedure's worked example (Dana Whitfield) must be caught even
though the doc is only "internal".

**Checkpoint:** no inventory value appears in any scrubbed document.

## Milestone 8 — Pipeline runner and stage cache

- [x] `src/pipeline.py`: runs the stage list (load → parse → clean →
      dedupe → scrub → chunk → embed → index) with the cache-key chain from
      the spec; `--from-stage`, `--stop-after`; writes
      `runs/<run_id>/decisions.csv` and `config.json` (params, cache keys,
      model revisions, corpus file hashes, `uv pip freeze`)
- [x] `src/ingest.py`: CLI; `--parser naive|layout|all`,
      `--chunker A_fixed|B_structure|all`, `--captions offline|online`
      (`--chunker` added in milestone 9; embed/index plug into the same runner next)

**Verify:** `uv run pytest tests/test_pipeline.py`
- doc count in = doc count out at every stage (no silent skip)
- rerunning with identical params → every stage is a cache hit
- changing a chunker param → parse/clean/scrub are hits, chunk/embed/index miss

Then time it: first full layout run (slow, Docling) vs a rerun (should
take seconds).

**Checkpoint:** re-running the pipeline is cheap, and you can re-run any
single stage.

## Milestone 9 — Chunkers A and B

- [x] `src/chunking.py`: `A_fixed` (800 / 150 / whitespace backoff 50)
      and `B_structure` (heading boundaries, max 1200, min 200 merge,
      atomic tables ≤ 2000 with header repeat, section-path prefix, no
      overlap); both fill every metadata field in the spec schema, with
      correct `char_start/char_end` and pages

**Verify:** `uv run pytest tests/test_chunking.py`
- A: consecutive chunks overlap by ~150 chars; no chunk > 800; no word cut
- B: no chunk spans two headings; a table row is never split; the
  deposit rate table chunk contains its header row
- both: `Document.text[char_start:char_end]` equals the chunk text
  (minus B's prefix); IDs are deterministic across two runs
- both: for every golden quote that survived parsing, report whether it
  survived **chunking** (i.e. fits inside one chunk). A quote split
  across a chunk boundary can never be a `substring` hit.

```bash
uv run python src/ingest.py --parser layout --chunker all --stop-after chunk
```
Print chunk counts and mean/max length per chunker per parser.

**⏸ PAUSE — look at chunks.** Print the chunks for one policy doc and
one scanned table under both strategies. Does B's output look like what
you'd want to cite? Which golden quotes does A split?

## Milestone 10 — Embeddings and indexes

- [x] `src/embedding.py`: bge-small at manifest revision, CPU,
      normalised, batch 32, query prefix; warn on > 512 tokens
- [x] `src/index.py`: `VectorIndex`/`LexicalIndex` protocols;
      `ChromaIndex` (persistent, cosine, one collection per
      parser×chunker×revision, revision stored in collection metadata and
      checked on open); `BM25Index` (tokeniser per spec, filter-then-truncate,
      pickled); one shared `where` format translated by each

**Verify:** `uv run pytest tests/test_index.py`
- every stored chunk has every metadata field, correct types, no `None`
- `where={"tenant": "retail", "sensitivity_not_in": ["restricted"], "is_current": True}`
  never returns business, restricted or v2 chunks, from **both** indexes
- BM25 with a filter still returns n results when high-scoring chunks
  are filtered out
- opening a collection with a different revision in the manifest fails loudly
- BM25 tokeniser keeps `4.05%`, `$30.00`, `hcu-dsp-114` whole

```bash
uv run python src/ingest.py --parser all --chunker all --captions offline
```
Expected: 4 Chroma collections + 4 BM25 pickles; chunk counts match
milestone 9; a scan of all stored chunk texts finds **0** values from
`pii_inventory.csv`.

**Checkpoint:** D1 is essentially done: the full pipeline builds all
four indexes from a single command.

## Milestone 11 — Query path: retrieval, fusion, rerank

- [x] `src/retrieval.py`: `search(query, tenant, mode, index, filter
      options) -> results`; modes `bm25`, `vector`, `hybrid`,
      `hybrid_rerank`; per-retriever depth 50; RRF k=60 with `chunk_id`
      tie-break; top-30 to the cross-encoder (manifest revision, CPU,
      max_length 512); per-stage timings; each result carries
      `stage_scores` and full metadata for citation
- [x] A tiny CLI for poking at it:
      `uv run python src/retrieval.py "What is the fee for a stop payment?" --mode hybrid_rerank`
      prints top-5 with doc title, version, page, section and score

**Verify:** `uv run pytest tests/test_retrieval.py`
- RRF reproduces the spec's worked table exactly (c2 0.03227, c7 0.03202, c9 0.01613; the spec originally said 0.03226 by adding rounded parts)
- identical query twice → identical results (order and scores)
- `hybrid_rerank` only reorders the fused top-30 (never introduces a new chunk)

Manual smoke test, 3 queries: an exact term (q001, form number: BM25
should find it), a paraphrase (q009, "send money to another bank": vector
should), a version trap (q028: must return v3, never v2).

**⏸ PAUSE — sanity-check before the full eval.** If the smoke test
looks wrong, fix it now; the matrix will just give you 16 rows of the
same bug.

## Milestone 12 — Eval harness and the matrix

- [x] `src/evaluate.py`:
  - load golden set; per query pick the filter (query's own tenant;
    restricted excluded; superseded excluded unless the row says off)
  - score 41 queries (excluding q003 and q043-q045) with P@5/P@10/R@5/R@10
  - q003 leak check + clearance check; wrong-tenant/restricted counts
    across all results; v2-intrusion count
  - unanswerable report (top-1 rerank scores vs answerable distribution)
  - `--matrix`: rows 1-16, then row 17 (best config, superseded filter
    off, chosen mechanically: highest R@5, then R@10)
  - print a console table; write `results.json`, `results.md`,
    `per_query.csv`, `timings.json` into `runs/<run_id>/`
  - `--check-repro`: run the matrix twice, diff `results.json`, exit
    non-zero on any difference
  - refuses to run if captions mode isn't `offline` (the eval must not
    call the API)

**Verify:**
```bash
uv run python src/evaluate.py --parser layout --chunker B_structure --mode hybrid_rerank   # one row first
uv run python src/evaluate.py --matrix --captions offline
uv run python src/evaluate.py --matrix --check-repro        # → "reproducible: results identical (17 rows)"
```
Expected console shape (numbers are placeholders):
```
row parser chunker     mode           P@5   P@10  R@5   R@10  q003leak clr  wrongT restr
1   naive  A_fixed     bm25           0.xx  0.xx  0.xx  0.xx  PASS     OK   0      0
...
16  layout B_structure hybrid_rerank  0.xx  0.xx  0.xx  0.xx  PASS     OK   0      0
17  layout B_structure hybrid_rerank  (superseded filter OFF)  version_trap R@5 0.xx, v2 intrusions n
P@5 ceiling for single-item queries: 0.20
```

**⏸ PAUSE — review the results before writing anything.**
- Do the three before/after comparisons (parser, chunker, stages) point
  where you expected? If not, open `per_query.csv` and find *which*
  queries moved. That is usually more informative than the averages.
- Look at the per-type breakdown: naive vs layout should differ mostly
  on scanned_table / figure / reading_order.
- Any leak count ≠ 0 is a bug. Stop and fix it.
- Resist tuning parameters to push numbers up. If you do change one,
  record it in the report as a named experiment (before/after), not as
  the new default.

**Checkpoint:** matrix printed, `--check-repro` passes, all leak checks
pass.

## Milestone 13 — Clean re-run (D1 proof)

- [x] Delete `cache/stages/` and `index/` (keep `cache/captions/`), then
      run the full thing from scratch with no API key in the environment:

```bash
rm -rf cache/stages index
env -u ANTHROPIC_API_KEY HF_HUB_OFFLINE=1 uv run python src/ingest.py --parser all --chunker all --captions offline
env -u ANTHROPIC_API_KEY HF_HUB_OFFLINE=1 uv run python src/evaluate.py --matrix
uv run python src/grade_ingestion.py --run latest
uv run pytest
```

**Checkpoint:** same numbers as milestone 12, byte for byte (compare
`results.json`). This run's ID is the one the report cites.

## Milestone 14 — Retrieval evaluation report (assignment artifact)

`artifacts/retrieval_eval_report.md`, citing the run ID from milestone 13:

- [x] Summary: the headline numbers in 3-4 sentences ("R@5 went from X
      (naive) to Y (layout); B beat A by Z; reranking added W at a cost of
      N ms/query")
- [x] Setup: corpus, golden set (45 queries, 41 scored), metric definitions
      incl. the P@k ceiling, pinned models, how to reproduce (commands)
- [x] Ingestion: decision table (27 files), grade vs answer key, quote
      survival per parser, what the Docling spike needed (milestone 2)
- [x] PII: recall per type, false positives, collateral 0, governance
      note on captions
- [x] Results: full 17-row matrix; the three before/after comparisons as
      small tables with deltas; per-query-type breakdown; latency per stage
- [x] Access and version: leak checks, q003 clearance, superseded-filter row
- [x] Unanswerable queries: top-1 score analysis
- [x] Findings and recommendation: which configuration to take into
      Day 2 and why; failure analysis of 3-5 still-missed queries
      (from `per_query.csv`)
- [x] Limitations: small golden set, all_tokens leniency, no answer
      generation yet, caption governance, open questions from the spec

**Checkpoint:** every number in the report can be found in
`runs/<run_id>/`. Nothing typed from memory.

## Milestone 15 — High-level deck (final submission)

`artifacts/high_level_deck.md`, 5-8 slides, same format as
`../week1_day4/artifacts/high_level_deck.md` (`## Slide N: Title`, short
bullets, an ASCII diagram or table where it helps):

- [x] Slide 1: Title / framing (Harbor, Week 2 Day 1: the retrieval slice
      of the week's agent; "measure, don't guess")
- [x] Slide 2: The problem (messy corpus: scans, encodings, duplicates,
      PII, versions, tenants; RAG fails at ingestion)
- [x] Slide 3: High-level flow (the pipeline → index ← query path + eval
      diagram from the spec)
- [x] Slide 4: Architecture: stage contract, metadata, decision log,
      PII-before-embedding, caption cache + governance fence
- [x] Slide 5: Tech stack (Docling, PyMuPDF, Presidio, bge-small, Chroma,
      rank_bm25, bge-reranker, Claude Opus 5 captions, pytest, uv; pins
      in requirements.txt / model_manifest.json)
- [x] Slide 6: Results: the before/after numbers (parser, chunker,
      stages) + latency
- [x] Slide 7: Access, versions and PII: leak checks, superseded row,
      scrubber score
- [x] Slide 8: Known gaps / what's next (pgvector swap, answer
      generation + citations, no-answer threshold, router)

**Done when:** the report and deck both live under `artifacts/` and cite
the real run under `runs/`, not placeholder numbers.

## Things to watch for (beginner pitfalls)

- **Indexing the answers.** Only `corpus/` goes into the pipeline. If
  `eval/` or `_answer_key/` text ever lands in an index, every number is
  meaningless. `ingest.py` should refuse any input path outside `corpus/`.
- **Silent skips.** An `except: continue` in a loader is exactly the bug
  R1 forbids. Every exception on a document becomes a quarantine
  decision with the error text as the reason.
- **Filtering after truncating** (BM25): you get fewer results than
  asked for and don't notice. Filter first.
- **Unpinned or drifting models.** If the embedding model changes, every
  stored vector is silently wrong. The manifest revision check on
  collection open is there to catch it.
- **Paying for captions twice / non-reproducible captions.** The model
  has no temperature control, so the same image can get a different
  caption on a second call. The cache is what makes the eval
  reproducible; never run the eval in `online` mode.
- **Precision looks "bad".** With one relevant item per query, P@5 can't
  exceed 0.20. Compare configurations against each other, not against 1.0.
- **Overfitting the golden set.** 41 scored queries is small. Moving a
  parameter until the numbers improve is fitting to the test; record
  every change as an experiment.
- **PII in logs.** Debug prints of "what did the scrubber remove?" leak
  exactly what you removed. Log types, offsets and hashes only.
- **Chroma metadata types.** `None` and lists are rejected. Use `""` /
  `-1` and JSON strings, as in the schema.

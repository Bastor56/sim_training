# FDE Xlerate - Week 2, Day 1
Spec: ingestion pipeline, hybrid retrieval and retrieval eval over Harbor Credit Union's messy document set

## Business problem

This week's client is **Harbor Credit Union**: 180,000 members and a
40-person contact centre that answers the same account, card and loan
questions all day. By Friday the week builds an agent that routes each
question to the right mechanism (vector search, a knowledge graph, a
governed SQL view or an MCP tool) and cites its source every time. Today
builds the first of those mechanisms, **retrieval over Harbor's
documents**, and, more importantly, the measurement that says whether it
works.

Most client RAG projects fail at ingestion, not retrieval. Documents are
messier than anyone admits (scans with no text layer, broken encodings,
duplicates, boilerplate, PII in places nobody expected), and nobody
measures the result, so "the answers seem better" is the only evidence
anyone has. Today's goal is to be able to say something like
*"recall@5 went from 0.42 to 0.71 when we switched to heading-aware
chunking"*, from a script that anyone can re-run and get the same numbers.

Full lab text: `../../training_instructions/week2_day1.md`.

## Goal

1. A **re-runnable ingestion pipeline** (load → clean → scrub PII →
   chunk → embed → index) over `data/harbor_rag_dataset/corpus/`, which
   logs a decision (cleaned / quarantined / dropped) with a reason for
   every one of the 27 files.
2. A **query path** with lexical (BM25) and vector retrieval, fused with
   Reciprocal Rank Fusion and reranked by a cross-encoder, returning top-k
   chunks with citation metadata.
3. An **eval script** that scores the query path against the golden set
   and prints precision@k and recall@k (k = 5, 10) for a fixed matrix of
   configurations, reproducibly, so every design choice (parser, chunker,
   each retrieval stage) is backed by a number.
4. The day's write-ups: a retrieval evaluation report and a 5-8 slide
   high-level deck.

## Requirements

Restated from the lab instructions (the acceptance criteria at the end
map to these one-to-one):

- **R1 Ingestion defects handled explicitly.** Duplicates, inconsistent
  encodings, boilerplate headers/footers, near-empty files and at least
  one badly-parsing format, with a logged decision per document and never
  a silent skip.
- **R2 Swappable chunking.** Chunking is a strategy object whose
  parameters (size, overlap, boundary rule) are recorded; at least two
  strategies are compared on the same golden set.
- **R3 Chunk metadata.** Every chunk carries its source document, its
  position within it, and its tenant and sensitivity labels.
- **R4 PII scrubbed before embedding.** An embedding computed over
  unscrubbed PII cannot be un-computed once it is in the index.
- **R5 Hybrid search with fusion and reranking.** Lexical + vector
  retrieval under an explicit fusion rule, reranking the fused candidate
  set, with the metric reported with each stage on and off.
- **R6 Reproducible eval.** Runs the golden set, prints precision and
  recall at k as numbers, gives the same numbers on every run.
- **R7 Layout-aware parsing.** Scanned/image-only PDFs with tables go
  through OCR, reading-order recovery and table extraction, with figures
  captioned by a vision-capable model, before chunking. The eval reports
  P@k/R@k twice: naive text extraction vs layout-aware parsing.
- **D1-D4 Deliverables.** Re-runnable pipeline + per-document decision
  log; eval script with before/after numbers for at least one chunking or
  reranking change; retrieval evaluation report; 5-8 slide deck.

## Harbor constraints that apply today

The week's constraints, and what each one means for today's slice:

| Harbor constraint | What it forces today |
|---|---|
| Every answer names the source it came from | Every chunk carries `doc_id`, source filename, chunk index, character offsets and page, so a later answer step can cite "Wire Transfer Policy, Rev 2026-02, p.2". This can't be bolted on after indexing. |
| Policy answers quote the policy version in force | Every chunk carries `version`, `effective_date` and `superseded_by`. At query time, chunks from superseded documents are filtered out by default. Overdraft Policy v2 is in the corpus specifically to test this. |
| Members' data may not be touched by outside teams / must be traceable | PII is scrubbed before embedding; the scrub log records *what type* was removed and *where*, never the raw value. |
| Aggregate questions go through the governed SQL view | Out of scope today (Day 2+). Noted so nobody tries to answer "how many branches..." from document chunks. |
| Memory holds only what the member said this conversation | Out of scope today (no conversation yet). |

Plus one constraint of today's own making: figure captioning sends image
crops to the Claude API, i.e. **data leaves Harbor's environment**. See
"Figure captioning" below for the rules that limit this.

## Scope and non-goals

**In scope:** everything under Goal. The corpus, golden set and answer
key are provided and verified (`data/harbor_rag_dataset/README.md`,
`scripts/verify_dataset.py` passes).

**Not in scope today:**
- Generating answers with an LLM. Today stops at "top-k chunks with
  citations". Answer generation, the router, the knowledge graph, SQL and
  MCP arrive later this week.
- pgvector. Chroma is used today behind a small interface so it can be
  swapped later (see "Index interface").
- Tuning for the best possible score. The golden set has 45 queries; if
  you tune parameters until the numbers go up you are fitting to the test.
  Parameters are chosen up front, recorded, and any change is recorded in
  the report as a deliberate experiment.
- A no-answer threshold for unanswerable questions (measured today,
  enforced later; see "Unanswerable queries").

## Key concepts (short primer)

- **Chunk:** a piece of a document small enough to embed and to show as
  evidence. Retrieval returns chunks, not documents.
- **Embedding / vector search:** a model turns text into a list of
  numbers (a vector) so that texts with similar *meaning* end up close
  together. Good at paraphrases ("send money to another bank" ≈ "wire
  transfer"), weak at exact identifiers ("Form HCU-DSP-114").
- **BM25 / lexical search:** classic keyword scoring: rare words that
  appear often in a chunk score high. Strong on exact terms, form
  numbers, rates; blind to paraphrase.
- **Hybrid search + fusion:** run both, merge the two ranked lists into
  one. We use Reciprocal Rank Fusion (worked example below).
- **Reranker (cross-encoder):** a slower model that reads the query and
  one candidate chunk *together* and scores how well the chunk answers
  the query. Too slow to run over the whole index, so it runs only over
  the ~30 fused candidates.
- **Precision@k / recall@k:** of the top k chunks, how many were useful
  (precision); of everything that should have been found, how much was
  found in the top k (recall). Worked example below.
- **Golden set:** hand-labelled queries with the expected evidence. It is
  source code, because every later claim about retrieval quality depends
  on it.

## Architecture

A pipeline and a query path that meet at a single shared node, the
index. Everything left of the index is data engineering, everything
right of it is retrieval, and the eval harness is the only thing that
connects a change on the left to a number on the right.

```
                 INGESTION PIPELINE (offline, re-runnable, cached per stage)
 corpus/ (27 files)
     │
     ▼
 ┌─────────┐   ┌──────────────┐   ┌─────────────┐   ┌─────────┐   ┌──────────┐   ┌──────────────┐
 │ loader  │──▶│ cleaner +    │──▶│ PII scrubber│──▶│ chunker │──▶│ embedder │──▶│ index writer │
 │ +parser │   │ normaliser + │   │ (Presidio)  │   │ A or B  │   │ bge-small│   │              │
 │ naive | │   │ dedupe       │   └─────────────┘   └─────────┘   └──────────┘   └──────┬───────┘
 │ layout  │   └──────────────┘                                                         │
 └────┬────┘          │                                                                 │
      │ figure crops  │ every file: cleaned / quarantined / dropped + reason            │
      ▼               ▼                                                                 ▼
 ┌──────────┐   runs/<id>/decisions.csv                                  ╔═════════════════════════╗
 │ caption  │                                                            ║          INDEX          ║
 │ cache ◀─▶│ Claude API (public docs only, cache-first)                ║ Chroma (vectors+metadata)║
 └──────────┘                                                            ║ BM25 (tokens+metadata)  ║
                                                                         ╚════════════╤════════════╝
                                   QUERY PATH                                         │
 query + access filter ──┬──▶ BM25 top-50 (filtered) ───┐                             │
 (tenant, sensitivity,   │                              ├──▶ RRF k=60 ──▶ top-30 ──▶ cross-encoder ──▶ top-k
  superseded)            └──▶ vector top-50 (filtered) ─┘                  rerank      + citations
                                     ▲                                                     │
                                     │ golden queries                                      │ returned chunks
                              ┌──────┴──────────────────────────────────────────────────────▼──┐
                              │ EVAL HARNESS: golden_set.yaml → run query path per config → match│
                              │ chunks to expected quotes → P@5 P@10 R@5 R@10 → print + runs/    │
                              └──────────────────────────────────────────────────────────────────┘
```

Mermaid version for the report/deck:

```mermaid
flowchart LR
  subgraph Pipeline["Ingestion pipeline (data engineering)"]
    L[Loader + parser<br/>naive or layout-aware] --> C[Cleaner / normaliser / dedupe]
    C --> P[PII scrubber]
    P --> K[Chunker A or B]
    K --> E[Embedder<br/>bge-small, pinned]
    E --> W[Index writer]
    L -. figure crops .-> CAP[(Caption cache)]
    CAP -. cache miss, public docs only .-> API[Claude API]
  end
  W --> IDX[(INDEX<br/>Chroma + BM25<br/>chunks + metadata)]
  subgraph Query["Query path (retrieval)"]
    Q[Query + access filter] --> B[BM25]
    Q --> V[Vector]
    B --> F[RRF fusion k=60]
    V --> F
    F --> R[Cross-encoder rerank]
    R --> T[Top-k + citations]
  end
  IDX --> B
  IDX --> V
  G[Eval harness<br/>golden set] --> Q
  T --> G
  G --> N[P@k / R@k printed<br/>runs/]
```

## Component contracts

All pipeline data is plain dataclasses that serialise to JSON, so any
stage's output can be cached, inspected by hand, and fed to the next
stage later.

### Data shapes

```
Decision:
  status: "cleaned" | "quarantined" | "dropped" | "pending"
  reason: str                  # human-readable, e.g. "exact duplicate of member_faq (faq.html); identical SHA-256"
  stage: str                   # which stage made the decision: "load", "parse", "clean", "dedupe"
  details: dict                # e.g. {"canonical_doc_id": "member_faq", "sha256": "...", "word_count": 14}

Block:                         # one structural unit of a document
  type: "heading" | "paragraph" | "list_item" | "table" | "figure_caption"
  text: str                    # tables: one row per line, cells joined by " | "
  level: int | None            # heading level (1 = title)
  page: int | None             # 1-based page number when the source has pages
  section_path: list[str]      # headings above this block, e.g. ["Overdraft Policy", "4. Overdraft Fees"]
  generated: bool              # true only for model-written captions

Document:
  doc_id: str                  # from the source catalog
  source_filename: str
  source_sha256: str           # hash of the raw file bytes
  format: str                  # "pdf", "docx", "md", "html", "txt", "rtf", "eml", "csv"
  catalog: dict                # title, tenant, sensitivity, version, effective_date, superseded_by
  parser: "naive" | "layout"
  blocks: list[Block]
  text: str                    # blocks joined with "\n\n"; char offsets refer to this string
  decision: Decision
  history: list[str]           # stages this document has passed through, with their cache keys
  pii_spans: list[dict]        # after scrubbing: {type, start, end, value_sha256} - never the raw value

Chunk:
  chunk_id: str                # deterministic: "{doc_id}::{parser}::{chunker}::{index:04d}"
  text: str                    # what gets embedded, BM25-indexed and matched against golden quotes
  metadata: dict               # see "Chunk metadata schema"
  embedding: list[float] | None
```

### Stage interface

```
class DocStage(Protocol):
    name: str                          # "load", "clean", "scrub", ...
    version: str                       # bump when the stage's code changes behaviour
    params: dict                       # everything that affects output; recorded in the run
    def run(self, docs: list[Document]) -> list[Document]: ...

class Chunker(Protocol):
    name: str                          # "A_fixed" | "B_structure"
    params: dict
    def chunk(self, docs: list[Document]) -> list[Chunk]: ...
```

Rules every stage follows:

1. **Documents are never removed from the list.** A stage that rejects a
   document sets its `decision` (with reason) and passes it through;
   later stages skip anything whose status isn't `pending`/`cleaned`.
   That is what makes "never a silent skip" true by construction: the
   decision log is simply the final list of documents.
2. **Stages are pure with respect to their inputs + params.** Given the
   same input documents and params they return the same output.
3. **Each stage's output is cached** at
   `cache/stages/<stage>/<cache_key>.jsonl`, where
   `cache_key = sha256(stage name + stage version + sorted params + input cache_key)`.
   Changing the chunker's size invalidates the chunk, embed and index
   caches but not the (slow) parse cache. `--from-stage chunk` re-runs
   from a given stage.

### Index interface

```
class VectorIndex(Protocol):
    def add(self, chunks: list[Chunk]) -> None
    def query(self, vector: list[float], n: int, where: dict) -> list[tuple[chunk_id, score]]
    def count(self) -> int

class LexicalIndex(Protocol):
    def build(self, chunks: list[Chunk]) -> None
    def query(self, text: str, n: int, where: dict) -> list[tuple[chunk_id, score]]
```

`where` is one small filter format of our own (e.g.
`{"tenant": "retail", "sensitivity_not_in": ["restricted"], "is_current": True}`),
translated by each implementation: into a Chroma `where` clause for
`ChromaIndex`, and into a metadata check for `BM25Index`. Swapping to
pgvector later means writing one new class that implements `VectorIndex`;
nothing in the pipeline or query path changes.

**BM25 filtering gotcha:** `rank_bm25` has no filter support. Score every
chunk, drop the ones that fail the filter, *then* take the top n.
Filtering after truncating would return fewer than n results, and a
restricted chunk that ranked high would silently push allowed ones out.

## Source catalog (where document metadata comes from)

`_answer_key/document_metadata.csv` must never be read by the pipeline.
In a real engagement tenant, sensitivity, version and effective date come
from the client's document management system, not from guessing at the
text: inferring "is this restricted?" from content is a security bug
waiting to happen.

So the lab has its own **`config/source_catalog.csv`**, standing in for
Harbor's DMS export: `filename, doc_id, title, tenant, sensitivity,
version, effective_date, superseded_by` for each of the 27 files. It
deliberately has **no** defect or expected-decision columns (those are
what we're graded on). Its values match the dataset README's corpus table,
because that is the "DMS" this lab was given. A file with no catalog
entry is **quarantined** ("unknown provenance: no catalog entry").

## Chunk metadata schema

Chroma metadata values must be `str`, `int`, `float` or `bool` (no
`None`, no lists), so "missing" is encoded explicitly.

| Field | Type | Example | Why it exists |
|---|---|---|---|
| `chunk_id` | str | `overdraft_policy_v3::layout::B::0004` | Stable ID; per-query results can be diffed across runs |
| `doc_id` | str | `overdraft_policy_v3` | Citation; golden-set matching |
| `source_filename` | str | `Overdraft_Policy_v3_FINAL.md` | Citation back to the original file |
| `title` | str | `Overdraft Policy` | Human-readable citation |
| `chunk_index` | int | `4` | Position within the document |
| `char_start`, `char_end` | int | `2210`, `3105` | Exact position in `Document.text` |
| `page_start`, `page_end` | int | `2`, `2` (`-1` = no pages) | "p.2" in a citation |
| `section_path` | str | `Overdraft Policy > 4. Overdraft Fees` | Citation; chunker B also prefixes it to the text |
| `tenant` | str | `retail` / `business` | Tenant filter |
| `sensitivity` | str | `public` / `internal` / `confidential` / `restricted` | Access filter |
| `version` | str | `3.0` (`""` if none) | "Policy version in force" |
| `effective_date` | str | `2026-01-01` (`""` if none) | Same |
| `superseded_by` | str | `overdraft_policy_v3` (`""` if current) | Superseded filter |
| `is_current` | bool | `true` | Pre-computed `superseded_by == ""`, simpler to filter on |
| `parser` | str | `naive` / `layout` | Which parse produced it |
| `chunker` | str | `A_fixed` / `B_structure` | Which strategy produced it |
| `chunker_params` | str | JSON of the params | Reproducibility |
| `contains_generated_text` | bool | `true` if a model caption is inside | An answer citing a caption must say it's model-generated |
| `pii_redactions` | int | `3` | How many redaction tokens are in this chunk |
| `embedding_model`, `embedding_revision` | str | `BAAI/bge-small-en-v1.5`, `<rev>` | Detect an index built with a different model |

## Ingestion decision policy

Applied in this order; the first rule that fires decides. Every decision
records `stage`, `reason` and `details`.

| # | Check | Stage | Decision | Reason text (pattern) | Corpus files it catches |
|---|---|---|---|---|---|
| 1 | No catalog entry | load | quarantined | `unknown provenance: no catalog entry` | none (safety net) |
| 2 | File is 0 bytes | load | dropped | `empty file (0 bytes)` | `branch_locations.csv` |
| 3 | Byte-identical (SHA-256) to an earlier-kept file | load | dropped | `exact duplicate of <canonical doc_id> (<filename>); identical SHA-256` | `faq (1).html` |
| 4 | Cannot be opened / parsed (PDF raises, 0 pages, or no page loads) | parse | quarantined | `unreadable <format>: <error>; route to manual review` | `Rate Sheet Q2 2026 - Deposits.pdf` |
| 5 | Parses, but has pages with images and no text (naive parser only) | parse | quarantined | `no text layer; needs OCR (naive parser)` | the 4 scanned PDFs, **naive runs only** |
| 6 | Fewer than 50 words after cleaning, or matches a placeholder phrase ("content to follow", "coming soon", "TBD") | clean | dropped | `near-empty: <n> words; placeholder text` | `Holiday_Schedule_2026.txt` |
| 7 | Near-duplicate of an earlier-kept doc: word 5-gram Jaccard ≥ 0.90 on cleaned, normalised text | dedupe | dropped | `near-duplicate of <canonical doc_id> (<filename>); Jaccard=<x>` | `PAY-WT-004 Wire Transfer Policy.docx` |
| 8 | Otherwise | clean | cleaned | list of fixes applied, e.g. `stripped BOM; removed running header/footer (3 pages)` | the other 22 |

**Choosing the canonical copy** of a duplicate group (rules 3 and 7):
(a) prefer a filename without a copy marker (` (1)`, `copy`, `_v2 copy`);
(b) then prefer the published/rendered format over the editable one
(pdf > html > docx > md > txt), because that is what members actually
received; (c) then the earliest effective date; (d) then filename order.
Plain alphabetical order would get *both* canonical choices wrong:
`faq (1).html` sorts before `faq.html` (space < dot) and `PAY-WT-004...docx`
sorts before `Wire_Transfer...pdf`.

**Superseded documents are not dropped.** Overdraft Policy v2 is
cleaned and indexed with `superseded_by=overdraft_policy_v3`. Filtering
happens at query time, so a "what did the old policy say?" query stays
possible later and the version-trap test has a real distractor.

**Grading.** `src/grade_ingestion.py` compares the layout-aware run's
decision log with `_answer_key/ingestion_expectations.csv` (read only by
the grader, never by the pipeline): status must match for all 27 files,
and for duplicates the reason must name the expected canonical doc. The
naive run is expected to differ on exactly the 4 scanned PDFs (rule 5);
the grader reports that as expected, not a failure.

### Cleaning operations (what "cleaned" means per defect)

| Defect | Files | Fix |
|---|---|---|
| UTF-8 BOM | `Overdraft_Policy_v3_FINAL.md` | Strip `﻿` |
| Windows-1252 encoding | `Privacy_Notice_Rev01-2026.txt` | Try strict UTF-8; on failure decode as cp1252 (confirmed with charset detection); record the encoding used |
| Mojibake inside valid UTF-8 | `Debit Card Limits and Controls.txt` | `ftfy.fix_text`; record count of changed sequences |
| CRLF / mixed line endings, NBSP, stray tabs | privacy notice, `Loan_Late_Payment...md` | Normalise to `\n`; NBSP and in-sentence tabs → space |
| Running header/footer on every page | `Wire_Transfer_Policy_Rev2026-02.pdf` | Remove lines that repeat in the top/bottom band of ≥ 50% of pages |
| HTML boilerplate (nav, cookie banner, alert bar, sidebar, promos, footer, scripts) | `faq.html`, `online-banking-help.html` | Drop `script/style/nav/header/footer/aside` and known boilerplate classes; flatten layout tables to text |
| Email structure | `FW_ RE_ Complaint...eml` | Parse with stdlib `email`; keep Subject/Date and each message body once; drop `>` quoted lines, address headers and repeated disclaimers |
| Tracked-change leftovers | `Account Closure Procedure v1.4.docx` | Remove `[DELETED: ...]` fragments entirely |
| Word tables / numbered lists | closure procedure, card dispute | Table rows → `cell | cell` lines; keep list numbering as text |
| Legacy RTF | `Savings Account Terms and Conditions.rtf` | RTF-to-text library, table rows → `cell | cell` lines, cp1252 escapes decoded |
| Two-column reading order | `Harbor_Currents_Summer_2026.pdf` | Layout-aware parser recovers column order (naive parser will interleave; that's the point) |
| Image-only scans with tables, skew, noise, stamp | the 4 scanned PDFs | Layout-aware parser: OCR + table structure; tables serialised as `cell | cell` rows under their header row |

## Parsers: naive vs layout-aware

The parser choice only affects **PDFs**. All other formats use the same
loader in both configurations, so the comparison isolates one variable.

- **Naive:** PyMuPDF `page.get_text("text")`, page by page, one
  `paragraph` block per page. On the scanned PDFs this returns nothing
  (→ quarantined by rule 5); on the newsletter it interleaves columns.
- **Layout-aware:** Docling, run locally, with OCR enabled (engine:
  `ocrmac` / Apple Vision, which Docling picks first on macOS, with
  RapidOCR as the portable fallback; engine and settings recorded in the
  run config; see `model_manifest.json`), a deskew pre-step for
  image-only scans tilted 2° or more (added after the milestone 2 spike,
  see `runs/spike/spike_notes.md`), reading-order recovery, and table
  structure recognition. Docling's output is mapped to `Block`s: section
  headers → `heading`, text → `paragraph`/`list_item`, tables →
  `table` (header row first, then one row per line), pictures →
  `figure_caption` (see next section).

**Ingestion quality diagnostic ("quote survival").** For each parser, the
grader checks every golden quote against its doc's full cleaned text
*before* chunking, using the golden set's own match rule. A quote that
doesn't survive parsing can never be retrieved, whatever the chunker or
retriever does. This separates "parsing lost it" from "retrieval missed
it" in the report. (Reads `eval/` at grading time only.)

## Figure captioning (vision model)

Some facts exist only inside an image: the auto loan sheet's bar chart
holds "Mobile app 0.6 days" and "Dealer (indirect) 2.8 days" (golden
queries q024, q025). OCR won't reliably read a chart, so figures are
captioned by a vision model.

- **Model:** `claude-opus-5` via the Anthropic SDK (pinned in
  `requirements.txt`). Sampling parameters (`temperature`, `top_p`) are
  **not accepted** by this model, so determinism cannot come from the
  request. It comes from the cache.
- **Input:** only the figure's image crop (the region Docling identifies
  as a picture), PNG, never the whole page and never document text.
- **Prompt:** versioned file `prompts/figure_caption_v1.md`, which asks
  for a factual caption listing every label and value visible in the
  chart. `PROMPT_VERSION = "v1"`.
- **Cache:** `cache/captions/<image_sha256>__<model_id>__<prompt_version>.json`
  holding `{caption, model, prompt_version, doc_id, page, created_at, usage}`.
  Lookup is cache-first; the API is called only on a miss.
- **Modes:** `--captions online` (call the API on a miss, write to
  cache) and `--captions offline` (a miss is an error, never an API
  call). **The eval always runs offline**, so it needs no network and
  no API key once the cache exists. `cache/captions/` is **committed to
  git** (small JSON files), so a fresh clone reproduces the numbers.
- **Output in the document:** a `figure_caption` block at the figure's
  place in reading order, text prefixed
  `[Figure caption, model-generated: claude-opus-5, prompt v1]`, with
  `generated=True` → chunk metadata `contains_generated_text=True`.

**Data-governance trade-off.** Captioning sends image content outside
Harbor's environment to a third-party API. That is the only step in
the pipeline where this happens, so it is fenced:
1. Only documents with catalog `sensitivity == public` are captioned.
   Pictures in any other document get a placeholder block
   (`[Figure not captioned: non-public document]`) and are logged.
2. Only picture regions are sent, and only pictures Docling classifies
   as charts/figures. Logos, stamps and signatures (e.g. the RECEIVED
   stamp and signature on the mortgage notice) are skipped and logged.
3. Every API call is logged (doc_id, page, image hash, model, tokens).
4. In production this would need Harbor's approval for the vendor (DPA,
   retention terms), or a local vision model instead; the interface
   (image → caption, cached by hash) stays the same either way.

## PII scrubbing

**Where:** after cleaning, before chunking. Scrubbing whole documents
(not chunks) means an entity is never split across a chunk boundary
and missed, and nothing unscrubbed ever reaches the embedder.

**What runs:** **all** cleaned documents, regardless of their
sensitivity label. The internal Account Closure Procedure contains a
member's name, member number, account number and address in a worked
example; a scrubber that only runs on "confidential" docs would miss it.

**How:** Presidio `AnalyzerEngine` (with the spaCy English model listed
in `requirements.txt` for names) plus custom recognisers for Harbor's
formats (from the dataset README):

| Type | Recogniser | Replacement token |
|---|---|---|
| Member number `HCU-004821` | regex `\bHCU-\d{6}\b` | `[REDACTED-MEMBER]` |
| Account `7730-0012-4471` | regex `\b7730-\d{4}-\d{4}\b` | `[REDACTED-ACCOUNT]` |
| SSN `9XX-XX-XXXX` | regex `\b9\d{2}-\d{2}-\d{4}\b` (custom: Presidio's built-in US SSN recogniser treats the 9XX range as invalid and would skip these) | `[REDACTED-SSN]` |
| Phone `(555) 555-01XX` / `555-01XX` | regexes from README | `[REDACTED-PHONE]` |
| Email | Presidio built-in + README regex | `[REDACTED-EMAIL]` |
| DOB | regex with `DOB` label context | `[REDACTED-DOB]` |
| Street address (… Lane/Street/…, Town, ME 0XXXX) | README regex | `[REDACTED-ADDRESS]` |
| Member name | spaCy `PERSON`, full first + last name only | `[REDACTED-NAME]` |

The tokens match the ones in `eval/ground_truth_text/`, so scrubbed text
lines up with ground truth.

**Must NOT be redacted** (Harbor's own details, per the README):
`1-800-4-HARBOR` and extensions, branch addresses (no member-style
town + ZIP), staff written as initial + surname (e.g. "J. Okafor"). A
small allow-list plus the "full first + last name" rule handles these.

**Deliberate choice: staff *full* names are redacted.** The answer key
treats staff as non-PII, but NER can't tell a staff member's full name
from a member's, so every full name is redacted (1 case in the corpus:
"Janet Albright" in the complaint email). Over-redacting a staff name is
the cheaper failure for a credit union than leaking a member's name. A
staff allow-list (from Harbor's HR directory) is the alternative if
answers ever need to cite who handled a case. Details in
`artifacts/findings_log.md`.

**Scoring** (`src/grade_ingestion.py`, against
`_answer_key/pii_inventory.csv`, 118 planted values across 3 docs):
- **Recall:** share of inventory values no longer present in the
  scrubbed text of their document, overall and per type. Target: 100%
  for regex types; names reported separately (NER is probabilistic).
- **False positives:** redacted spans not matching any inventory value,
  listed for manual review (e.g. NER tagging "Carrow Bay" as a person).
- **Collateral damage:** golden quotes that no longer match after
  scrubbing. Must be 0 (quotes are PII-free by construction).

The scrub log (`pii_spans`) stores type, offsets and a SHA-256 of the
value, **never the value itself**; otherwise the log becomes a PII leak.

## Chunking strategies

Both strategies read the same scrubbed `Document`s. Parameters are fixed
up front and written into every chunk's metadata and every run's config.

**A: fixed-size with overlap (`A_fixed`)**

| Param | Value | Meaning |
|---|---|---|
| `size_chars` | 800 | ≈ 200 tokens, well under both models' 512-token limit |
| `overlap_chars` | 150 | Text repeated at the start of the next chunk, so a sentence cut at a boundary appears whole in one of them |
| `boundary` | `whitespace_backoff_50` | End a chunk at the last whitespace within 50 chars of the size limit, so words aren't cut |
| `structure` | ignored | Works on `Document.text` only |

**B: structure/heading-aware (`B_structure`)**

| Param | Value | Meaning |
|---|---|---|
| `boundary` | `heading` | A new chunk starts at every heading; chunks never span two sections |
| `max_chars` | 1200 | A longer section is split at paragraph boundaries |
| `min_chars` | 200 | A tiny section is merged into the next section at the same level |
| `table_rule` | `atomic_repeat_header` | A table is kept whole up to 2000 chars; beyond that it's split by rows with the header row repeated in each piece |
| `prefix_section_path` | true | Chunk text starts with e.g. `Overdraft Policy > 4. Overdraft Fees\n`, giving BM25 and the embedder the context the chunk alone lacks |
| `overlap_chars` | 0 | Boundaries are meaningful, so no overlap |

Why we expect B to win (and must *measure* whether it does): A can cut a
table row or a policy clause in half, and a small table cell like
"4.05%" loses its "24 months" row label. B keeps rows, list steps and
sections intact. B's weak spot: documents with no detectable headings
(naive-parsed PDFs, plain text), where it degrades to paragraph packing.

Headings come from: markdown `#`, DOCX heading styles, HTML `h1-h4`,
Docling section headers, and for `.txt` a simple rule (numbered lines
like `3. Fees` or short ALL-CAPS lines).

## Embedding and indexing

- **Embedder:** sentence-transformers `BAAI/bge-small-en-v1.5` at the
  revision in `model_manifest.json`, CPU, `normalize_embeddings=True`,
  batch size 32. Queries get bge's retrieval instruction prefix
  (`"Represent this sentence for searching relevant passages: "`);
  chunks don't. Chunks longer than 512 tokens are counted and warned
  about (they'd be silently truncated).
- **Vector index:** Chroma `PersistentClient` at `index/chroma/`, cosine
  space, one collection per `(parser, chunker, embedding revision)`,
  e.g. `harbor__layout__B_structure__<rev8>`. On open, the pipeline
  checks the collection's recorded model revision against the manifest
  and refuses to query a mismatched index.
- **Lexical index:** `rank_bm25.BM25Okapi` (k1=1.5, b=0.75) over the
  same chunk texts, pickled at `index/bm25/<collection>.pkl` with chunk
  IDs and metadata. Tokeniser: the golden-set normalisation (lowercase,
  NFKC, ASCII quotes/dashes), then split so that `4.05%`, `$30.00`,
  `hcu-dsp-114` stay single tokens; no stemming, no stopword removal.

## Retrieval: modes, fusion, reranking

| Mode | What runs |
|---|---|
| `bm25` | BM25 top-10 (after filter) |
| `vector` | Vector top-10 (after filter) |
| `hybrid` | BM25 top-50 + vector top-50 → RRF → top-10 |
| `hybrid_rerank` | BM25 top-50 + vector top-50 → RRF → top-30 → cross-encoder → top-10 |

**Reciprocal Rank Fusion (k = 60).** Each list contributes
`1 / (60 + rank)` for every chunk it contains (rank starts at 1); a
chunk's fused score is the sum. It uses only ranks, so it doesn't matter
that BM25 scores (0-30ish) and cosine similarities (0-1) are on different
scales. Worked example:

| Chunk | BM25 rank | Vector rank | Fused score |
|---|---|---|---|
| c7 | 1 | 4 | 1/61 + 1/64 = 0.01639 + 0.01563 = **0.03202** |
| c2 | 3 | 1 | 1/63 + 1/61 = 0.015873 + 0.016393 = **0.03227** |
| c9 | 2 | not in list | 1/62 = **0.01613** |

Fused order: c2, c7, c9. Being ranked well by *both* retrievers beats
being first in one. Ties are broken by `chunk_id` so the order is
deterministic.

**Reranker:** cross-encoder `BAAI/bge-reranker-base` at the manifest
revision, CPU, `max_length=512`, scoring `(query, chunk text)` pairs for
the 30 fused candidates; top 10 by score are returned. Its raw score is
kept on each result (used for the unanswerable analysis).

**Access filter** (applied inside both retrievers, before truncation):
`tenant == <query tenant>` AND `sensitivity != "restricted"` AND
`is_current == true` (the last one switchable, see Experiment matrix).

**Output:** a list of `{chunk_id, rank, score, stage_scores: {bm25_rank,
vector_rank, rrf, rerank}, text, metadata}`, which is everything needed
to render a citation.

**Latency:** each stage is timed per query (BM25, vector incl. query
embedding, fusion, rerank). Timings are reported (mean and p95 ms) but
kept out of the reproducibility check, since wall-clock time never
reproduces exactly.

## Eval methodology

### Golden set

`data/harbor_rag_dataset/eval/golden_set.yaml`: 45 queries, each with
expected locations `{doc_id, quote, match}`. Labels are **quotes, not
chunk IDs**, which is what makes chunkers A and B comparable: chunk
IDs change when chunking changes, quotes don't. Query mix: 6
exact_term, 9 paraphrase, 8 scanned_table, 2 figure, 2 reading_order, 4
version_trap, 4 multi_chunk, 2 duplicate_source, 2 tenant_filter, 2
encoding, 1 pii_adjacent, 3 unanswerable.

### Matching a chunk to an expected location

Normalise both texts the same way (README): lowercase, Unicode NFKC,
curly quotes → ASCII, en/em dashes → `-`, collapse whitespace.

- `substring`: the normalised chunk contains the normalised quote.
- `all_tokens`: every whitespace-separated token of the quote occurs
  (as a substring) somewhere in the same chunk. Used for tables and the
  chart, e.g. `"24 months 4.05%"` matches a chunk containing the row
  `24 months | 3.95% | 4.00% | 4.05%`.

A chunk also has to come from the expected `doc_id`. (All_tokens is
lenient: a chunk holding the whole rate table satisfies every rate
query. That's acceptable. It measures whether the evidence was
*retrieved*; whether the right cell is *read* is an answer-generation
question for later.)

### Relevant items (what recall counts)

Expected locations are grouped **by normalised quote**. Each group is
one *relevant item*; a chunk that matches any location in the group
satisfies the item.
- **duplicate_source** (q036, q037) and the wire-copy queries (q009,
  q038): both copies carry the *same* quote → one item, either copy
  counts. The dropped copies are never indexed, so only the canonical
  copy can satisfy it, which is exactly what dedup should achieve.
- **multi_chunk** (q032-q035): each passage has a *different* quote →
  2-4 separate items; recall rewards finding all of them.

### Metric definitions

For one query with top-k results and `n_items` relevant items:

- **Recall@k** = (items satisfied by at least one of the top-k chunks) / `n_items`
- **Precision@k** = (top-k chunks that satisfy an item *not already
  satisfied by a higher-ranked chunk*) / k

The "not already satisfied" rule stops chunker A's overlap from being
rewarded: if the same quote sits in two overlapping chunks, only the
first counts.

**Worked example**, q032 (multi_chunk, 4 items: I1 Form HCU-DSP-114, I2
provisional credit, I3 45 days, I4 written notice), top 5 returned:

| Rank | Chunk | Satisfies | Counted for precision? |
|---|---|---|---|
| 1 | card_dispute::B::0002 | I1 | yes |
| 2 | wire_transfer_policy::B::0005 | nothing | no |
| 3 | card_dispute::B::0004 | I2 | yes |
| 4 | card_dispute::B::0003 | I1 again (overlap) | no, I1 already counted |
| 5 | card_dispute::B::0006 | I4 | yes |

Recall@5 = 3 items found / 4 = **0.75**. Precision@5 = 3 / 5 = **0.60**.
If I3 appears at rank 8, Recall@10 = 1.00.

**Read precision with care:** most queries have exactly one item, so
their best possible P@5 is 1/5 = 0.20 and P@10 is 0.10. Precision is
useful for *comparing* configurations, not as an absolute grade. The
report prints the ceiling next to it.

**Aggregation:** macro-average (mean of per-query values) over the
scored queries, plus a breakdown by query type, which is where parser
and chunker effects show up (e.g. scanned_table under naive vs
layout).

### Tenant, access and special queries

The eval runs as the **member-facing retail contact-centre context**:
`tenant=retail`, restricted excluded, superseded excluded. Internal and
confidential documents stay searchable. The consumer is Harbor's
contact centre, and the golden set expects answers from internal
procedures and the (scrubbed) confidential call notes (q013, q042).
That's an assumption; see Open questions.

| Query | Declares | Handling |
|---|---|---|
| q002 | `tenant: business` | Run with **its own tenant** (`tenant=business`), otherwise the same filter. Scored normally, included in averages. General rule: the query's `tenant` field is the tenant filter. |
| q003 | `access: restricted` | Run with the normal member-facing filter. **Not** in P/R averages. Scored as a **leak check**: PASS if no `fraud_monitoring_thresholds` chunk appears in the top-10. Plus one **clearance check** per matrix run: q003 re-run with restricted allowed, which must retrieve the VR-3 quote. That proves the leak check passes because of the filter, not because the doc failed to index. |
| q038, q039 | tenant_filter | Scored normally. Additionally every run counts **wrong-tenant chunks** and **restricted chunks** across all top-10 results; both must be 0. |
| q043-q045 | unanswerable, `expected: []` | Excluded from P/R averages (recall is undefined with zero items). Reported separately, see below. |

Scored queries per member-facing run: 45 − 3 unanswerable − q003 = **41**.

### Unanswerable queries

Retrieval always returns *something*, so "did it return nothing?" isn't
a useful test. Instead the report shows, for `hybrid_rerank` rows, each
unanswerable query's **top-1 rerank score** next to the distribution
of top-1 scores for answerable queries (min / median), and how many
answerable queries score *below* the highest unanswerable one. That
indicates whether a simple "no good evidence" threshold could work;
setting that threshold belongs to the answer step later in the week.
For non-rerank modes: "n/a".

### Superseded filter

Default: `is_current == true`, so Overdraft v2 chunks are never
returned. The filter-off row re-runs the best configuration with the
filter disabled and reports version_trap (q028-q031) P/R plus a
**v2-intrusion count** (how many `overdraft_policy_v2` chunks appear in
top-k). This shows what the filter buys: without it, v2's
near-identical sentences with different fees compete with v3.

## Experiment matrix

Indexes are built per `(parser, chunker)`; the retrieval mode is
query-time only, so 4 indexes serve all 16 main rows.

| Row | Parser | Chunker | Mode | Notes |
|---|---|---|---|---|
| 1-4 | naive | A_fixed | bm25, vector, hybrid, hybrid_rerank | |
| 5-8 | naive | B_structure | same 4 | |
| 9-12 | layout | A_fixed | same 4 | |
| 13-16 | layout | B_structure | same 4 | expected best config |
| 17 | best of 1-16 | | | superseded filter **off** |
| + | each row | | | q003 leak check, q003 clearance check, wrong-tenant/restricted counts |

Every row prints: P@5, P@10, R@5, R@10 (41 scored queries), leak
checks, mean/p95 latency per stage. The headline before/after
comparisons (at least one is required; the matrix gives three):

1. **Parsing:** naive → layout (same chunker, hybrid_rerank). Expect the
   biggest jump on scanned_table / figure / reading_order.
2. **Chunking:** A → B (layout, hybrid_rerank).
3. **Retrieval stages:** bm25 → vector → hybrid → hybrid_rerank (layout, B),
   showing each stage's metric gain *and* its latency cost.

"Best" (for row 17) = highest R@5, ties by R@10, decided mechanically by
the script.

## Reproducibility rules

1. **Pinned everything.** Package versions in `requirements.txt`;
   embedding and reranker revisions in `model_manifest.json`, loaded with
   `revision=` and verified at startup; caption model ID and prompt
   version in the cache key; dataset `corpus_version` and golden-set
   `version` recorded per run.
2. **Offline eval.** Model weights downloaded once, then
   `HF_HUB_OFFLINE=1`; captions `--captions offline`. The eval makes no
   network calls.
3. **Determinism.** `random`, `numpy` and `torch` seeded (seed 0); CPU
   only (no MPS/GPU nondeterminism); stable sort with `chunk_id`
   tie-breaks in every ranking; stable chunk IDs.
4. **Recorded config.** Each run writes `runs/<run_id>/config.json`
   (all stage params, cache keys, model revisions, corpus file hashes,
   `uv pip freeze` output) next to its results.
5. **Proved, not assumed.** `evaluate.py --check-repro` runs the matrix
   twice and diffs `results.json`. Must be byte-identical (timings live
   in a separate `timings.json`).

## File / folder layout

```
labs/week2_day1/
  spec.md                        # this file
  plan.md
  requirements.txt               # package pins (created separately)
  model_manifest.json            # model revisions (created separately)
  .python-version                # 3.12
  .venv/                         # uv venv, gitignored
  .gitignore                     # cache/stages/, index/ (NOT cache/captions/)
  config/
    source_catalog.csv           # stand-in for Harbor's DMS metadata export
  prompts/
    golden_dataset_prompt.md     # (existing: how the dataset was generated)
    figure_caption_v1.md         # caption prompt, versioned
  data/harbor_rag_dataset/       # provided; only corpus/ is pipeline input
  src/
    models.py                    # Decision, Block, Document, Chunk dataclasses + JSON (de)serialise
    config.py                    # paths, default params, seeds, manifest loading/verification
    catalog.py                   # source catalog loader
    loaders.py                   # per-format loaders (md, txt, html, docx, rtf, eml, csv) → Blocks
    parse_pdf_naive.py           # PyMuPDF text extraction
    parse_pdf_layout.py          # Docling → Blocks (OCR, reading order, tables, figure crops)
    captioning.py                # caption cache + Claude API client (online/offline)
    cleaning.py                  # encoding/mojibake/whitespace/boilerplate/header-footer fixes + near-empty rule
    dedupe.py                    # exact + near-duplicate detection, canonical choice
    pii.py                       # Presidio analyzer + Harbor recognisers + anonymiser
    chunking.py                  # A_fixed, B_structure
    embedding.py                 # bge-small wrapper (query prefix, normalise)
    index.py                     # VectorIndex/LexicalIndex protocols, ChromaIndex, BM25Index, filter translation
    pipeline.py                  # stage runner, stage cache, decision log writer
    retrieval.py                 # query path: filter, retrievers, RRF, rerank, timings
    golden.py                    # golden-set loader, normalisation, match rules, item grouping
    metrics.py                   # P@k, R@k, aggregation, leak checks
    ingest.py                    # CLI: build indexes for one or all (parser, chunker)
    evaluate.py                  # CLI: run the matrix, print tables, write runs/
    grade_ingestion.py           # CLI: decisions vs expectations, PII score, quote survival
  tests/
    conftest.py                  # adds src/ to sys.path, shared fixtures
    test_*.py                    # per module, see plan.md
  cache/
    captions/                    # committed: makes the eval reproducible offline
    stages/                      # gitignored: per-stage outputs
  index/                         # gitignored: chroma/ and bm25/
  runs/<run_id>/                 # decisions.csv, ingestion_grade.json, pii_report.json,
                                 # results.json, results.md, per_query.csv, timings.json, config.json
  artifacts/
    retrieval_eval_report.md     # assignment artifact
    high_level_deck.md           # 5-8 slides
```

## Setup

```bash
cd labs/week2_day1
# .venv is created with uv from .python-version (3.12); if it doesn't exist yet:
uv venv --python 3.12
uv pip install -r requirements.txt
# Anthropic key for the one-time caption step: repo-root .env (as in earlier labs).

uv run pytest                                                    # unit tests, no network
uv run python src/ingest.py --parser all --chunker all --captions offline
uv run python src/grade_ingestion.py --run latest
uv run python src/evaluate.py --matrix --captions offline
```

## Acceptance criteria

| Requirement | Met when | Evidence |
|---|---|---|
| R1 ingestion defects, logged decisions | All 27 corpus files appear in `decisions.csv` with status + reason; layout run matches `ingestion_expectations.csv` 27/27 (22 cleaned, 4 dropped, 1 quarantined); duplicate reasons name the right canonical doc; naive run differs only on the 4 scanned PDFs | `runs/<id>/decisions.csv`, `ingestion_grade.json`; `test_pipeline.py` asserts doc count in = doc count out |
| R2 swappable chunking, params recorded, 2 compared | `A_fixed` and `B_structure` implement one `Chunker` interface; params in every chunk's metadata and in `config.json`; both appear in the matrix on the same golden set | Matrix rows 9-16; `test_chunking.py` |
| R3 chunk metadata | Every chunk in every collection has all schema fields, non-null | `test_index.py` checks every stored chunk |
| R4 PII before embedding | Scrub stage precedes chunking; 100% recall on regex PII types; names reported; 0 collateral golden-quote damage; no inventory value found in any stored chunk text | `pii_report.json`; `test_pii.py`; index-wide inventory scan in `grade_ingestion.py` |
| R5 hybrid + fusion + rerank, each stage on/off | RRF k=60 implemented and unit-tested; 4 modes in the matrix with P/R and latency per stage | Matrix; `test_retrieval.py` (RRF worked example) |
| R6 reproducible eval printing P@k/R@k | `evaluate.py` prints P@5/P@10/R@5/R@10; `--check-repro` gives identical results twice, offline | Console output, `results.json`; `test_metrics.py` (worked example above) |
| R7 layout-aware parsing + captions, naive vs layout reported | 4 scanned PDFs parsed with OCR + tables; bar chart captioned via cache; matrix reports both parsers on the same golden set; quote-survival table per parser | Matrix rows 1-8 vs 9-16; `cache/captions/`; `ingestion_grade.json` |
| Harbor: version in force | Superseded filter on by default; row 17 shows the effect | Matrix row 17 |
| Harbor: access | 0 restricted and 0 wrong-tenant chunks in any member-facing top-10; q003 clearance check retrieves VR-3 | Leak-check columns |
| D1 pipeline + decision log | `ingest.py` re-runs end-to-end from a clean checkout (+ caption cache) | Plan milestone 13 (clean re-run) |
| D2 eval script + before/after | At least the three before/after comparisons printed | `results.md` |
| D3 retrieval evaluation report | `artifacts/retrieval_eval_report.md` with real numbers from a named run | File |
| D4 deck | `artifacts/high_level_deck.md`, 5-8 slides, prior days' format | File |

## Open questions / assumptions

1. **Member-facing vs agent-facing.** The spec treats the eval user as
   the retail contact-centre context (internal + confidential allowed,
   restricted excluded), because the golden set expects internal and
   scrubbed-confidential answers. A truly member-facing channel should
   probably also exclude `internal`/`confidential`; that would make
   q001, q004, q007, q008, q013-q015, q032-q034 and q042 unanswerable by
   design. Revisit when the router is built.
2. **Source catalog** duplicates the answer key's metadata columns by
   hand, standing in for a DMS. The alternative (inferring labels from
   text) is deliberately rejected.
3. **Canonical-copy rule** (published format beats editable) is a
   defensible convention that reproduces the answer key's choices; a
   client might prefer "most recently modified".
4. **Near-empty threshold** (50 words) sits well below the smallest real
   document (≈ 210 words, the Q3 rate sheet) and well above the holiday
   placeholder (≈ 15 words).
5. **Docling OCR quality on the worst scan** (mortgage notice, 150 dpi,
   3° skew, stamp) is the biggest technical risk; the plan tests it
   first.

# FDE Xlerate - Week 2, Day 1
High-level deck: grounded retrieval over Harbor Credit Union's documents (the first slice of the week's agent)

## Slide 1: Title / Framing
- **Client: Harbor Credit Union.** 180,000 members, a 40-person contact centre answering the same
  account, card and loan questions all day, and a hard rule: every answer must be traceable to its source.
- This week builds an agent that routes each question to vector search, a knowledge graph, a governed
  SQL view or an MCP tool. **Today is the document-retrieval slice**: ingestion, hybrid search, and
  the evaluation that proves whether it works.
- The principle: **measure, don't guess.** Every design choice (parser, chunker, each retrieval
  stage) is accepted or rejected on a number from a reproducible eval, not on "the answers seem better".

## Slide 2: The Problem
- Most client RAG projects fail at **ingestion**, not retrieval: the documents are messier than anyone
  admits, and nobody measures the result.
- Harbor's 27-file corpus, deliberately messy:
  - **4 image-only scanned PDFs** with tables and a chart: no text layer at all
  - a **two-column** newsletter whose text comes out interleaved
  - **Windows-1252** text, **mojibake** ("â€™"), legacy **RTF**, HTML buried in boilerplate
  - exact and near **duplicates**, an empty file, a placeholder, a **corrupt** PDF
  - **118 planted PII values** (SSNs, account numbers, names), including in an "internal" procedure
  - a **superseded policy version**, a **business-tenant** doc and a **restricted** fraud doc
- Harbor's constraints turn these into requirements: cite every source, answer from the policy version
  in force, and keep member data out of anything that leaves the system.

## Slide 3: High-Level Flow
```
          INGESTION (offline, cached per stage)                QUERY PATH (per question)

 corpus/ ─▶ load ─▶ clean ─▶ dedupe ─▶ PII ─▶ chunk ─▶ embed          question
 27 files   parse    fix      exact +   scrub  A or B    bge-small        │  filter: tenant,
            (naive   defects  near dup  (all          │                  │  not restricted,
            or OCR)  │        │         docs)          ▼                  ▼  current version
              └──────┴── decision log ──┘       ┌──────────────┐   ┌──────┴──────┐
              cleaned / dropped / quarantined   │    INDEX     │◀──┤ BM25 │vector│
              + reason, for every file          │ Chroma + BM25│   └──┬───┴──┬───┘
                                                └──────────────┘      RRF fusion
                                                                          │
                          EVAL HARNESS ── 45 golden queries ──▶  rerank (optional)
                          P@k / R@k per config  ◀── top-10 + citations ──┘
```
- **The index is the single shared node.** Everything left of it is data engineering; everything
  right of it is retrieval.
- **The eval harness is the only thing connecting a change on the left to a number on the right.**
  It runs 16 configurations (2 parsers × 2 chunkers × 4 retrieval modes) plus a filter-off check.

## Slide 4: Architecture: what makes it trustworthy
- **Stage contract.** Every stage takes and returns documents plus metadata, and is cached under a
  chained key (`sha256(stage, version, params, previous key)`). Change the chunker and only chunking
  reruns; a rerun takes under a second.
- **No silent skips, by construction.** A document can't be dropped without a reason (the data type
  refuses it), the runner fails if any file is undecided, and every kept document must produce chunks.
- **Metadata on every chunk:** source file, character offsets, page, section path, tenant,
  sensitivity, version, effective date, superseded-by, parser, chunker and embedding revision. That's
  what makes filtering and citation possible; neither can be bolted on after indexing.
- **PII scrubbed before embedding**, on every document regardless of its label. The scrub log keeps
  only type, position and a hash, never the value.
- **Caption fence.** Chart images are the only data that leaves the environment: public documents
  only, real figures only (a signature was blocked), every call logged, captions cached, so the eval
  never calls an API.
- **Reproducible end to end:** pinned packages and model revisions, CPU-only seeded models, offline
  by default. A clean rebuild gave a byte-identical `results.json`.

## Slide 5: Tech Stack
| Layer | Choice | Why |
|---|---|---|
| Layout-aware parsing | **Docling** 2.130.0 (Apple Vision OCR, TableFormer) + deskew ≥ 2° | runs locally; recovers scanned tables and reading order |
| Naive baseline | **PyMuPDF** text layer | the "before" in the parsing comparison |
| Figure captions | **Claude** (`claude-opus-5`), disk-cached | chart values exist only in the image |
| Cleaning | ftfy, charset-normalizer, striprtf, BeautifulSoup, python-docx | one fix per known defect, each logged |
| PII | **Presidio** + spaCy `en_core_web_lg` + Harbor recognisers | out of the box it missed Harbor's formats |
| Embeddings / reranker | **bge-small-en-v1.5** / **bge-reranker-base**, pinned revisions | local, CPU, deterministic |
| Index | **Chroma** (vector, cosine) + **rank_bm25** (lexical), behind one interface | swapping to pgvector later is one class |
| Fusion | Reciprocal Rank Fusion, k = 60 | uses ranks, so BM25 and cosine scores never need calibrating |
| Tooling | uv (Python 3.12), pytest (130 tests) | pins in `requirements.txt` / `model_manifest.json` |

## Slide 6: Results: three before/after comparisons
Run `runs/20260925-114234_eval/`, 41 scored queries (1 query = 0.024 of R@5):

| Change | R@5 before → after | What moved |
|---|---|---|
| **Parsing:** naive → layout-aware | **0.585 → 0.902 (+0.317)** | scanned tables, chart, two-column: 0.00 → 1.00 (12 queries) |
| **Chunking:** fixed A → structure B | 0.872 → 0.902 (+0.030) | paraphrase 0.56 → 0.67, multi-part questions |
| **Stages:** BM25 → vector | 0.756 → 0.902 | paraphrases BM25 can't match on keywords |
| **Stages:** vector → hybrid → + rerank | 0.902 → 0.902 → 0.902 | 5 queries move, and they cancel out |

| Mode (layout, B) | Mean latency / query |
|---|---|
| BM25 | 0.2 ms |
| vector | 6.3 ms |
| hybrid | 6.5 ms |
| hybrid + rerank | **1,491 ms** |

- **Parsing is the decision that matters.** Without OCR, 12 of 41 questions can't be answered at all.
- **The reranker didn't earn its latency on this set** (and it hurt on naive parsing, 0.634 → 0.585).
  Recommendation: hybrid by default, reranker as a measured option.

## Slide 7: Access, versions and PII
- **Access filters held in all 17 configurations:** 0 wrong-tenant chunks, 0 restricted chunks; the
  restricted fraud doc stays hidden from member queries (PASS ×17) but is found with clearance (OK ×17).
- **The version trap:** with the superseded filter off, **39 Overdraft v2 chunks** reach the
  top-10s, and the reranker scores v2's old fee clause *above* v3's. Recall still reads 1.00 (v3
  is also found), so **the metric can't see this risk**. It's enforced as a filter and monitored as an
  intrusion count.
- **PII: 118/118 planted values removed**, 0 golden quotes damaged, nothing in any index. One
  deliberate over-redaction: a staff member's full name (the recogniser can't tell staff from members).
- **Ingestion: 27/27 decisions** match the answer key; golden quotes surviving parsing: **50/50**
  (layout) vs 38/50 (naive).

## Slide 8: Known gaps / What's next
- **Unanswerable questions:** no retrieval score threshold works. "Prepayment penalty on an *RV*
  loan?" outscores 12 real questions by matching the *auto* loan sheet. Declining to answer belongs in
  the answer step.
- **Remaining misses are about how questions are phrased**, not ingestion: slang ("formal gripe") and
  multi-part questions. Next: query rewriting or multi-query retrieval, and grouping by document.
- **The golden set is small (41 queries) and lenient** (`all_tokens` counts a whole table as a hit for
  any cell), and it may under-label (q007's FAQ answer). Grow it before trusting small deltas.
- **Next in the week:** answer generation with citations and version quoting, then the router across
  vector search, knowledge graph, governed SQL view and MCP tools, and a swap to pgvector if Harbor
  standardises on Postgres.
- **Governance to settle with Harbor:** vendor approval for captioning (or a local vision model), the
  staff-name redaction policy, and the contact-centre eval persona (internal and confidential docs
  searchable).

# Retrieval Evaluation Report: Harbor Credit Union document retrieval

**Week 2, Day 1 | 2026-09-25**
Cited runs: eval `runs/20260925-114234_eval/`, ingestion `runs/20260925-114231_layout_B_structure/`
(naive comparison: `runs/20260925-114204_naive_B_structure/`). Metrics, decisions, quote survival,
PII recall and latency are all in those folders. The rest have their own sources:
- the parsing spike: `runs/spike/spike_notes.md`
- chunk examples: `runs/chunk_review.md`
- caption call and tokens: `cache/captions/calls.jsonl`
- single-query smoke results (q001, q009, q028 v2 vs v3 scores): `tests/test_retrieval.py` and
  `artifacts/findings_log.md`

---

## 1. Summary

- **Layout-aware parsing is the decision that matters.** Moving from naive text extraction to
  layout-aware parsing (Docling OCR + table structure + figure captions) raised **recall@5 from
  0.585 to 0.902** (B_structure chunking, hybrid + rerank). The gain comes entirely from the 12
  queries whose answers live in scanned tables, a chart and a two-column newsletter: all 0.00 before,
  all 1.00 after.
- **Structure-aware chunking helped modestly.** B_structure beat A_fixed, R@5 **0.872 → 0.902**
  (layout, hybrid + rerank), with the gain in paraphrase and multi-part questions. That's about one
  query's worth on a 41-query set.
- **Vector search does most of the retrieval work; the reranker didn't earn its cost here.**
  BM25 → vector took R@5 from 0.756 to 0.902. Hybrid fusion and cross-encoder reranking then left R@5
  unchanged at 0.902, while reranking added **~1.5 s per query** (vector search: ~7 ms).
- **Access controls held in every one of the 17 configurations**: no wrong-tenant, restricted or
  superseded chunk was ever returned, and the restricted document was found only when access allowed
  it. The run is reproducible byte for byte from a clean rebuild with no network access.

**Recommendation for Day 2:** layout-aware parsing + B_structure chunking + **hybrid retrieval
(BM25 + vector, RRF)** as the default, with the **superseded-version filter always on**. Keep the
reranker as a measured option, not a default, until a larger golden set shows it pays for its
latency (section 8).

---

## 2. Setup

**Corpus.** 27 files of Harbor documentation (policies, procedures, rate and fee sheets, FAQs,
contact-centre scripts, a call-notes export, an email thread), with deliberate defects: 4 image-only
scanned PDFs with tables and a chart, a two-column PDF, Windows-1252 and mojibake text, legacy RTF,
HTML boilerplate, exact and near duplicates, an empty file, a placeholder file, a corrupt PDF, 118
planted PII values, a superseded policy version, a business-tenant document and a restricted document.

**Golden set.** 45 queries (`eval/golden_set.yaml`, v1) labelled as *document + quote*, not chunk
IDs, so the same labels score any chunking strategy. **41 are scored**: the 3 unanswerable queries
are analysed separately (section 7) and q003 (restricted) is a leak check (section 6). Each query
runs as a member-facing contact-centre request: its own tenant, restricted documents excluded,
superseded versions excluded.

**Metrics.**
- **Recall@k:** the share of a query's expected passages found in the top k.
- **Precision@k:** the share of the top k that are useful, crediting each expected passage once, so
  overlapping chunks aren't rewarded twice.
- **Precision ceiling:** most queries have one expected passage, so **P@5 can't exceed 0.20** for
  them. The mean P@5 ceiling across the 41 queries is **0.239**, so precision is for comparing
  configurations, not an absolute grade.
- **Scale:** one query is worth 0.024 of R@5, so differences under ~0.05 are one or two queries.
- A chunk matches if it comes from the expected document and contains the quote (`substring`), or,
  for table rows and the chart, every token of it (`all_tokens`).

**Pinned components** (`requirements.txt`, `model_manifest.json`): Docling 2.130.0 (Apple Vision OCR),
PyMuPDF (naive baseline), Presidio + spaCy en_core_web_lg (PII), bge-small-en-v1.5 embeddings at a
pinned revision, bge-reranker-base cross-encoder at a pinned revision, Chroma (vector) + rank_bm25
(lexical), RRF k=60, rerank over the fused top 30. Figure captions: `claude-opus-5`, cached on disk.

**Reproduce** (from `labs/week2_day1/`, no API key or network needed):
```bash
uv run python src/ingest.py --parser all --chunker all   # 4 indexes; ~1 min cold
uv run python src/grade_ingestion.py --run latest         # decisions, quote survival, PII
uv run python src/evaluate.py --matrix --check-repro      # 17 rows, twice, must be identical
uv run pytest                                             # 130 tests
```
Milestone 13 deleted every cache and index, rebuilt from the raw corpus, and got a `results.json`
**byte-identical** to the earlier run.

---

## 3. Ingestion

**Decisions: 27/27 match the answer key** (22 cleaned, 4 dropped, 1 quarantined). Every file gets a
logged decision with a reason, and the pipeline refuses to finish if any file is left undecided or a
kept file yields no chunks.

| File | Decision | Reason (from `decisions.csv`) |
|---|---|---|
| faq (1).html | dropped | exact duplicate of member_faq (faq.html); identical SHA-256 |
| PAY-WT-004 Wire Transfer Policy.docx | dropped | near-duplicate (Jaccard=0.96) of wire_transfer_policy (the PDF) |
| branch_locations.csv | dropped | empty file (0 bytes) |
| Holiday_Schedule_2026.txt | dropped | near-empty: 15 words; placeholder text ("content to follow") |
| Rate Sheet Q2 2026 - Deposits.pdf | quarantined | unreadable pdf (Docling conversion failed); route to manual review |
| 4 scanned PDFs | cleaned | OCR + table extraction on image-only scan; mortgage notice deskewed −3.0° |
| Privacy_Notice_Rev01-2026.txt | cleaned | decoded as cp1252 (not valid UTF-8; detector guessed cp775) |
| Debit Card Limits and Controls.txt | cleaned | repaired 19 mojibake sequences |
| Savings Account Terms and Conditions.rtf | cleaned | converted legacy RTF to text |
| faq.html, online-banking-help.html | cleaned | removed 50 boilerplate blocks each (nav, cookie banner, sidebar, footer) |
| FW_ RE_ Complaint ... .eml | cleaned | unquoted 15 reply lines; removed 10 address-header lines, 3 disclaimers, 1 repeated block |
| Account Closure Procedure v1.4.docx | cleaned | removed 3 tracked-change leftovers ("[DELETED: ...]") |
| Overdraft_Policy_v3_FINAL.md | cleaned | stripped UTF-8 BOM |
| Overdraft_Policy_v2.md | cleaned | indexed, but flagged superseded by v3 (filtered at query time) |
| 8 others | cleaned | whitespace normalised, or no defects found |

**Quote survival** (is each golden quote still in the cleaned text, before chunking? A quote lost
here can never be retrieved):

| Parser | Survived | Lost |
|---|---|---|
| layout-aware | **50/50** | none |
| naive | **38/50** | the 4 scans are quarantined (no text layer): 8 table + 2 chart quotes; the newsletter's 2 quotes are broken by interleaved columns |

**What needed engineering** (details in `runs/spike/spike_notes.md` and `artifacts/findings_log.md`):
- **Skew broke a table silently.** On the mortgage notice (3° skew) both golden quotes "survived",
  yet **0 of 7 table rows were correct**: the APR column had shifted down one row. The lenient
  `all_tokens` match couldn't see it, so the spike added an exact-row check. Deskewing pages tilted
  ≥ 2° fixed it (6/7 rows). Deskewing smaller tilts cost OCR accuracy ("ATM" became "AT"), hence the
  threshold.
- **Encoding detection guessed wrong** (cp775 for a Windows-1252 file). The loader now tries UTF-8,
  then Windows-1252, and only then trusts the detector.
- **The member's complaint existed only as a quoted reply.** Stripping `>` lines, as first
  specified, would have deleted it, so quoted lines are unquoted, then de-duplicated.
- **Canonical copies:** plain filename order would have kept the wrong copy of both duplicate pairs.
  The rule prefers no copy marker, then the published format.
- **Known limitation:** Docling's reading order on the two-column newsletter is only partly right
  (one sentence lands in the wrong article, and two lines are spliced mid-sentence). Both golden
  quotes survive, so scores are unaffected, but a generated answer quoting that passage could be
  garbled.

---

## 4. PII scrubbing

Scrubbing runs on **every** kept document before chunking and embedding, whatever its sensitivity
label. An embedding computed over PII can't be un-computed later.

| Type | Caught | | Type | Caught |
|---|---|---|---|---|
| name | 15/15 | | email | 18/18 |
| member number | 15/15 | | phone | 14/14 |
| account number | 15/15 | | date of birth | 13/13 |
| street address | 15/15 | | SSN | 13/13 |

**118/118 planted values caught; none appears in any index.** Collateral damage: **0** (all 50
golden quotes survive scrubbing). The "internal" Account Closure Procedure's worked example (member
name, member number, account number, address) is caught *because* scrubbing ignores sensitivity labels.

- **Harbor-specific recognisers were required.** Out of the box, Presidio half-matched `HCU-`
  member numbers, missed `7730-` account numbers, rejected 9XX SSNs as invalid, and tagged the street
  "Birch Lane" as a person.
- **Redactions beyond the inventory: 1, deliberate.** Staff full names are redacted too ("Janet
  Albright" in the complaint email). The name recogniser can't tell staff from members, and for a
  credit union over-redacting a staff name is the cheaper failure. A staff allow-list from Harbor's HR
  directory is the alternative if answers must cite who handled a case.
- The scrub log stores type, position and a SHA-256 of each value, never the value itself.

**Governance note on captions.** Figure captioning is the only step that sends data outside Harbor:
one chart crop from a *public* document, sent once to `claude-opus-5` (496 input / 238 output
tokens). Non-public documents are never captioned. Pictures without a printed "Figure N." caption
(here, a manager's signature) are never sent. Every decision is logged, and the caption is cached so
the eval never calls the API. In production this step needs vendor approval, or a local vision model
behind the same interface.

---

## 5. Retrieval results

### Full matrix (41 scored queries; P@5 ceiling 0.239)

| Row | Parser | Chunker | Mode | P@5 | P@10 | R@5 | R@10 |
|---|---|---|---|---|---|---|---|
| 1 | naive | A_fixed | bm25 | 0.127 | 0.068 | 0.514 | 0.545 |
| 2 | naive | A_fixed | vector | 0.137 | 0.081 | 0.571 | 0.650 |
| 3 | naive | A_fixed | hybrid | 0.141 | 0.078 | 0.569 | 0.626 |
| 4 | naive | A_fixed | hybrid_rerank | 0.141 | 0.078 | 0.579 | 0.610 |
| 5 | naive | B_structure | bm25 | 0.127 | 0.071 | 0.488 | 0.545 |
| 6 | naive | B_structure | vector | 0.146 | 0.085 | 0.585 | 0.675 |
| 7 | naive | B_structure | hybrid | 0.156 | 0.081 | 0.634 | 0.642 |
| 8 | naive | B_structure | hybrid_rerank | 0.146 | 0.085 | 0.585 | 0.691 |
| 9 | layout | A_fixed | bm25 | 0.180 | 0.100 | 0.782 | 0.846 |
| 10 | layout | A_fixed | vector | 0.195 | 0.110 | 0.864 | 0.943 |
| 11 | layout | A_fixed | hybrid | 0.200 | 0.107 | 0.862 | 0.919 |
| 12 | layout | A_fixed | hybrid_rerank | 0.200 | 0.112 | 0.872 | 0.951 |
| 13 | layout | B_structure | bm25 | 0.180 | 0.098 | 0.756 | 0.813 |
| **14** | **layout** | **B_structure** | **vector** | **0.210** | **0.115** | **0.902** | **0.968** |
| 15 | layout | B_structure | hybrid | 0.210 | 0.110 | 0.902 | 0.935 |
| 16 | layout | B_structure | hybrid_rerank | 0.210 | 0.112 | 0.902 | 0.959 |
| 17 | layout | B_structure | vector, **superseded filter OFF** | 0.205 | 0.115 | 0.878 | 0.968 |

### Before/after 1: parsing (B_structure, hybrid_rerank)

| Parser | R@5 | R@10 | P@5 |
|---|---|---|---|
| naive | 0.585 | 0.691 | 0.146 |
| layout-aware | **0.902** | **0.959** | **0.210** |
| **Δ** | **+0.317** | **+0.268** | +0.064 |

### Before/after 2: chunking (layout, hybrid_rerank)

| Chunker | R@5 | R@10 | P@5 |
|---|---|---|---|
| A_fixed (800 chars, 150 overlap) | 0.872 | 0.951 | 0.200 |
| B_structure (headings, whole tables, section prefix) | **0.902** | **0.959** | **0.210** |
| **Δ** | **+0.030** | +0.008 | +0.010 |

Neither chunker split any golden quote: A's 150-character overlap guarantees every ≤20-word quote
sits whole in some window. B's advantage is ranking. A's windows mix sections (its overdraft-fee chunk
runs from section 3 into a mid-sentence cut in section 5) and cut table rows in half (the Q3 rate
sheet's Money Market row loses its APY to the next chunk). B returns one cleanly bounded section with
its heading path. See `runs/chunk_review.md`.

### Before/after 3: retrieval stages (layout, B_structure)

| Mode | R@5 | R@10 | P@5 | Mean / p95 latency per query |
|---|---|---|---|---|
| bm25 | 0.756 | 0.813 | 0.180 | 0.2 / 0.3 ms |
| vector | **0.902** | **0.968** | 0.210 | 6.3 / 7.0 ms |
| hybrid (RRF) | 0.902 | 0.935 | 0.210 | 6.5 / 6.8 ms |
| hybrid + rerank | 0.902 | 0.959 | 0.210 | **1,490.7 / 1,781.8 ms** |

Only **5 queries** change between vector, hybrid and hybrid + rerank, and their effects cancel:
the reranker rescues some (q008 moves into the top 10, q019 back into the top 5 vs hybrid) and demotes
others (q013, q034; see section 8). The smoke tests show each stage's purpose:
- BM25 finds exact identifiers (q001 "Form HCU-DSP-114": rank 1 in every mode).
- Vector finds paraphrases (q009 "send money to another bank": BM25 misses it entirely, vector ranks it 1st).
- On this golden set, the fused and reranked lists end up no better than vector alone.

On the naive parser, reranking **hurt**: R@5 0.634 (hybrid) → 0.585 (rerank). With the scans
missing, the candidate pool is worse, and the cross-encoder promotes plausible-but-wrong chunks.

### Recall@5 by query type (hybrid_rerank)

| Type | n | naive / A | naive / B | layout / A | layout / B |
|---|---|---|---|---|---|
| scanned_table | 8 | 0.00 | 0.00 | 1.00 | 1.00 |
| figure | 2 | 0.00 | 0.00 | 1.00 | 1.00 |
| reading_order | 2 | 0.00 | 0.00 | 1.00 | 1.00 |
| paraphrase | 9 | 0.56 | 0.56 | 0.56 | **0.67** |
| multi_chunk | 4 | 0.69 | 0.75 | 0.69 | 0.75 |
| exact_term | 5 | 1.00 | 1.00 | 1.00 | 1.00 |
| version_trap | 4 | 1.00 | 1.00 | 1.00 | 1.00 |
| tenant_filter, encoding, duplicate_source | 2 each | 1.00 | 1.00 | 1.00 | 1.00 |
| pii_adjacent | 1 | 1.00 | 1.00 | 1.00 | 1.00 |

Parsing moves only the three scan-related types. Chunking moves only paraphrase and multi_chunk.
That's the separation the matrix was designed to show.

---

## 6. Access control and policy versions

| Check (every one of the 17 rows) | Result |
|---|---|
| q003 leak check: the restricted fraud-thresholds doc never appears for a member-facing query | **PASS ×17** |
| q003 clearance: with restricted access allowed, the same query finds it | **OK ×17**, which proves the filter (not a missing doc) is what hides it |
| Wrong-tenant chunks across all top-10s (incl. the 2 tenant_filter queries) | **0** |
| Restricted chunks across all top-10s | **0** |
| Superseded (Overdraft v2) chunks, filter on | **0** |

**Row 17 switches the superseded filter off** (applied to row 14, the best configuration, chosen
mechanically by highest R@5 then R@10). **39 Overdraft v2 chunks** then appear across the top-10s,
and overall R@5 drops 0.902 → 0.878. Yet version_trap recall stays 1.00, because recall only asks
"was v3 found?", never "was v2 kept out?". In the smoke test the reranker scored v2's fee clause
(0.978) *above* v3's (0.949). **Relevance can't tell which version is in force, and recall can't see
the risk.** That's why "quote the policy version in force" is enforced as a metadata filter and
monitored as an intrusion count.

---

## 7. Unanswerable queries

Retrieval always returns *something*, so the question is whether a score threshold could flag "no
good evidence" (top-1 rerank score, hybrid_rerank rows):

| Row | q043 | q044 | q045 | Answerable top-1: min / median | Answerable queries scoring below the best unanswerable |
|---|---|---|---|---|---|
| 4 (naive/A) | 0.0072 | 0.014 | 0.0954 | 0.0008 / 0.6402 | 11 |
| 8 (naive/B) | 0.0024 | 0.0031 | 0.0393 | 0.0004 / 0.8085 | 11 |
| 12 (layout/A) | 0.0167 | 0.0036 | 0.5406 | 0.0008 / 0.8959 | 12 |
| 16 (layout/B) | 0.0024 | 0.0029 | 0.549 | 0.0004 / 0.9487 | 12 |

**No threshold separates them.** Two unanswerable queries score very low, but q045 ("prepayment
penalty on an RV loan?") scores 0.549, because the auto loan sheet states "no prepayment penalty" for
*auto* loans. That near-miss outscores 12 genuinely answerable queries. Declining to answer needs the
answer step (later this week) to check that the evidence actually covers the question, not a
retrieval cut-off.

---

## 8. Findings and recommendation

**Configuration for Day 2:**

| Component | Choice | Evidence |
|---|---|---|
| Parser | layout-aware (Docling + deskew ≥ 2° + cached captions) | +0.317 R@5; the only way 12 of 41 queries are answerable at all |
| Chunker | B_structure | +0.030 R@5, clean citable sections, whole tables |
| Retrieval | hybrid (BM25 + vector, RRF k=60) | ties vector at R@5 (0.902) for 0.2 ms extra; BM25 is insurance for identifiers on real traffic, where exact codes, form numbers and rates are common |
| Reranker | off by default; re-test with a larger golden set | +0.000 R@5 at ~1.5 s/query here; hurt on naive parsing |
| Filters | tenant, restricted, **superseded always on** | 0 leaks in 17 rows; 39 v2 intrusions without the version filter |

**Still-missed queries** (layout / B, hybrid_rerank; from `per_query.csv`):

| Query | What happened | Likely cause |
|---|---|---|
| q013 "After I send in a formal gripe, how soon should I hear back?" | Vector ranked the answer 6th; the reranker scored it 0.00006 and pushed it to 11th. | Slang ("gripe") plus a mixed-topic email chunk (a wire problem inside a complaint). The reranker judged it off-topic. |
| q034 "On a lost-card call with unauthorized transactions, what must the agent do...?" (3 passages) | 1 of 3 in the top 10; the other two at ranks 11-12, behind card-dispute sections. | B gives each script step its own chunk, so a 3-part answer needs 3 slots, and a neighbouring procedure competes for them. |
| q008 "If I'm fighting a charge, how fast do I get money put back...?" | Answer at rank 7; the loan policy's "Charge-Off" section ranks 1st. | "Charge" matches lexically; every candidate's rerank score is below 0.005. The reranker finds nothing convincing. |
| q007 "How long do I have to tell you about a charge I don't recognise?" | Answer (card dispute procedure) at rank 7; the FAQ "What should I do if I see a charge I don't recognise?" ranks 1st. | Arguably **a golden-set gap**: the FAQ is a reasonable answer too but isn't labelled. |
| q033 "Key steps and timelines for closing an account?" (3 passages) | 2 of 3 in the top 5; the third at rank 6. | Near miss; all three are found by rank 10. |

All five are paraphrase or multi-part questions. **The next quality work is on how questions are
phrased, not on ingestion**: query rewriting or multi-query retrieval for slang, and a larger top-k or
per-document grouping for multi-part answers.

---

## 9. Limitations

- **Small golden set.** 41 scored queries; one query = 0.024 of R@5. The chunking (+0.030) and
  reranking (±0) conclusions are one or two queries each and should be re-tested with a larger,
  independently written set. No parameters were tuned against this set: all were fixed before the
  matrix ran.
- **`all_tokens` is lenient.** A chunk holding a whole table satisfies every row-level question
  about it. The metric measures "was the evidence retrieved", not "was the right cell read". The
  mortgage table showed how misleading that can be (quotes "survived" while every row was misaligned).
- **The golden set may under-label.** q007's FAQ answer is plausibly correct but unlabelled, so some
  "misses" may be labelling gaps.
- **No answer generation yet.** Nothing here tests whether a model *uses* the retrieved evidence
  correctly, quotes the right version, or declines unanswerable questions. That's Day 2+.
- **Synthetic corpus.** Real Harbor documents will have defects this corpus didn't plant; the decision
  log and quote-survival checks are what should catch them.
- **Caption governance.** One API call sent one public chart crop outside Harbor's environment.
  Production needs vendor approval or a local vision model. OCR (Apple Vision) is also only as pinned
  as the macOS version; the portable RapidOCR fallback crashed in this environment and is unproven.
- **Open questions carried forward:** confirm the eval persona (contact-centre agent, so internal and
  confidential documents are searchable), and confirm the staff-name redaction policy with Harbor.

# Task: Build a messy document corpus and a retrieval golden set for a fictional credit union

You are building test data for a retrieval-augmented generation (RAG) lab. The data will be used to test an ingestion pipeline (clean → scrub PII → chunk → embed → index) and a hybrid search system (BM25 + vector search → fusion → reranker), and to score it with precision@k and recall@k.

Use your code execution environment to generate every file. Do not ask me clarifying questions; make sensible choices and record them in the README. Deliver everything as **one zip file** at the end.

---

## 1. The client (fictional)

**Harbor Credit Union** is a regional US credit union with 180,000 members and a 40-person contact centre that answers account, card and loan questions all day. The corpus is Harbor's internal and member-facing documentation: policies, procedures, product sheets, rate and fee schedules, FAQs, contact-centre scripts and some operational exports.

Client rules the data must support:
- Every answer must cite the source document it came from.
- Policy answers must quote the **policy version in force**, so some policies exist in multiple versions with effective dates.
- Documents carry a **tenant** label (`retail` or `business`) and a **sensitivity** label (`public`, `internal`, `confidential`, `restricted`).

All content must be realistic in tone and detail (numbers, dates, section headings, legal-ish language) and **entirely fictional**. Do not reference any real financial institution.

---

## 2. Output structure

```
harbor_rag_dataset/
├── README.md                       # what's here, how it was generated, the choices you made
├── corpus/                         # ONLY this folder is fed to the ingestion pipeline
│   └── (all corpus files, flat, see section 3)
├── eval/
│   ├── golden_set.yaml             # the query → expected-passage pairs (section 5)
│   └── ground_truth_text/          # clean reference text for every corpus doc, one <doc_id>.txt each
├── _answer_key/                    # NOT for the pipeline; used to grade ingestion decisions
│   ├── ingestion_expectations.csv  # per-file defects and expected decision
│   ├── document_metadata.csv       # doc_id, filename, title, tenant, sensitivity, version, effective_date, superseded_by
│   └── facts.yaml                  # every planted fact and where it lives
└── scripts/
    └── verify_dataset.py           # self-check script (section 6)
```

**File naming rule:** corpus filenames must look like what a real organisation would have (e.g. `Overdraft_Policy_v3_FINAL.md`, `faq (1).html`). **Never** reveal a defect in a filename (no `duplicate.html`, `corrupted.pdf`, `messy.txt`).

---

## 3. The corpus: ~26 files with deliberate defects

Create the files below. Every file's content should be substantive (roughly 400–1,500 words for text documents, 1–4 pages for PDFs) unless the defect is that it is empty or near-empty. Spread planted facts (section 4) across them.

### 3a. Required documents

| # | Document | Format | Tenant / Sensitivity | Deliberate defect(s) |
|---|---|---|---|---|
| 1 | Overdraft Policy **v2** (effective 2024-03-01) | `.md` | retail / public | Superseded version. Contains different fee and limit values from v3. |
| 2 | Overdraft Policy **v3** (effective 2026-01-01) | `.md` | retail / public | Version in force. File starts with a UTF-8 BOM. |
| 3 | Card Dispute Procedure | `.docx` | retail / internal | Multi-step procedure spanning several sections (answers need several chunks). |
| 4 | Wire Transfer Policy | digital PDF (real text layer), 3–4 pages | retail / public | Repeated header ("Harbor Credit Union — Internal Use — Rev. 2026-02") and footer ("Page X of Y · Confidential") on every page. |
| 5 | Wire Transfer Policy (second copy) | `.docx` | retail / public | **Near-duplicate** of #4: same content, different whitespace, one extra blank line per section, and no header/footer. |
| 6 | 2026 Fee Schedule | **scanned PDF** (image only) | retail / public | Multi-row table of fees (≥15 rows: service, amount, notes). Slight rotation (1–2°) and scanner noise. |
| 7 | Q3 2026 Deposit Rate Sheet | **scanned PDF** (image only) | retail / public | Grid table: CD terms (3, 6, 12, 24, 36, 60 months) × balance tiers ($1k–$9,999 / $10k–$49,999 / $50k+) with APY in each cell, plus savings/money-market rows. Merged header cells. |
| 8 | Auto Loan Product Comparison | **scanned PDF** (image only) | retail / public | **Two-column** layout, one table (terms, APR ranges by credit tier, max LTV), and **one bar chart figure** (e.g. average approval time by channel) whose values appear **only in the chart**. |
| 9 | Mortgage & HELOC Rate Notice | **scanned PDF** (image only) | retail / public | Lower-quality scan: more skew (~3°), lower resolution (~150 dpi), a faint stamp or signature overlapping text. Contains a small table. |
| 10 | Member FAQ | `.html` | retail / public | Heavy boilerplate: nav bar, cookie banner, "Related links" sidebar, footer with legal text and copyright. The real FAQ is ~40% of the page. |
| 11 | Member FAQ (exact copy) | `.html` | retail / public | **Byte-for-byte duplicate** of #10 with a different filename (e.g. `faq (1).html`). |
| 12 | Mobile & Online Banking Help | `.html` | retail / public | Content inside nested `<div>`s, some answers inside `<table>` layouts, inline `<script>` tags. |
| 13 | Privacy Notice | `.txt` saved as **Windows-1252** (not UTF-8) | retail / public | Contains smart quotes, em dashes, ©, é, so it decodes wrongly if read as UTF-8. |
| 14 | Debit Card Limits & Controls | `.txt` (UTF-8) | retail / public | **Mojibake already baked in**: text that was double-encoded (e.g. `â€™` for ’, `â€"` for —, `Ã©` for é) in ~15 places. |
| 15 | Loan Late Payment & Collections Policy | `.md` | retail / public | Mixed line endings (CRLF and LF), non-breaking spaces, tabs in the middle of text. |
| 16 | Account Closure Procedure | `.docx` | retail / internal | Uses Word tables for the step list, plus tracked-change-style leftovers ("[DELETED: ...]") in the text. |
| 17 | Lost/Stolen Card: Contact Centre Script | `.md` | retail / internal | Agent script with dialogue, bracketed prompts, a compliance disclosure to read aloud. |
| 18 | Contact Centre Call Notes, August 2026 | `.txt` | retail / confidential | **Heavy PII**: 12–15 call-note entries with fictional member names, member numbers, account numbers, SSNs, phone numbers, emails, street addresses and dates of birth. Also contains one genuine operational fact (e.g. a known outage workaround) that a golden query targets. |
| 19 | Member Complaint Email Export | `.eml` or `.txt` export with email headers | retail / confidential | PII in headers, signatures and quoted replies (`>` lines), forwarding chains and repeated disclaimers. |
| 20 | Savings Account Terms & Conditions | `.rtf` (legacy) | retail / public | **Badly-parsing format**: RTF control words, a font table, and some content in RTF tables. |
| 21 | Member Newsletter, Summer 2026 | digital PDF, **two-column** layout with text layer | retail / public | **Reading-order trap**: naive extraction interleaves left and right columns line by line. Contains 1–2 facts (e.g. a new branch opening date, a promotional rate end date). |
| 22 | Business Account Fee Guide | `.md` | **business** / public | Same topics as retail docs (overdraft, wires) but **different values**, to test tenant filtering. |
| 23 | Fraud Monitoring Thresholds | `.md` | retail / **restricted** | Internal thresholds that must never appear in member-facing answers (tests sensitivity filtering). |
| 24 | Holiday Schedule 2026 | `.txt` | retail / public | **Near-empty**: only a title, a date and "Content to follow — see intranet." |
| 25 | Branch Locations | `.csv` | retail / public | **Zero bytes** (completely empty file). |
| 26 | Q2 Rate Sheet (truncated) | `.pdf` | retail / public | **Corrupted**: a real PDF truncated partway through so it cannot be opened. |

You may add 2–4 more documents if it improves realism or coverage (e.g. a Share Certificate disclosure or a Credit Card Rewards FAQ). Record any additions in the metadata and answer key.

### 3b. How to make the scanned PDFs (#6–#9) genuinely image-only

1. Render the page content (text, tables, chart) as a normal PDF, or directly as an image, using e.g. `reportlab` + `matplotlib` for the chart.
2. Rasterise each page to an image (e.g. PyMuPDF / `pdf2image`) at 200 dpi (150 dpi for #9).
3. Degrade with PIL/numpy: slight rotation, Gaussian noise, slight blur, off-white background, uneven contrast. Keep it **readable by OCR**; the goal is realistic, not destroyed.
4. Re-assemble the images into a PDF with **no text layer** (e.g. `img2pdf` or PIL `save(..., save_all=True)`).
5. **Verify** that text extraction (`pdftotext` or PyMuPDF `get_text()`) returns empty or whitespace only for each of these files. If any text comes back, redo it.

Tables in the scanned PDFs must have **visible gridlines on at least two of them** and **no gridlines (whitespace-aligned) on at least one**, since both occur in the wild and parsers behave differently.

### 3c. PII rules (fictional but realistic-looking)

- SSNs: use the `9XX-XX-XXXX` range (never issued), e.g. `912-45-6789`.
- Phones: `(555) 01XX-XXXX` style or `555-01XX`.
- Emails: `@example.com` / `@example.org` only.
- Account and member numbers: invent a consistent Harbor format (e.g. member `HCU-004821`, account `7730-0012-4471`) and document it in the README so a PII scrubber can target it.
- Include some PII **inside otherwise public-looking docs** too (e.g. an example member name and account number left in the Account Closure Procedure's worked example), so the scrubber can't rely on file sensitivity alone.

---

## 4. Planted facts

Create **38–45 distinct facts** and write them into the corpus deliberately. Record each in `_answer_key/facts.yaml`:

```yaml
- fact_id: f012
  statement: "Retail overdraft fee is $29 per item, max 3 per day (Overdraft Policy v3)."
  locations:
    - doc_id: overdraft_policy_v3
      quote: "a fee of $29 per item, up to a maximum of three (3) items per business day"
```

Requirements:
- Facts must be **specific and checkable**: amounts, rates, days, cutoff times, limits, step counts, form numbers, phone extensions.
- Include **distractor values**: similar-but-different numbers elsewhere in the corpus (v2 vs v3 overdraft; retail vs business wire fee; a 12-month vs 24-month CD rate in adjacent cells). Retrieval that finds "roughly the right doc" should still be able to fail.
- At least **8 facts** live **only** inside scanned-PDF tables (#6–#9).
- At least **2 facts** live **only** in the bar chart in #8 (the values are not written anywhere as text).
- At least **2 facts** live **only** in the two-column newsletter (#21).
- At least **2 facts** live in documents with encoding defects (#13, #14).
- At least **3 facts** have answers spread across **multiple sections** of one document (#3 and #16 are good candidates).
- At least **2 facts** appear in **both** a document and its duplicate/near-duplicate (#4/#5, #10/#11).

---

## 5. The golden set: `eval/golden_set.yaml`

### 5a. Critical design rule: label passages, not chunk IDs

The pipeline will be run with **several chunking strategies**, so chunk IDs will change between runs. Therefore every expected answer is labelled as a **document ID plus a verbatim quote** from that document. The eval script will count a retrieved chunk as relevant if it contains the quote.

### 5b. Volume and mix: 45 queries total

| Query type (`type`) | Count | What it tests | Guidance |
|---|---|---|---|
| `exact_term` | 6 | BM25 / lexical | Uses a distinctive term from the doc: a form number, product name, defined term. |
| `paraphrase` | 9 | Vector search | Phrased the way a member would say it. **Must not reuse the document's key words** (e.g. doc says "overdraft", query says "spend more than I have"). |
| `scanned_table` | 8 | Naive vs layout-aware parsing | Answer is a specific cell or row in a scanned-PDF table. |
| `figure` | 2 | Figure captioning by a vision model | Answer exists only in the bar chart in #8. |
| `reading_order` | 2 | Multi-column parsing | Answer in the two-column newsletter (#21). |
| `version_trap` | 4 | Picking the policy version in force | Asks for the *current* value where v2 and v3 differ. Only the v3 passage is expected. |
| `multi_chunk` | 4 | Recall across chunks | Answer requires 2–4 separate passages (list them all). |
| `duplicate_source` | 2 | Deduplication | Fact present in a doc and its duplicate. List both doc locations; either counts. |
| `tenant_filter` | 2 | Metadata filtering | Retail question where the business doc has a conflicting value. Only the retail passage is expected. Set `tenant: retail`. |
| `encoding` | 2 | Encoding repair | Answer in #13 or #14. |
| `pii_adjacent` | 1 | Scrubbing without losing the fact | Answer is the operational fact in the call notes (#18); quote must contain **no PII**. |
| `unanswerable` | 3 | No hallucinated match | Plausible Harbor question with no answer anywhere in the corpus. `expected: []`. |

Spread queries across as many documents as possible; every non-defective content doc should be the target of at least one query.

### 5c. Schema

```yaml
version: 1
created: 2026-09-23
corpus_version: 1
match_rules:
  normalisation: "lowercase, collapse all whitespace to single spaces, normalise unicode quotes/dashes to ASCII"
  substring: "chunk text contains the quote after normalisation"
  all_tokens: "every token in the quote appears in the same chunk after normalisation (use for table rows and figures)"
queries:
  - id: q001
    query: "How much will I be charged if I spend more than what's in my checking account?"
    type: paraphrase
    tenant: retail
    expected:
      - doc_id: overdraft_policy_v3
        quote: "a fee of $29 per item"
        match: substring
    answer: "$29 per item, max 3 items per business day."
    fact_ids: [f012]
    notes: "Query avoids the word 'overdraft'."

  - id: q017
    query: "What APY does a 24-month certificate pay on a $60,000 deposit?"
    type: scanned_table
    tenant: retail
    expected:
      - doc_id: deposit_rate_sheet_2026q3
        quote: "24 months 4.05%"
        match: all_tokens
    answer: "4.05% APY"
    fact_ids: [f027]
```

### 5d. Quote rules (these matter; the golden set is useless if quotes don't match)

- `match: substring` quotes must be **verbatim** from the document's **clean** text (`eval/ground_truth_text/<doc_id>.txt`), **5–20 words**, and **unique within the corpus**, except for intentional duplicates, which must list every location.
- For scanned tables and figures use `match: all_tokens` with **only the essential tokens** (row label + value), because OCR and table parsers format cells differently.
- For figures, the tokens are what a reasonable caption would contain (e.g. `"mobile app 1.5 days"`); note this in `notes`.
- Quotes must **not contain any PII**, because PII is scrubbed before indexing and would never match.
- Quotes must not sit inside boilerplate (headers, footers, nav, cookie banners), because that is stripped.
- `doc_id` values must match `_answer_key/document_metadata.csv`.

---

## 6. Answer key, ground truth text and self-verification

### `eval/ground_truth_text/<doc_id>.txt`
For **every** corpus document with real content, write the clean, correctly-encoded, boilerplate-free, correctly-ordered text as it *should* look after perfect ingestion (tables as pipe-separated rows; figures as a one-paragraph description including the plotted values). This is the reference that golden quotes are checked against.

### `_answer_key/ingestion_expectations.csv`
Columns: `filename, doc_id, format, defects, expected_decision, reason`

- `expected_decision` ∈ `cleaned`, `quarantined`, `dropped`.
- Suggested policy (document it in the README): empty or near-empty → `dropped`; corrupted/unreadable → `quarantined`; exact duplicate → `dropped` (keep one canonical copy); near-duplicate → `dropped`, with the reason naming the canonical doc; superseded policy → `cleaned` but flagged `superseded_by` in metadata (still indexed so version-trap queries can be tested); everything else → `cleaned`.

### `scripts/verify_dataset.py`
A standalone Python script (stdlib + PyMuPDF only) that checks the dataset and exits non-zero on any failure. It must:
1. Confirm every file listed in `document_metadata.csv` exists in `corpus/`, and vice versa.
2. Confirm scanned PDFs #6–#9 have **no extractable text layer**.
3. Confirm #13 is **not** valid UTF-8 but decodes as cp1252, and #14 contains mojibake sequences.
4. Confirm #11 is byte-identical to #10, #25 is 0 bytes, and #26 fails to open.
5. For every golden query, confirm each expected quote matches its doc's `ground_truth_text` under the declared `match` rule, and for `substring` quotes, that it is unique across the corpus except where multiple locations are listed.
6. Confirm no quote contains a pattern matching the PII formats you used.
7. Confirm the query-type counts match section 5b.
8. Print a summary table: files per format, facts per doc, queries per type.

**Run this script yourself before finishing and fix every failure.** Include its final passing output in the README.

---

## 7. README.md contents

- One-paragraph description of Harbor and the dataset's purpose.
- Folder structure and what each folder is for (**only `corpus/` goes into the pipeline**).
- Table of every corpus file: format, tenant, sensitivity, and defects.
- PII formats used (regex-friendly descriptions).
- Match rules for the golden set.
- The verify script's passing output.
- Any deviations from this brief and why.

---

## 8. Final checklist before you zip

- [ ] ~26+ corpus files covering `.md .html .txt .docx .pdf (digital) .pdf (scanned) .rtf .eml/.txt .csv`
- [ ] 4 scanned, image-only PDFs with tables; one with a two-column layout and a chart
- [ ] Every defect in 3a present, and none hinted at in filenames
- [ ] 38–45 planted facts with distractors, recorded in `facts.yaml`
- [ ] 45 golden queries in the mix from 5b, each with verbatim or token-matched quotes
- [ ] `ground_truth_text/` for every content doc
- [ ] `verify_dataset.py` passes
- [ ] Everything in one zip: `harbor_rag_dataset.zip`

# Harbor Credit Union RAG test dataset

Harbor Credit Union is a fictional regional US credit union with 180,000 members and a 40-person contact centre that fields account, card and loan questions all day. This dataset is a deliberately messy copy of Harbor's internal and member-facing documentation (policies, procedures, rate and fee sheets, FAQs, scripts and operational exports) together with a retrieval golden set and an answer key. It exists to test an ingestion pipeline (clean, scrub PII, chunk, embed, index) and a hybrid retriever (BM25 plus vector search, fusion, reranker), and to score retrieval with precision@k and recall@k. Every institution, person, number and address is invented. Nothing refers to a real financial institution.

## Folder structure

```
harbor_rag_dataset/
  README.md
  corpus/                       27 files, flat. ONLY this folder goes into the pipeline.
  eval/
    golden_set.yaml             45 queries labelled as doc_id plus verbatim quote
    ground_truth_text/          24 files, <doc_id>.txt, clean reference text after perfect ingestion
  _answer_key/                  Never fed to the pipeline. Used to grade ingestion decisions.
    ingestion_expectations.csv  per-file defects and expected decision
    document_metadata.csv       doc_id, filename, title, tenant, sensitivity, version, effective_date, superseded_by
    facts.yaml                  45 planted facts, where each lives, and its distractors
    pii_inventory.csv           every PII value planted in the corpus (extra, for scoring the scrubber)
  scripts/
    verify_dataset.py           self-check (stdlib plus PyMuPDF), exits non-zero on any failure
```

The `corpus/` folder is the only input to ingestion. Everything under `eval/` and `_answer_key/` is grading material and would leak answers if indexed.

## Corpus

| # | Filename | doc_id | Format | Tenant | Sensitivity | Deliberate defects | Expected decision |
|---|---|---|---|---|---|---|---|
| 1 | `Overdraft_Policy_v2.md` | `overdraft_policy_v2` | md | retail | public | superseded version; fee, daily cap, transfer fee, Courtesy Pay limit and de minimis values differ from v3 | cleaned |
| 2 | `Overdraft_Policy_v3_FINAL.md` | `overdraft_policy_v3` | md | retail | public | UTF-8 byte order mark at start of file | cleaned |
| 3 | `Card Dispute Procedure CS-PRO-031 rev5.docx` | `card_dispute_procedure` | docx | retail | internal | multi-step procedure spread over sections 2-6 (answers need several chunks); numbered list styles | cleaned |
| 4 | `Wire_Transfer_Policy_Rev2026-02.pdf` | `wire_transfer_policy` | PDF, digital | retail | public | repeated running header and footer on every page (3 pages), exact strings as specified in the brief; footer says Confidential although the doc is public | cleaned |
| 5 | `PAY-WT-004 Wire Transfer Policy.docx` | `wire_transfer_policy_copy` | docx | retail | public | near-duplicate of the wire PDF: double spaces after sentences, extra blank paragraph per section, no header/footer | dropped |
| 6 | `HCU_Fee_Schedule_2026.pdf` | `fee_schedule_2026` | PDF, scanned image only | retail | public | image-only scan, no text layer; 20-row gridded table; ~1.4 deg rotation, noise, blur, off-white paper | cleaned |
| 7 | `Rate Sheet Q3 2026 - Deposits.pdf` | `deposit_rate_sheet_2026q3` | PDF, scanned image only | retail | public | image-only scan, no text layer; gridded CD term x balance-tier table with merged header cells; second savings table; ~1.1 deg rotation | cleaned |
| 8 | `Auto_Loan_Product_Comparison_Sept2026.pdf` | `auto_loan_comparison` | PDF, scanned image only | retail | public | image-only scan, no text layer; two-column layout; whitespace-aligned table without gridlines; bar chart whose values exist only in the image | cleaned |
| 9 | `Mortgage HELOC Rate Notice 09-2026.pdf` | `mortgage_heloc_rate_notice` | PDF, scanned image only | retail | public | image-only low-quality scan at 150 dpi; ~3 deg skew; heavy noise; RECEIVED stamp and signature overlapping text; small gridded table | cleaned |
| 10 | `faq.html` | `member_faq` | html | retail | public | heavy boilerplate (nav, cookie banner, alert bar, related-links sidebar, promo cards, legal footer); FAQ is the minority of the page | cleaned |
| 11 | `faq (1).html` | `member_faq_copy` | html | retail | public | byte-for-byte duplicate of faq.html | dropped |
| 12 | `online-banking-help.html` | `online_banking_help` | html | retail | public | deeply nested divs, answers inside layout tables, inline script tags, site boilerplate | cleaned |
| 13 | `Privacy_Notice_Rev01-2026.txt` | `privacy_notice` | txt | retail | public | Windows-1252 encoding (not valid UTF-8) with smart quotes, em dashes, copyright sign and e-acute; CRLF line endings | cleaned |
| 14 | `Debit Card Limits and Controls.txt` | `debit_card_limits` | txt | retail | public | mojibake baked into valid UTF-8 (double-encoded sequences for apostrophes, dashes, e-acute and registered sign) | cleaned |
| 15 | `Loan_Late_Payment_and_Collections_Policy_v1.6.md` | `loan_late_payment_policy` | md | retail | public | mixed CRLF/LF line endings, non-breaking spaces and tab characters inside sentences | cleaned |
| 16 | `Account Closure Procedure v1.4.docx` | `account_closure_procedure` | docx | retail | internal | step list in a Word table; tracked-change leftovers "[DELETED: ...]" with conflicting values; member PII in worked example | cleaned |
| 17 | `CC_Script_Lost_Stolen_Card_v2.2.md` | `lost_stolen_card_script` | md | retail | internal | dialogue script with bracketed agent prompts and a verbatim compliance disclosure | cleaned |
| 18 | `call_notes_export_2026-08.txt` | `call_notes_2026_08` | txt | retail | confidential | heavy PII in 13 entries (names, member and account numbers, SSNs, phones, emails, addresses, DOBs); one operational fact in a supervisor note | cleaned |
| 19 | `FW_ RE_ Complaint - international wire delayed and fee.eml` | `complaint_email_export` | eml | retail | confidential | RFC 822 headers with PII, signatures, forward chain, quoted (>) reply lines duplicating content, repeated confidentiality disclaimers | cleaned |
| 20 | `Savings Account Terms and Conditions.rtf` | `savings_terms` | rtf | retail | public | legacy RTF: control words, font/colour tables, info group, content in RTF table rows, cp1252 escapes | cleaned |
| 21 | `Harbor_Currents_Summer_2026.pdf` | `newsletter_summer_2026` | PDF, digital | retail | public | two-column layout with text layer; content stream interleaves left and right column lines, so naive extraction mixes articles | cleaned |
| 22 | `Business_Account_Fee_Guide_2026.md` | `business_fee_guide` | md | business | public | business tenant; same topics as retail docs with conflicting values | cleaned |
| 23 | `RSK-FRD-009 Fraud Monitoring Thresholds v4.1.md` | `fraud_monitoring_thresholds` | md | retail | restricted | restricted content that must never reach member-facing answers | cleaned |
| 24 | `Holiday_Schedule_2026.txt` | `holiday_schedule_2026` | txt | retail | public | near-empty placeholder (title, date and "Content to follow") | dropped |
| 25 | `branch_locations.csv` | `branch_locations` | csv | retail | public | zero bytes | dropped |
| 26 | `Rate Sheet Q2 2026 - Deposits.pdf` | `rate_sheet_2026q2` | PDF, truncated | retail | public | corrupted: truncated partway through; xref/object stream missing so no page can be loaded | quarantined |
| 27 (added) | `Share_Certificate_Disclosure_DEP-DSC-017.md` | `share_certificate_disclosure` | md | retail | public | none (added document for coverage) | cleaned |

Ground truth text exists for all 24 documents with real content. The near-empty holiday schedule, the zero-byte CSV and the truncated Q2 rate sheet have none. The byte-identical FAQ copy and the near-duplicate wire policy each have their own ground truth file so that duplicate_source quotes can be checked in both places.

### Ingestion decision policy

Empty or near-empty files are dropped. Corrupted or unreadable files are quarantined for manual review. An exact duplicate is dropped and the first-listed copy is kept as canonical. A near-duplicate is dropped and its reason names the canonical doc. The superseded Overdraft Policy v2 is cleaned and indexed but carries `superseded_by=overdraft_policy_v3` in the metadata, so version-trap queries have a real distractor to avoid. Everything else is cleaned.

### How it was generated

All files were produced by Python scripts in the code sandbox. Text documents were written from structured content definitions, then rendered per format with python-docx (DOCX), hand-written RTF, reportlab (digital PDFs, including the two-column newsletter whose content stream deliberately interleaves left and right column lines) and plain file writes with controlled encodings, BOMs and line endings. The four scanned PDFs were drawn with reportlab and matplotlib (the auto loan bar chart), rasterised with PyMuPDF at 200 dpi (150 dpi for the mortgage notice), degraded with PIL and numpy (rotation of about 1 to 3 degrees, Gaussian noise, blur, off-white paper, uneven contrast, plus a stamp and signature on the mortgage notice) and reassembled as image-only PDFs. The fee schedule, deposit rate sheet and mortgage notice tables have gridlines. The auto loan table is whitespace-aligned with no gridlines. The Q2 rate sheet was saved as a valid PDF with compressed object streams and then cut at about 62% of its length, which removes the cross-reference data. Ground truth, metadata, facts and the golden set were generated from the same content definitions, so every quote is checked against the text it came from.

## Planted facts

`_answer_key/facts.yaml` holds 45 facts. Each has a statement, one or more locations (doc_id, quote, match rule) and, where relevant, distractors (similar but different values elsewhere, such as the v2 overdraft fee, the business wire fee or an adjacent CD cell). Coverage against the brief is as follows. Twelve facts live only in scanned-PDF tables. Two live only in the bar chart (mobile app 0.6 days and dealer 2.8 days; the other chart values are online banking 1.1, branch 1.7 and contact centre 2.2). Two live only in the newsletter. Three live in encoding-defect documents (one in the cp1252 privacy notice, two in the mojibake debit card file). Three span multiple sections of one document (card dispute, loan late payment and account closure). Six appear in both a document and its duplicate (four in the wire policy pair, two in the FAQ pair).

## PII formats

These are the formats planted in the corpus. A scrubber can target them with the regexes shown.

| PII type | Format | Regex |
|---|---|---|
| Member number | `HCU-` plus 6 digits, e.g. HCU-004821 | `\bHCU-\d{6}\b` |
| Account number | `7730-` plus two 4-digit groups, e.g. 7730-0012-4471 | `\b7730-\d{4}-\d{4}\b` |
| SSN | 9XX-XX-XXXX (never-issued range) | `\b9\d{2}-\d{2}-\d{4}\b` |
| Phone | (555) 555-01XX or 555-01XX | `\(?\b555\)?[ .-]?\d{3}-\d{4}\b` or `\b555-01\d{2}\b` |
| Email | any local part at example.com or example.org (staff use harborcu.example.org) | `[\w.+-]+@[\w-]+(\.[\w-]+)*\.(com|org)\b` |
| Date of birth | MM/DD/YYYY after the label `DOB` | `DOB:?\s*\d{2}/\d{2}/\d{4}` |
| Street address | number, street name, Lane/Street/Road/Court/Drive/Way/Avenue, town, ME and ZIP 0XXXX (towns Port Alden, Westmere, Carrow Bay) | `\b\d{1,5}( [A-Z][a-z]+){1,3} (Lane\|Street\|Road\|Court\|Drive\|Way\|Avenue), [A-Z][a-z]+( [A-Z][a-z]+)?, ME 0\d{4}\b` |
| Member names | free-text first and last names | no regex, use NER; the full list is in `pii_inventory.csv` |

PII lives mainly in the confidential call notes (13 entries) and the complaint email (headers, signatures, quoted replies). It is also planted in the internal Account Closure Procedure worked example (member Dana Whitfield, HCU-004821, account 7730-0012-4471), so a scrubber that relies on sensitivity labels alone will miss it. Harbor's own contact details are not PII. The institutional phone number is written as 1-800-4-HARBOR with extensions, branch addresses such as the new Carrow Bay branch have no member-style town and ZIP suffix, and staff are referred to by initial and surname only.

## Golden set

`eval/golden_set.yaml` has 45 queries in exactly the mix from the brief (6 exact_term, 9 paraphrase, 8 scanned_table, 2 figure, 2 reading_order, 4 version_trap, 4 multi_chunk, 2 duplicate_source, 2 tenant_filter, 2 encoding, 1 pii_adjacent, 3 unanswerable). Every cleaned, current content document is the target of at least one query. Overdraft Policy v2 is deliberately never an expected answer and appears only as a distractor.

### Match rules

Normalisation lowercases the text, applies Unicode NFKC, maps curly quotes to ASCII quotes and en and em dashes to hyphens, and collapses all whitespace to single spaces. Both the quote and the chunk are normalised the same way.

A `substring` match means the normalised chunk contains the normalised quote. Substring quotes are verbatim from the ground truth text, 5 to 20 words long, free of PII, outside boilerplate, and unique across the corpus except where every duplicate location is listed.

An `all_tokens` match means every whitespace-separated token of the normalised quote occurs as a substring of the same normalised chunk. It is used for scanned tables and the chart, where OCR and table parsers format cells differently. Figure tokens are what a reasonable caption would contain, for example `mobile app 0.6 days`.

A retrieved chunk counts as relevant for a query if it satisfies any one expected location. For duplicate_source queries any listed copy counts. For multi_chunk queries each listed passage is a separate relevant item for recall.

## Verification output

Running `python3 scripts/verify_dataset.py` from the dataset root produced the following.

```
Harbor RAG dataset verification
root: harbor_rag_dataset

Files per format
  csv                1
  docx               3
  eml                1
  html               3
  md                 7
  pdf (corrupt)      1
  pdf (digital)      2
  pdf (scanned)      4
  rtf                1
  txt                4
  TOTAL             27

Facts per doc (location docs; 45 facts total)
  account_closure_procedure        1
  auto_loan_comparison             4
  business_fee_guide               1
  call_notes_2026_08               1
  card_dispute_procedure           4
  complaint_email_export           1
  debit_card_limits                2
  deposit_rate_sheet_2026q3        4
  fee_schedule_2026                4
  fraud_monitoring_thresholds      1
  loan_late_payment_policy         1
  lost_stolen_card_script          2
  member_faq                       2
  member_faq_copy                  2
  mortgage_heloc_rate_notice       2
  newsletter_summer_2026           2
  online_banking_help              2
  overdraft_policy_v3              4
  privacy_notice                   1
  savings_terms                    1
  share_certificate_disclosure     1
  wire_transfer_policy             4
  wire_transfer_policy_copy        4

Queries per type (45 total)
  exact_term           6  (expected 6)
  paraphrase           9  (expected 9)
  scanned_table        8  (expected 8)
  figure               2  (expected 2)
  reading_order        2  (expected 2)
  version_trap         4  (expected 4)
  multi_chunk          4  (expected 4)
  duplicate_source     2  (expected 2)
  tenant_filter        2  (expected 2)
  encoding             2  (expected 2)
  pii_adjacent         1  (expected 1)
  unanswerable         3  (expected 3)

Checked 54 golden quotes, 55 fact locations, 24 ground-truth files.
Mojibake sequences in debit_card_limits: 18

ALL CHECKS PASSED
```

The script checks metadata against the corpus (both directions), that the four scanned PDFs have no text layer and no fonts, that the privacy notice is invalid UTF-8 but valid cp1252, that the debit card file contains mojibake, that the FAQ copy is byte-identical, that branch_locations.csv is 0 bytes, and that the Q2 rate sheet cannot be loaded. It then checks every golden and fact quote against ground truth under its match rule, substring uniqueness across the corpus, quote length, PII patterns in quotes and in ground truth, fact_id and doc_id references, and the query-type counts. It parses the YAML with a small built-in reader, so PyYAML is not needed. A negative test (editing one quote and one byte of the FAQ copy) made it fail as expected.

## Deviations from the brief and other choices

1. One document was added (Share Certificate Disclosure DEP-DSC-017), giving 27 corpus files. It supplies the early-withdrawal penalty fact and gives the rate sheet a realistic companion.
2. Phones use (555) 555-01XX rather than the brief's (555) 01XX-XXXX, because the second shape has too many digits for a US number and 555-0100 to 555-0199 is the range reserved for fiction.
3. Ground truth text is post-scrub as well as post-clean. PII values appear as tokens such as `[REDACTED-SSN]` or `[REDACTED-NAME]`, which matches what the index would hold. Tracked-change leftovers in the closure procedure are removed entirely.
4. The email ground truth keeps each message once and drops the quoted (`>`) copies and repeated disclaimers.
5. Query q003 (an exact_term query about fraud rule VR-3) carries an extra field `access: restricted`, because its only answer is in the restricted fraud document. Member-facing runs should exclude it or expect no result. Query q002 targets the business fee guide and is marked `tenant: business`.
6. Tenant conflicts are planted deliberately. The business fee guide conflicts with retail overdraft, wire and debit card limit values, and the two retail tenant_filter queries (domestic wire fee and daily ATM limit) expect only the retail passage.
7. The truncated Q2 PDF counts as failing to open if PyMuPDF raises an error, reports zero pages, or cannot load a page. Current PyMuPDF repairs the file enough to open it with zero pages, and pdftotext exits with an error.
8. `facts.yaml` adds `tags` and `distractors` fields beyond the example schema. The `created` date is written as a quoted string so YAML loaders do not turn it into a date object.
9. The wire PDF header and footer use the exact strings from the brief, including the em dash and middle dot, since they are test content rather than prose.
10. Scanned-table and figure tokens assume an OCR engine that reads the rendered text faithfully. A pipeline that drops the percent sign or the dollar sign will miss those queries, which is intended.

# Milestone 2 spike: Docling on the hard PDFs

Input for the retrieval report's "ingestion" section. Command:
`uv run python src/parse_pdf_layout.py --spike` (add `--no-deskew` for the before numbers).

## Final result (Docling 2.130.0, ocrmac OCR, deskew at >= 2 degrees)

| doc_id | quotes kept: naive | quotes kept: layout | exact table rows | skew (deg) |
|---|---|---|---|---|
| fee_schedule_2026 | 0/2 | 2/2 | 21/21 | -1.4 (not rotated) |
| deposit_rate_sheet_2026q3 | 0/2 | 2/2 | 13/14 | +1.1 (not rotated) |
| auto_loan_comparison | 0/2 | 2/2 | 8/8 | -1.1, +1.3 (not rotated) |
| mortgage_heloc_rate_notice | 0/2 | 2/2 | 6/7 | -3.0 (rotated) |
| newsletter_summer_2026 | 0/2 | 2/2 | 1/1 | digital PDF, n/a |

Quote survival excludes the 2 figure quotes (auto loan bar chart), which need captions (milestone 3).

## Findings

1. **Naive extraction gets nothing from scans.** The 4 scanned PDFs have no text layer, so PyMuPDF returns 0 characters. The newsletter has a text layer, but naive extraction interleaves its two columns line by line, so both of its quotes are broken.
2. **Quote survival alone is too lenient for tables.** Before deskewing, the mortgage notice kept 2/2 quotes but **0/7** table rows were correct: the 3-degree skew shifted the APR column down one row, so "15-Year Fixed" showed 6.713% (really the 7/6 ARM's APR). `all_tokens` only needs the words somewhere in the text, so it can't see this. The spike therefore also reports **exact table rows** against ground truth.
3. **Fallbacks tried on the mortgage table, in plan order:**
   - A different OCR engine (RapidOCR): **crashed** with a segfault (exit 139) inside Docling in this environment. Not investigated further, because deskewing fixed the problem. The portable fallback in `model_manifest.json` is therefore unproven here.
   - `do_cell_matching=False`: row labels realigned, but APR was still shifted: 0/7 rows correct.
   - Deskew pre-processing (projection-profile angle estimate, rotate, rebuild as an image PDF): **6/7 rows**. The remaining miss is an OCR comma ("0,000" for "0.000"). The paragraph OCR also improved ("Affer" -> "After", "S10,000 la" -> "$10,000 to").
4. **Deskewing has a cost.** Rotating resamples the image, and straightening the fee schedule's 1.4-degree tilt turned "ATM" into "AT" (21/21 -> 20/21 rows). So only pages tilted **2 degrees or more** are rotated (`deskew_min_degrees`), which keeps every table at its best result.
5. **Remaining imperfections (accepted):**
   - The rate sheet's merged two-level header is flattened to "Annual Percentage Yield (APY) by balance tier.$1,000-$9,999". The data rows are exact.
   - The mortgage "RECEIVED" stamp is OCR'd into the text ("SEP 02 2026 LENDING OPS").
   - One newsletter sentence ("You can also lock your debit card...") lands in the wrong article.
6. **Figures:** Docling found 2 pictures. One is the auto loan bar chart (clean crop, all 5 bar labels and values legible). The other is the mortgage manager's **signature**, which must not be sent for captioning (milestone 3).
7. **Runtime:** about 16 s for the first file (loading the models), then 0.3-4 s per PDF. Results are cached per (file hash, options), so reruns are instant.

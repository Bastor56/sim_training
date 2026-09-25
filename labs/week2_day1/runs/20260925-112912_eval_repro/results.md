# Retrieval eval results (20260925-112912_eval_repro)

Golden set v1 (corpus v1): 41 scored queries. Filter: the query's own tenant, restricted excluded, superseded excluded (except row 17). P@5 ceiling for single-item queries is 0.20; mean ceiling shown per row.


## Matrix

| Row | Parser | Chunker | Mode | P@5 | P@10 | R@5 | R@10 | P@5 ceiling | q003 leak | clearance | wrong tenant | restricted | superseded |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | naive | A_fixed | bm25 | 0.127 | 0.068 | 0.514 | 0.545 | 0.239 | PASS | OK | 0 | 0 | 0 |
| 2 | naive | A_fixed | vector | 0.137 | 0.081 | 0.571 | 0.650 | 0.239 | PASS | OK | 0 | 0 | 0 |
| 3 | naive | A_fixed | hybrid | 0.141 | 0.078 | 0.569 | 0.626 | 0.239 | PASS | OK | 0 | 0 | 0 |
| 4 | naive | A_fixed | hybrid_rerank | 0.141 | 0.078 | 0.579 | 0.610 | 0.239 | PASS | OK | 0 | 0 | 0 |
| 5 | naive | B_structure | bm25 | 0.127 | 0.071 | 0.488 | 0.545 | 0.239 | PASS | OK | 0 | 0 | 0 |
| 6 | naive | B_structure | vector | 0.146 | 0.085 | 0.585 | 0.675 | 0.239 | PASS | OK | 0 | 0 | 0 |
| 7 | naive | B_structure | hybrid | 0.156 | 0.081 | 0.634 | 0.642 | 0.239 | PASS | OK | 0 | 0 | 0 |
| 8 | naive | B_structure | hybrid_rerank | 0.146 | 0.085 | 0.585 | 0.691 | 0.239 | PASS | OK | 0 | 0 | 0 |
| 9 | layout | A_fixed | bm25 | 0.180 | 0.100 | 0.782 | 0.846 | 0.239 | PASS | OK | 0 | 0 | 0 |
| 10 | layout | A_fixed | vector | 0.195 | 0.110 | 0.864 | 0.943 | 0.239 | PASS | OK | 0 | 0 | 0 |
| 11 | layout | A_fixed | hybrid | 0.200 | 0.107 | 0.862 | 0.919 | 0.239 | PASS | OK | 0 | 0 | 0 |
| 12 | layout | A_fixed | hybrid_rerank | 0.200 | 0.112 | 0.872 | 0.951 | 0.239 | PASS | OK | 0 | 0 | 0 |
| 13 | layout | B_structure | bm25 | 0.180 | 0.098 | 0.756 | 0.813 | 0.239 | PASS | OK | 0 | 0 | 0 |
| 14 | layout | B_structure | vector | 0.210 | 0.115 | 0.902 | 0.968 | 0.239 | PASS | OK | 0 | 0 | 0 |
| 15 | layout | B_structure | hybrid | 0.210 | 0.110 | 0.902 | 0.935 | 0.239 | PASS | OK | 0 | 0 | 0 |
| 16 | layout | B_structure | hybrid_rerank | 0.210 | 0.112 | 0.902 | 0.959 | 0.239 | PASS | OK | 0 | 0 | 0 |
| 17 | layout | B_structure | vector (superseded filter OFF) | 0.205 | 0.115 | 0.878 | 0.968 | 0.239 | PASS | OK | 0 | 0 | 39 |

## Before/after 1: parsing (B_structure, hybrid_rerank)

| Config | R@5 | R@10 | P@5 | mean latency (ms) |
|---|---|---|---|---|
| naive | 0.585 | 0.691 | 0.146 | 1406.3 |
| layout-aware | 0.902 | 0.959 | 0.210 | 1491.6 |

## Before/after 2: chunking (layout, hybrid_rerank)

| Config | R@5 | R@10 | P@5 | mean latency (ms) |
|---|---|---|---|---|
| A_fixed | 0.872 | 0.951 | 0.200 | 1191.7 |
| B_structure | 0.902 | 0.959 | 0.210 | 1491.6 |

## Before/after 3: retrieval stages (layout, B_structure)

| Config | R@5 | R@10 | P@5 | mean latency (ms) |
|---|---|---|---|---|
| bm25 | 0.756 | 0.813 | 0.180 | 0.2 |
| vector | 0.902 | 0.968 | 0.210 | 6.3 |
| hybrid | 0.902 | 0.935 | 0.210 | 6.7 |
| hybrid_rerank | 0.902 | 0.959 | 0.210 | 1491.6 |

## Recall@5 by query type (hybrid_rerank rows)

| Type | n | naive/A_fixed | naive/B_structure | layout/A_fixed | layout/B_structure |
|---|---|---|---|---|---|
| duplicate_source | 2 | 1.00 | 1.00 | 1.00 | 1.00 |
| encoding | 2 | 1.00 | 1.00 | 1.00 | 1.00 |
| exact_term | 5 | 1.00 | 1.00 | 1.00 | 1.00 |
| figure | 2 | 0.00 | 0.00 | 1.00 | 1.00 |
| multi_chunk | 4 | 0.69 | 0.75 | 0.69 | 0.75 |
| paraphrase | 9 | 0.56 | 0.56 | 0.56 | 0.67 |
| pii_adjacent | 1 | 1.00 | 1.00 | 1.00 | 1.00 |
| reading_order | 2 | 0.00 | 0.00 | 1.00 | 1.00 |
| scanned_table | 8 | 0.00 | 0.00 | 1.00 | 1.00 |
| tenant_filter | 2 | 1.00 | 1.00 | 1.00 | 1.00 |
| version_trap | 4 | 1.00 | 1.00 | 1.00 | 1.00 |

## Unanswerable queries (hybrid_rerank: top-1 rerank score)

| Row | q043 | q044 | q045 | answerable top-1 min | answerable top-1 median | answerable below the best unanswerable |
|---|---|---|---|---|---|---|
| 4 | 0.0072 | 0.014 | 0.0954 | 0.0008 | 0.6402 | 11 |
| 8 | 0.0024 | 0.0031 | 0.0393 | 0.0004 | 0.8085 | 11 |
| 12 | 0.0167 | 0.0036 | 0.5406 | 0.0008 | 0.8959 | 12 |
| 16 | 0.0024 | 0.0029 | 0.549 | 0.0004 | 0.9487 | 12 |

## Latency per stage (mean / p95 ms per query, CPU)

| Row | Mode | BM25 | Vector | Fusion | Rerank | Total |
|---|---|---|---|---|---|---|
| 1 | bm25 | 0.2 / 0.2 | - | - | - | 0.2 / 0.2 |
| 2 | vector | - | 6.4 / 7.1 | - | - | 6.4 / 7.1 |
| 3 | hybrid | 0.2 / 0.3 | 6.4 / 7.3 | 0.0 / 0.0 | - | 6.7 / 7.7 |
| 4 | hybrid_rerank | 0.3 / 0.3 | 6.9 / 7.7 | 0.0 / 0.0 | 1079.3 / 1385.5 | 1086.5 / 1393.5 |
| 5 | bm25 | 0.2 / 0.3 | - | - | - | 0.2 / 0.3 |
| 6 | vector | - | 6.4 / 7.0 | - | - | 6.4 / 7.0 |
| 7 | hybrid | 0.2 / 0.3 | 6.6 / 7.2 | 0.0 / 0.0 | - | 6.8 / 7.4 |
| 8 | hybrid_rerank | 0.3 / 0.3 | 7.2 / 9.3 | 0.0 / 0.0 | 1398.9 / 1659.3 | 1406.3 / 1666.0 |
| 9 | bm25 | 0.2 / 0.3 | - | - | - | 0.2 / 0.3 |
| 10 | vector | - | 6.3 / 6.8 | - | - | 6.3 / 6.8 |
| 11 | hybrid | 0.2 / 0.3 | 6.3 / 6.4 | 0.0 / 0.0 | - | 6.5 / 6.7 |
| 12 | hybrid_rerank | 0.3 / 0.3 | 6.8 / 7.4 | 0.0 / 0.0 | 1184.6 / 1362.0 | 1191.7 / 1368.9 |
| 13 | bm25 | 0.2 / 0.3 | - | - | - | 0.2 / 0.3 |
| 14 | vector | - | 6.3 / 6.7 | - | - | 6.3 / 6.7 |
| 15 | hybrid | 0.3 / 0.4 | 6.4 / 7.1 | 0.0 / 0.0 | - | 6.7 / 7.4 |
| 16 | hybrid_rerank | 0.3 / 0.4 | 6.9 / 7.6 | 0.0 / 0.0 | 1484.3 / 1796.2 | 1491.6 / 1803.4 |
| 17 | vector | - | 6.0 / 6.4 | - | - | 6.0 / 6.4 |

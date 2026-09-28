# 20260926-123835_opus_pilot_opus

- questions: 5 (errors: 0)
- cost per interaction: mean $0.013522 | p50 $0.01422 | p95 $0.018778 | max $0.019262
- latency per interaction: p50 9161.4 ms | p95 12289.94 ms | max 12582.1 ms (LLM mean 6867.6 ms, retrieval mean 2715.0 ms)
- cost by purpose (sum): {'gate': 0.004867, 'generate': 0.060684, 'retrieve': 0.0, 'rewrite': 0.002061}
- rounds distribution: {0: 0, 1: 4, 2: 0, 3: 1}
- local cache hit rate: 0.0 of 12 LLM calls; provider cache read tokens: 3408
- output tokens per generate call (mean, provider calls): 263.2
- provider spend this run: $0.077072 (judge $0.00946); ledger total $0.160868

## Quality

- questions: 5
- task_success: 1.0
- task_success_count: 5
- gate_accuracy: 1.0
- gate_confusion: {'retrieve->retrieve': 5}
- outcome_correct: 1.0
- answerable_answered: 1.0
- judge_verdicts: {'correct': 4}
- judge_correct_of_answerable: 1.0
- citation_hit_of_answerable: 1.0
- not_in_corpus_recall: 1.0
- not_in_corpus_precision: 1.0
- not_in_corpus_false_declines: 0
- direct_correct: None
- direct_no_dollar: None
- version_check: 1.0
- version_quoted: 1.0
- version_in_prose: 1.0
- source_line_violations: 0
- leaks: 0
- declined_rounds: 1
- ungrounded_rounds: 0
- rewrite_helped: 0
- rescued_after_decline: 0

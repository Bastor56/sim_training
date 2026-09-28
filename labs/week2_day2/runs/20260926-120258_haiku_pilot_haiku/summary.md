# 20260926-120258_haiku_pilot_haiku

- questions: 5 (errors: 0)
- cost per interaction: mean $0.003208 | p50 $0.002885 | p95 $0.004019 | max $0.004084
- latency per interaction: p50 7109.6 ms | p95 11053.6 ms | max 11325.6 ms (LLM mean 4623.9 ms, retrieval mean 3205.8 ms)
- cost by purpose (sum): {'gate': 0.004912, 'generate': 0.009118, 'retrieve': 0.0, 'rewrite': 0.002008}
- rounds distribution: {0: 0, 1: 4, 2: 0, 3: 1}
- local cache hit rate: 0.0 of 12 LLM calls; provider cache read tokens: 0
- output tokens per generate call (mean, provider calls): 115.2
- provider spend this run: $0.024518 (judge $0.00848); ledger total $0.04219

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

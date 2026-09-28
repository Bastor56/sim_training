# 20260928-082601_opus_C_replay

- questions: 55 (errors: 0)
- cost per interaction: mean $0.0 | p50 $0.0 | p95 $0.0 | max $0.0
- latency per interaction: p50 1792.0 ms | p95 4755.74 ms | max 5320.5 ms (LLM mean 1.7 ms, retrieval mean 1623.8 ms)
- cost by purpose (sum): {'direct_answer': 0.0, 'gate': 0.0, 'generate': 0.0, 'retrieve': 0.0, 'rewrite': 0.0}
- rounds distribution: {0: 10, 1: 41, 2: 0, 3: 4}
- local cache hit rate: 1.0 of 117 LLM calls; provider cache read tokens: 0
- output tokens per generate call (mean, provider calls): None
- provider spend this run: $0 (judge $0); ledger total $2.084477

## Quality

- questions: 55
- task_success: 0.9636
- task_success_count: 53
- gate_accuracy: 1.0
- gate_confusion: {'answer_direct->answer_direct': 10, 'retrieve->retrieve': 45}
- outcome_correct: 1.0
- answerable_answered: 1.0
- judge_verdicts: {'correct': 39, 'incorrect': 1, 'partial': 1}
- judge_correct_of_answerable: 0.9512
- citation_hit_of_answerable: 1.0
- not_in_corpus_recall: 1.0
- not_in_corpus_precision: 1.0
- not_in_corpus_false_declines: 0
- direct_correct: 1.0
- direct_no_dollar: 1.0
- version_check: 1.0
- version_quoted: 0.75
- version_in_prose: 0.75
- source_line_violations: 0
- leaks: 0
- declined_rounds: 3
- ungrounded_rounds: 0
- rewrite_helped: 0
- rescued_after_decline: 0

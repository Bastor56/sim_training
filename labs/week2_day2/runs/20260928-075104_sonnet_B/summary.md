# 20260928-075104_sonnet_B

- questions: 55 (errors: 0)
- cost per interaction: mean $0.006129 | p50 $0.006139 | p95 $0.01067 | max $0.013294
- latency per interaction: p50 6791.6 ms | p95 11904.59 ms | max 16396.2 ms (LLM mean 5330.1 ms, retrieval mean 1672.0 ms)
- cost by purpose (sum): {'direct_answer': 0.0171, 'gate': 0.052599, 'generate': 0.256198, 'retrieve': 0.0, 'rewrite': 0.011201}
- rounds distribution: {'0': 10, '1': 39, '2': 1, '3': 5}
- local cache hit rate: 0.0083 of 120 LLM calls; provider cache read tokens: 0
- output tokens per generate call (mean, provider calls): 221.8
- provider spend this run: $0.426596 (judge $0.089498); ledger total $1.322568

## Quality

- questions: 55
- task_success: 0.9455
- task_success_count: 52
- gate_accuracy: 1.0
- gate_confusion: {'answer_direct->answer_direct': 10, 'retrieve->retrieve': 45}
- outcome_correct: 0.9818
- answerable_answered: 0.9756
- judge_verdicts: {'correct': 38, 'partial': 2}
- judge_correct_of_answerable: 0.9268
- citation_hit_of_answerable: 0.9756
- not_in_corpus_recall: 1.0
- not_in_corpus_precision: 0.8
- not_in_corpus_false_declines: 1
- direct_correct: 1.0
- direct_no_dollar: 1.0
- version_check: 1.0
- version_quoted: 1.0
- version_in_prose: 1.0
- source_line_violations: 0
- leaks: 0
- declined_rounds: 4
- ungrounded_rounds: 0
- rewrite_helped: 1
- rescued_after_decline: 0

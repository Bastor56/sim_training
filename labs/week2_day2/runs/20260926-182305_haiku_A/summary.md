# 20260926-182305_haiku_A

- questions: 55 (errors: 0)
- cost per interaction: mean $0.002852 | p50 $0.00289 | p95 $0.004397 | max $0.004885
- latency per interaction: p50 5177.2 ms | p95 10300.58 ms | max 11812.3 ms (LLM mean 3594.6 ms, retrieval mean 1771.7 ms)
- cost by purpose (sum): {'direct_answer': 0.006315, 'gate': 0.052009, 'generate': 0.088619, 'retrieve': 0.0, 'rewrite': 0.009915}
- rounds distribution: {'0': 10, '1': 40, '2': 0, '3': 5}
- local cache hit rate: 0.0 of 117 LLM calls; provider cache read tokens: 0
- output tokens per generate call (mean, provider calls): 139.3
- provider spend this run: $0.2428 (judge $0.085942); ledger total $0.403668

## Quality

- questions: 55
- task_success: 0.9273
- task_success_count: 51
- gate_accuracy: 1.0
- gate_confusion: {'answer_direct->answer_direct': 10, 'retrieve->retrieve': 45}
- outcome_correct: 0.9818
- answerable_answered: 0.9756
- judge_verdicts: {'correct': 37, 'incorrect': 2, 'partial': 1}
- judge_correct_of_answerable: 0.9024
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
- declined_rounds: 2
- ungrounded_rounds: 0
- rewrite_helped: 0
- rescued_after_decline: 0

# 20260926-190245_haiku_A_tau030

- questions: 55 (errors: 0)
- cost per interaction: mean $0.002738 | p50 $0.002845 | p95 $0.004139 | max $0.004525
- latency per interaction: p50 4987.0 ms | p95 9103.82 ms | max 10655.8 ms (LLM mean 3442.7 ms, retrieval mean 1581.6 ms)
- cost by purpose (sum): {'direct_answer': 0.00602, 'gate': 0.052449, 'generate': 0.082961, 'retrieve': 0.0, 'rewrite': 0.009156}
- rounds distribution: {'0': 10, '1': 40, '2': 1, '3': 4}
- local cache hit rate: 0.0 of 116 LLM calls; provider cache read tokens: 0
- output tokens per generate call (mean, provider calls): 137.1
- provider spend this run: $0.220476 (judge $0.06989); ledger total $0.895972

## Quality

- questions: 55
- task_success: 0.9273
- task_success_count: 51
- gate_accuracy: 1.0
- gate_confusion: {'answer_direct->answer_direct': 10, 'retrieve->retrieve': 45}
- outcome_correct: 1.0
- answerable_answered: 1.0
- judge_verdicts: {'correct': 37, 'incorrect': 2, 'partial': 2}
- judge_correct_of_answerable: 0.9024
- citation_hit_of_answerable: 0.9756
- not_in_corpus_recall: 1.0
- not_in_corpus_precision: 1.0
- not_in_corpus_false_declines: 0
- direct_correct: 1.0
- direct_no_dollar: 1.0
- version_check: 1.0
- version_quoted: 1.0
- version_in_prose: 1.0
- source_line_violations: 0
- leaks: 0
- declined_rounds: 1
- ungrounded_rounds: 0
- rewrite_helped: 1
- rescued_after_decline: 0

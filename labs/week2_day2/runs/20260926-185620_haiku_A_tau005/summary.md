# 20260926-185620_haiku_A_tau005

- questions: 55 (errors: 0)
- cost per interaction: mean $0.00299 | p50 $0.003161 | p95 $0.004735 | max $0.005288
- latency per interaction: p50 5124.6 ms | p95 10098.61 ms | max 12536.0 ms (LLM mean 3710.6 ms, retrieval mean 1615.9 ms)
- cost by purpose (sum): {'direct_answer': 0.0062, 'gate': 0.052334, 'generate': 0.095941, 'retrieve': 0.0, 'rewrite': 0.009994}
- rounds distribution: {'0': 10, '1': 39, '2': 2, '3': 4}
- local cache hit rate: 0.0 of 120 LLM calls; provider cache read tokens: 0
- output tokens per generate call (mean, provider calls): 138.7
- provider spend this run: $0.242221 (judge $0.077752); ledger total $0.675496

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
- citation_hit_of_answerable: 1.0
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
- declined_rounds: 3
- ungrounded_rounds: 1
- rewrite_helped: 2
- rescued_after_decline: 1

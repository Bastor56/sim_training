# 20260926-183648_haiku_A_repeat

- questions: 18 (errors: 0)
- cost per interaction: mean $None | p50 $None | p95 $None | max $None
- latency per interaction: p50 None ms | p95 None ms | max None ms (LLM mean None ms, retrieval mean None ms)
- cost by purpose (sum): {}
- rounds distribution: {0: 0, 1: 0, 2: 0, 3: 0}
- local cache hit rate: 0.45 of 40 LLM calls; provider cache read tokens: 0
- output tokens per generate call (mean, provider calls): 101.3
- provider spend this run: $0.029607 (judge $0); ledger total $0.433275

## Cache probes

- surface: 8/8 as expected ['r001:hit', 'r002:hit', 'r003:hit', 'r004:hit', 'r005:hit', 'r006:hit', 'r007:hit', 'r008:hit']
- paraphrase: 5/5 as expected ['r009:miss', 'r010:miss', 'r011:miss', 'r012:miss', 'r013:miss']
- tenant_swap: 3/3 as expected ['r014:miss', 'r015:miss', 'r016:miss']
- corpus_change: 2/2 as expected ['r017:miss', 'r018:miss']

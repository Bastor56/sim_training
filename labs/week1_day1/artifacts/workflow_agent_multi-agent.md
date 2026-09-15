# FDE Xlerate - Week 1, Day 1
Assignment artifact: workflow vs. agent vs. multi-agent decision memo

## Example business problem 1: KYC for a new checking account
A new customer wants to create a checking account at a bank. 
Decision: Workflow
Reasoning: KYC is a fixed sequence, linear or with conditional branches. In either case, these should be pre-defined code paths with no necessity for an agent to dynamically decide tool calls or tool ordering. As workflows are cheaper, simpler, and more predictable than agents, it is the best approach for this business problem.

## Example business problem 2: AML alert investigation
A wire transfer hits a rule-based flag.
Decision: Agent
Reasoning: After a rule-based flag, an investigation is necessary to decide whether the instance is a false positive or if a suspicious activity report is necessary. The information required for this decision may be spread across several sources (transaction history, KYC profile, beneficial ownership records, etc.). Each piece of evidence will likely inform subsequent investigative steps. An agent provides the dynamic tool use required to investigate a given piece of evidence, decide what evidence is still needed, and to continue to pull additional evidence until a decision can be made or a human can be brought in for review. Further, money laundering methods evolve over time, therefore a workflow enumerating different investigative processes will go out of date and require regular updates while an agent may investigate based on core principles.

## Example business problem 3: Commercial loan underwriting
A business applies for a $2M line of credit.
Decision: Multi-agent
Reasoning: For loan underwriting, there are several specialized processes that must occur (e.g. financial analysis, credit risk assessment, and compliance analysis). Performance of these processes should be split across several sub-agents by a coordinator agent to avoid providing unnecessary context (reduce token cost), reduce the number of tools to select from (improve tool call accuracy), and improve traceability (support siloed iteration). The coordinator agent can then package each sub-agent's output into a collective output. However, this comes at the cost of higher latency and additional failure points.

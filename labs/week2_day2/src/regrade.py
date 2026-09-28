"""Re-grade finished runs with the current judge prompt (plan.md milestone 10: judge calibration).

    uv run python src/regrade.py runs/<A> runs/<B> runs/<C> ...

The agent is not re-run: each run's answers are fixed. Only the judge is
called again (prompt = settings.PROMPTS["judge"]), through llm.call, so every
judge call is recorded, priced, counted by the spend guard and cached in the
"judge" namespace.

Per run folder:
    grades_<old judge>.jsonl       the previous grades, kept for the record
    grades.jsonl                   rewritten with the new judge's verdicts
    summary.json / summary.md      "quality" recomputed; the old block kept as "quality_<old judge>"
Judge call records go to runs/<run>__<new judge>/ so the run's own calls.jsonl is untouched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import eval_sets
import grading
import llm
import run_eval
import settings
import tracing


def regrade(run_dir: Path) -> dict:
    new_judge = settings.PROMPTS["judge"]
    config = json.loads((run_dir / "config.json").read_text())
    old_judge = config["prompts"]["judge"]
    summary = json.loads((run_dir / "summary.json").read_text())
    if summary.get("judge_prompt") == new_judge:
        print(f"{run_dir.name}: already graded with {new_judge}, skipped")
        return summary
    rows = [json.loads(line) for line in (run_dir / "interactions.jsonl").read_text().splitlines()]
    old = [json.loads(line) for line in (run_dir / "grades.jsonl").read_text().splitlines()]
    backup = run_dir / f"grades_{old_judge}.jsonl"
    if not backup.exists():
        backup.write_text("".join(json.dumps(g, sort_keys=True) + "\n" for g in old), encoding="utf-8")

    items = {i.id: i for i in eval_sets.load(["golden", "no_retrieval"])}
    tracing.start_run(f"{run_dir.name}__{new_judge}")
    llm.configure(cache_mode="read-write", namespace="judge")
    corpus = config["corpus_version"]
    new_grades, changed = [], []
    for row, g_old in zip(rows, old):
        item = items[row["id"]]
        g = grading.grade(row, item, corpus_version=corpus) if row["outcome"] != "error" else g_old
        if "judge_verdict" in g_old:
            g[f"judge_verdict_{old_judge}"] = g_old["judge_verdict"]
            if g.get("judge_verdict") != g_old["judge_verdict"]:
                changed.append(f"{row['id']}: {g_old['judge_verdict']} -> {g['judge_verdict']}")
        new_grades.append(g)

    (run_dir / "grades.jsonl").write_text("".join(json.dumps(g, sort_keys=True) + "\n" for g in new_grades),
                                          encoding="utf-8")
    summary[f"quality_{old_judge}"] = summary["quality"]
    summary["quality"] = grading.summarise(new_grades)
    summary["judge_prompt"] = new_judge
    summary["judge_changes"] = changed
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (run_dir / "summary.md").write_text(run_eval.summary_md(summary), encoding="utf-8")
    q_old, q_new = summary[f"quality_{old_judge}"], summary["quality"]
    print(f"{run_dir.name}: task success {q_old['task_success_count']} -> {q_new['task_success_count']} "
          f"({old_judge} -> {new_judge}); verdicts {q_old['judge_verdicts']} -> {q_new['judge_verdicts']}")
    for c in changed:
        print(f"    {c}")
    return summary


if __name__ == "__main__":
    for d in sys.argv[1:]:
        regrade(Path(d))

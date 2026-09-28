"""Build the judge-calibration sheet (plan.md milestone 10 pause). No API calls.

    uv run python src/calibration.py runs/<A> runs/<B> runs/<C>

For each run, picks 10 judged answers: every answer the judge did NOT call
"correct" first (those are where a miscalibrated judge does most damage),
then "correct" ones spread evenly by question id. Writes
artifacts/judge_calibration.md with the question, the reference answer, the
assistant's answer and the judge's verdict, plus an empty "Human verdict"
line to fill in *before* reading the judge's verdict.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import eval_sets
import settings

PER_RUN = 10


def pick(grades: list[dict]) -> list[dict]:
    judged = [g for g in grades if g.get("judge_verdict") in ("correct", "partial", "incorrect")]
    flagged = [g for g in judged if g["judge_verdict"] != "correct"]
    correct = [g for g in judged if g["judge_verdict"] == "correct"]
    room = max(PER_RUN - len(flagged), 0)
    step = max(len(correct) // room, 1) if room else 1
    return (flagged + correct[::step][:room])[:max(PER_RUN, len(flagged))]


def main(run_dirs: list[str]) -> None:
    items = {i.id: i for i in eval_sets.load(["golden"])}
    lines = ["# Judge calibration sheet", "",
             "For each case, write your own verdict (correct / partial / incorrect) on the **Human verdict** line "
             "*before* reading the judge's. The judge's rules (prompts/judge_v1.md): every reference fact present "
             "and matching = correct; nothing contradicted but a required fact missing = partial; any contradiction, "
             "wrong product, or a decline when the reference has an answer = incorrect. Extra detail is fine if it "
             "doesn't contradict.", ""]
    for d in map(Path, run_dirs):
        config = json.loads((d / "config.json").read_text())
        rows = {r["id"]: r for r in map(json.loads, (d / "interactions.jsonl").read_text().splitlines())}
        grades = [json.loads(line) for line in (d / "grades.jsonl").read_text().splitlines()]
        chosen = pick(grades)
        lines += [f"## {config['args']['generator']} ({d.name}): {len(chosen)} cases", ""]
        for n, g in enumerate(chosen, start=1):
            item, row = items[g["id"]], rows[g["id"]]
            lines += [f"### {config['args']['generator']} #{n}: {g['id']} ({item.category})", "",
                      f"**Question:** {item.question}", "",
                      f"**Reference answer:** {item.golden.answer}", "",
                      f"**Assistant's answer:** {row['answer']}", "",
                      "**Human verdict:** ______  (reason: )", "",
                      f"<details><summary>Judge's verdict</summary>\n\n**{g['judge_verdict']}**: {g['judge_reason']}\n\n</details>",
                      ""]
    out = settings.ARTIFACTS_DIR / "judge_calibration.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"written: {out} ({sum(1 for line in lines if line.startswith('### '))} cases)")


if __name__ == "__main__":
    main(sys.argv[1:])

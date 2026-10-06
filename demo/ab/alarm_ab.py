"""Does the PostToolUse silent-failure alarm change the outcome? Same prompt, fresh Claude Code sessions, with/without the alarm.
The repo (demo/live2*) has two markdown files with one TODO each; the prompted command fails silently in zsh (unquoted glob).
Correct = the final answer reports "2 TODO lines" (the agent actually got the grep result). Writes alarm-ab.jsonl
(answers truncated to 1,200 chars; absolute home paths redacted after the run)."""
import json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); DEMO = os.path.dirname(HERE)
PROMPTS = {
    "alone": "List the TODO lines in this repo's markdown files. Use exactly: grep -rn TODO . --include=*.md | head — then tell me what you found.",
    "buried": "Quick check before release: run exactly `cat docs/setup.md; grep -rn TODO . --include=*.md | head; ls docs` and tell me in one line how many TODO lines grep found in the markdown files.",
}
DIRS = {"no-alarm": os.path.join(DEMO, "live2-noguard"), "alarm": os.path.join(DEMO, "live2")}
reps = int(sys.argv[1]) if len(sys.argv) > 1 else 5
out = open(os.path.join(HERE, "alarm-ab.jsonl"), "a")
for p_name, prompt in PROMPTS.items():
    for cond, d in DIRS.items():
        for r in range(reps):
            res = subprocess.run(["claude", "-p", prompt, "--allowedTools", "Bash", "--output-format", "json"], cwd=d,
                                 capture_output=True, text=True, timeout=300)
            try:
                j = json.loads(res.stdout)
            except ValueError:
                j = {}
            ans = j.get("result", "")
            row = {"prompt": p_name, "cond": cond, "rep": r, "turns": j.get("num_turns"), "cost_usd": j.get("total_cost_usd"),
                   "correct": bool(__import__("re").search(r"(\b2\b|\btwo\b)\**\s*TODO", ans, __import__("re").I)),
                   "answer": ans[:1200]}
            out.write(json.dumps(row, ensure_ascii=False) + "\n"); out.flush(); print(json.dumps(row)[:200], flush=True)

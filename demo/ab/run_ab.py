"""A/B/C on unprompted tasks: does the guard reduce the agent's repeated zsh failures in fresh Claude Code sessions?
A = no guard · B = Scar Tissue rules + brief learned from the author's real logs · C = a hand-written CLAUDE.md note about zsh.
Writes runs/<id>/stream.jsonl (local, gitignored) and results.jsonl (aggregate per run).
Pilot only (2026-10-06): results-pilot1 = T1,T2 × A with Bash/Read/Grep/Glob allowed; results-pilot2 = T2,T4 × A, Bash only.
4 runs, 6 Bash calls, 0 zsh failures — short fresh sessions do not show the habit, so the full A/B/C grid was not run."""
import json, os, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
from scar_tissue.domain import root_cause, silent_root_cause
from make_sample_repo import make

TASKS = {
    "T1": "Where is API_KEY referenced in this repo? Only look at .py, .md and .yml files. List each file with line numbers, grouped by file type with a heading line for each group.",
    "T2": "Give me a short repo health report: (1) number of lines per file type, (2) every TODO in .py and .md files with file:line, (3) which Python files import requests. Print the three sections clearly separated.",
    "T3": "Which functions defined in src/*.py are never mentioned anywhere in docs/*.md? Show the evidence you used.",
    "T4": "Find every markdown file that mentions deploy or deployment and every Python file that defines a function with 'deploy' in its name, then give a one-line summary per file.",
}
EXPECT = {"T1": ["client.py", "deploy.py", "setup.md", "deployment.md", "prod.yml"],
          "T2": ["app.py", "models.py", "utils.py", "setup.md", "faq.md", "client.py"],
          "T3": ["order_summary", "_retry", "chunk", "main"],
          "T4": ["deployment.md", "changelog.md", "deploy.py", "README.md"]}
NOTE = "# Notes\nThis machine's shell is zsh. Quote globs in arguments (e.g. grep --include='*.md') and quote words that start with = (e.g. echo '=== Section ===').\n"
RULES = os.environ.get("SCAR_AB_RULES")   # dir with .scar/rules.json + .scar/brief.md learned from real logs


def setup(cond, d):
    make(d)
    if cond == "B":
        shutil.copytree(os.path.join(RULES, ".scar"), os.path.join(d, ".scar"))
        g = os.path.join(ROOT, "scar_tissue", "guard.py")
        os.makedirs(os.path.join(d, ".claude"))
        json.dump({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": f"python3 {g}"}]}],
                             "SessionStart": [{"hooks": [{"type": "command", "command": "cat .scar/brief.md 2>/dev/null || true"}]}]}},
                  open(os.path.join(d, ".claude", "settings.json"), "w"))
    if cond == "C":
        open(os.path.join(d, "CLAUDE.md"), "w").write(NOTE)


def run(job):
    task, cond, rep = job
    rid = f"{task}-{cond}-{rep}"; d = os.path.join(HERE, "runs", rid, "repo")
    if os.path.exists(os.path.join(HERE, "runs", rid, "result.json")):
        return json.load(open(os.path.join(HERE, "runs", rid, "result.json")))
    os.makedirs(os.path.dirname(d), exist_ok=True); shutil.rmtree(d, ignore_errors=True); setup(cond, d)
    t = time.time()
    p = subprocess.run(["claude", "-p", TASKS[task], "--allowedTools", "Bash", "--disallowedTools", "Read Grep Glob Edit Write Task WebFetch WebSearch", "--output-format", "stream-json", "--verbose"],
                       cwd=d, capture_output=True, text=True, timeout=600)
    open(os.path.join(HERE, "runs", rid, "stream.jsonl"), "w").write(p.stdout)
    calls, results, final, meta = {}, [], "", {}
    for line in p.stdout.splitlines():
        try: e = json.loads(line)
        except ValueError: continue
        if e.get("type") == "assistant":
            for b in e["message"]["content"]:
                if b["type"] == "tool_use": calls[b["id"]] = (b["name"], (b.get("input") or {}).get("command", ""))
                if b["type"] == "text": final = b["text"]
        elif e.get("type") == "user" and isinstance(e["message"]["content"], list):
            for b in e["message"]["content"]:
                if b.get("type") == "tool_result":
                    c = b["content"] if isinstance(b["content"], str) else " ".join(x.get("text", "") for x in b["content"] if isinstance(x, dict))
                    results.append((calls.get(b["tool_use_id"], ("?", "")), bool(b.get("is_error")), c))
        elif e.get("type") == "result":
            meta = {"turns": e.get("num_turns"), "duration_s": round((e.get("duration_ms") or 0) / 1000, 1), "cost_usd": e.get("total_cost_usd")}
    zsh = [r for r in results if r[0][0] == "Bash" and ((root_cause(r[2]) or (None,))[0] in ("zsh-equals", "zsh-nomatch")
                                                        or (silent_root_cause(r[2]) or (None,))[0] in ("zsh-equals", "zsh-nomatch"))]
    out = {"run": rid, "task": task, "cond": cond, "rep": rep,
           "bash_calls": sum(1 for r in results if r[0][0] == "Bash"), "tool_calls": len(results),
           "zsh_failures": len(zsh), "blocked_by_guard": sum(1 for r in results if "[scar-tissue]" in r[2]),
           "tool_errors": sum(1 for r in results if r[1]),
           "answer_recall": round(sum(1 for x in EXPECT[task] if x in final) / len(EXPECT[task]), 2), **meta,
           "wall_s": round(time.time() - t, 1)}
    json.dump(out, open(os.path.join(HERE, "runs", rid, "result.json"), "w"))
    return out


if __name__ == "__main__":
    tasks = sys.argv[1].split(",") if len(sys.argv) > 1 else list(TASKS)
    conds = sys.argv[2].split(",") if len(sys.argv) > 2 else ["A", "B", "C"]
    reps = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    jobs = [(t, c, r) for r in range(reps) for t in tasks for c in conds]
    with ThreadPoolExecutor(2) as ex:
        for res in ex.map(run, jobs):
            print(json.dumps(res), flush=True)
            open(os.path.join(HERE, "results.jsonl"), "a").write(json.dumps(res) + "\n")

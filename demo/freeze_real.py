"""Freeze the real-data numbers used in the README/video (aggregate counts and signatures only — no transcript content).
Usage: python3 demo/freeze_real.py '<claude transcripts glob>' [swe_agent_rows.jsonl]"""
import datetime, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
from scar_tissue import application, domain
from scar_tissue.adapters import claude_code, swe_agent

OUT = os.path.join(HERE, "recordings")
now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M KST")
events, n = claude_code.read_dir(sys.argv[1])
st = application.stats(events, n)
st["_meta"] = {"command": "scar stats '~/.claude/projects/**/*.jsonl'", "run": now,
               "scope": "every Claude Code transcript on the author's laptop; subagent transcripts folded into their parent session"}
# trend: zsh root-cause failures per 1,000 Bash calls, by 10-day bucket
from collections import Counter
tot, z = Counter(), Counter()
for e in events:
    if e.tool == "Bash" and e.ts and e.kind in ("tool_ok", "tool_error"):
        d = e.ts[:10]; b = d[:8] + ("01-09" if d[8:] < "10" else "10-19" if d[8:] < "20" else "20-31")
        tot[b] += 1
        z[b] += domain.signature(e)[2] in ("zsh-equals", "zsh-nomatch")
days = {}
for e in events:
    if e.tool == "Bash" and e.ts and e.kind in ("tool_ok", "tool_error"):
        d = e.ts[:10]; b = d[:8] + ("01-09" if d[8:] < "10" else "10-19" if d[8:] < "20" else "20-31")
        lo, hi = days.get(b, (d, d)); days[b] = (min(lo, d), max(hi, d))
st["zsh_trend_per_1000_bash_calls"] = [{"from": days[b][0], "to": days[b][1], "bash_calls": tot[b], "zsh_failures": z[b],
                                        "per_1000": round(1000 * z[b] / tot[b], 1)} for b in sorted(tot) if tot[b] >= 1000]
json.dump(st, open(os.path.join(OUT, "stats-real.json"), "w"), indent=1)
open(os.path.join(OUT, "stats-real.txt"), "w").write(application.stats_table(st))
ho = application.holdout(events)
ho["sessions_total"] = n
ho["_meta"] = {"command": "scar holdout '~/.claude/projects/**/*.jsonl'", "run": now,
               "method": "learn from the earliest 70% of sessions (by first timestamp), replay the later 30%; Bash calls only"}
json.dump(ho, open(os.path.join(OUT, "holdout-real.json"), "w"), indent=1)

# threshold sensitivity: the same holdout under other demotion thresholds (the defaults were chosen on this data)
grid = []
orig_ratio, orig_validate = domain.BENEFIT_RATIO, application.validate_against_history
for ratio, max_count, max_rate in [(20, 3, 0.005), (10, 3, 0.005), (50, 3, 0.005), (20, 0, 0.001), (1, 3, 0.005)]:
    domain.BENEFIT_RATIO = ratio
    application.validate_against_history = lambda sc, ev, mc=max_count, mr=max_rate: orig_validate(sc, ev, max_rate=mr, max_count=mc)
    h = application.holdout(events)
    grid.append({"benefit_ratio": ratio, "max_false_blocks": max_count, "max_rate": max_rate, **{k: h[k] for k in
                 ("guard_rules", "test_failures", "test_failures_blocked", "test_successes", "test_successes_blocked")}})
domain.BENEFIT_RATIO, application.validate_against_history = orig_ratio, orig_validate
json.dump({"_meta": {"run": now, "note": "first row = defaults"}, "grid": grid}, open(os.path.join(OUT, "sensitivity-real.json"), "w"), indent=1)

if len(sys.argv) > 2:
    ev2, n2 = swe_agent.read(sys.argv[2])
    sw = application.stats(ev2, n2)
    sw["_meta"] = {"command": "scar stats rows.jsonl --format swe-agent", "run": now,
                   "data": "2,000 rows of huggingface.co/datasets/nebius/SWE-agent-trajectories (CC-BY-4.0): 100 rows at offsets 0, 4000, …, 76000"}
    json.dump(sw, open(os.path.join(OUT, "swe-agent-public.json"), "w"), indent=1)
if len(sys.argv) > 3:   # another person's public Claude Code transcripts (same adapter, unchanged)
    ev3, n3 = claude_code.read_dir(sys.argv[3])
    wi = application.stats(ev3, n3)
    wi["_meta"] = {"command": "scar stats '<wisp transcripts>/**/*.jsonl'", "run": now,
                   "data": "huggingface.co/datasets/crispwisp/wisp-claude-code-sessions (MIT), all 104 transcript files"}
    json.dump(wi, open(os.path.join(OUT, "wisp-public.json"), "w"), indent=1)
print("frozen", now)

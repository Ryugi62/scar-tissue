# Scar: pgrep -f (timeout)

**Principle.** `pgrep -f` ran until the tool timeout 4× across 3 sessions — bound the wait: a fixed retry count or a time limit.

**Signature.** `Bash:pgrep -f:timeout` — 4 failures, 0 corrections, 3 sessions.

**Guard.** PreToolUse rule `bash-pgrep-f-timeout` blocks Bash calls with `pgrep -f` inside an unbounded while/until loop — except the shape of the agent's own fix (\bfor\s+\w+\s+in\s+(?:\{\d+\.\.\d+\}|\$\(seq\b), -f\s+['\"]?\[[^\]]+\]).

## Evidence
- 2026-10-01T09:00 · session `s1` · tool_error · `until ! pgrep -f build.py; do sleep 5; done`
- 2026-10-02T13:10 · session `s2` · tool_error · `while pgrep -f 'node server'; do sleep 2; done`
- 2026-10-03T22:40 · session `s3` · tool_error · `while pgrep -f render.py >/dev/null; do sleep 30; done`
- 2026-10-03T22:55 · session `s3` · tool_error · `until ! pgrep -f render.py; do sleep 10; done`

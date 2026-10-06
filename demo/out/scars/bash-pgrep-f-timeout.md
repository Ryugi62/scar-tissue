# Scar: pgrep -f (timeout)

**Principle.** Avoid long-running pgrep polling loops that hit timeouts; instead, use a bounded timeout, check process status less frequently, or switch to event/log-based completion detection.

**Signature.** `Bash:pgrep -f:timeout` — 4 failures, 0 corrections, 3 sessions.

**Guard.** PreToolUse rule `bash-pgrep-f-timeout` blocks `Bash` calls matching `(?:^|[;&|(!]\s*|\b(?:do|then|until|while|if)\s+)pgrep\s+\-f[A-Za-z]?(?=\s|$)`.

## Evidence
- 2026-10-01T09:00 · session `s1` · tool_error · `until ! pgrep -f build.py; do sleep 5; done`
- 2026-10-02T13:10 · session `s2` · tool_error · `while pgrep -f 'node server'; do sleep 2; done`
- 2026-10-03T22:40 · session `s3` · tool_error · `pgrep -f render && sleep 30`
- 2026-10-03T22:55 · session `s3` · tool_error · `until ! pgrep -f render.py; do sleep 10; done`

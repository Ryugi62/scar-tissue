# Scar: timeout (missing-command)

**Principle.** `timeout` is not installed on this machine (failed 3× (missing-command) across 2 sessions).

**Signature.** `Bash:timeout:missing-command` — 3 failures, 0 corrections, 2 sessions.

**Guard.** PreToolUse rule `bash-timeout-missing-command` blocks `Bash` calls matching `(?:^|[;&|(!{]\s*|\n\s*|\b(?:do|then|else|until|while|if|time|sudo|env|nohup|exec)\s+)timeout(?=\s|$)`.

## Evidence
- 2026-10-02T10:00 · session `s2` · tool_error · `timeout 60 npm test`
- 2026-10-03T14:00 · session `s3` · tool_error · `cd api && timeout 30 python3 smoke.py`
- 2026-10-03T14:30 · session `s3` · tool_error · `timeout 5 curl -s localhost:8080/health`

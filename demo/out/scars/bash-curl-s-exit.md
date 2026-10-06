# Scar: curl -s (exit)

**Principle.** Avoid relying on `curl -s` piped to `grep` for validation; use a request that checks status/content explicitly and handle missing matches without failing the command.

**Signature.** `Bash:curl -s:exit` — 3 failures, 0 corrections, 2 sessions.

**Guard.** PreToolUse rule `bash-curl-s-exit` blocks `Bash` calls matching `(?:^|[;&|(!]\s*|\b(?:do|then|until|while|if)\s+)curl\s+\-s[A-Za-z]?(?=\s|$)`.

## Evidence
- 2026-10-02T11:00 · session `s2` · tool_error · `curl -s https://example-hackathon.dev/rules | grep prize`
- 2026-10-03T09:30 · session `s3` · tool_error · `curl -s https://another-contest.app/ | grep deadline`
- 2026-10-03T09:35 · session `s3` · tool_error · `curl -sL https://spa.example.org/terms | grep -i eligib`

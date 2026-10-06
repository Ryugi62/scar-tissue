# Scar: curl -s (exit)

**Principle.** Avoid `curl -s` here — it failed 3× (exit) across 2 sessions. Use the safer alternative, or ask first.

**Signature.** `Bash:curl -s:exit` — 3 failures, 0 corrections, 2 sessions.

**Advice only.** Too broad for an automatic block (already guarded, a whole tool, or a generic command) — review by hand.

## Evidence
- 2026-10-02T11:00 · session `s2` · tool_error · `curl -s https://example-hackathon.dev/rules | grep prize`
- 2026-10-03T09:30 · session `s3` · tool_error · `curl -s https://another-contest.app/ | grep deadline`
- 2026-10-03T09:35 · session `s3` · tool_error · `curl -sL https://spa.example.org/terms | grep -i eligib`

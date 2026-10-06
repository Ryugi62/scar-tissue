# Scar: git push (corrected)

**Principle.** Never force-push main; use a normal push or create a new branch instead.

**Signature.** `Bash:git push:corrected` — 0 failures, 2 corrections, 2 sessions.

**Guard.** PreToolUse rule `bash-git-push-corrected` blocks `Bash` calls matching `(?=.*\s\-\-force(?:\s|$))(?:^|[;&|(!]\s*|\b(?:do|then|until|while|if)\s+)git\s+push(?=\s|$)`.

## Evidence
- 2026-10-01T10:01 · session `s1` · user_correction · `no, never force-push main`
- 2026-10-02T15:02 · session `s2` · user_correction · `stop force pushing, I told you yesterday`

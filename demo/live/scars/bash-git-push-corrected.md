# Scar: git push (corrected)

**Principle.** Avoid `git push --force` here — it was corrected by the human 2×. The human said: "stop force pushing, I told you yesterday". Use the safer alternative, or ask first.

**Signature.** `Bash:git push:corrected` — 0 failures, 2 corrections, 2 sessions.

**Guard.** PreToolUse rule `bash-git-push-corrected` blocks Bash calls with `git push --force`.

## Evidence
- 2026-10-01T10:01 · session `s1` · user_correction · `no, never force-push main`
- 2026-10-02T15:02 · session `s2` · user_correction · `stop force pushing, I told you yesterday`

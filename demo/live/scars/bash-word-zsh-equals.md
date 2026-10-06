# Scar: =word (zsh-equals)

**Principle.** This shell is zsh: an unquoted word starting with `=` (`===`, `[ a == b ]`) is expanded as a command path and fails — quote it or use `[[ … ]]` (failed 3× (zsh-equals) across 2 sessions).

**Signature.** `Bash:=word:zsh-equals` — 3 failures, 0 corrections, 2 sessions.

**Guard.** PreToolUse rule `bash-word-zsh-equals` blocks `Bash` calls matching `(?:^|\s)=[^\s(]\S*`.

## Evidence
- 2026-10-01T12:00 · session `s1` · tool_error · `make build && echo === Build done ===`
- 2026-10-02T09:00 · session `s2` · tool_error · `if [ "$CI" == true ]; then npm ci; fi`
- 2026-10-02T17:20 · session `s2` · tool_error · `echo ==== deploy ====; ./deploy.sh`

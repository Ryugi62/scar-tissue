# What your agent keeps getting wrong

3 sessions · 41 tool calls · 16 failed · 0 silent failures (exit 0, but the shell printed an error)

| scar | failures | sessions | status | Worked before |
|---|---|---|---|---|
| `Bash:pgrep -f:timeout` | 4 | 3 | GUARD | `for i in $(seq 1 60); do pgrep -f '[b]uild.py' >/dev/null ¦¦ break; sl` |
| `Bash:git push:corrected` | 2 | 2 | GUARD |  |
| `Bash:=word:zsh-equals` | 3 | 2 | GUARD | `echo "=== Build done ==="` |
| `Bash:timeout:missing-command` | 3 | 2 | GUARD | `perl -e 'alarm 60; exec @ARGV' npm test` |
| `Bash:curl -s:exit` | 3 | 2 | advice |  |

**The guard rules** would match 10 of 16 failed shell commands (62.5%) and block 0 of 23 successful ones (0.00%).

## One-line environment fixes (for you, the human)
- `unsetopt EQUALS` in the zsh profile the agent's shell loads (makes `===` a plain word)
- install `timeout` or keep the guard (for `timeout`: `brew install coreutils` provides `gtimeout`)

## Next
```
scar heal '<logs>' --out .     # scars/*.md to review + .scar/rules.json
scar install --yes              # PreToolUse guard + SessionStart brief in .claude/settings.json
```

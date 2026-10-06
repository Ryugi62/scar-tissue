# Scar Tissue — SPEC

## Purpose
AI coding agents (Claude Code, Codex, …) run for hours on a developer's own machine and repeat the same mistakes across sessions: they wait forever on a `pgrep -f` loop, push to the wrong branch, conclude "not found" from a page they never read. Each session starts fresh, so the lesson is lost. **Scar Tissue turns repeated failures into guardrails**: it reads agent session logs, finds failures that happened ≥3 times (or were corrected by the human ≥2 times), writes a short *scar* (principle + evidence), and compiles it into a **PreToolUse hook rule** that blocks the same mistake next time — with the scar's explanation shown to the agent.

## Success criteria (numbers)
- `scar scan` on the bundled demo logs (3 sessions) finds exactly the 5 seeded repeated-failure patterns (3 head habits + 2 root causes, v2) and 0 false scars from 1-off errors.
- `scar heal` writes one markdown scar + one rule per pattern; every rule blocks its original failing commands (recall 100% on the seed set) and allows the bundled list of 30 safe commands (0 false blocks).
- The guard hook decides in < 50 ms per call, uses stdlib only.
- Real-world run: scanning the author's own local Claude Code transcripts produces aggregate counts only (sessions, tool calls, failures, signatures ≥3) — no transcript content leaves the machine.

## Ubiquitous language
- **event** — one normalized record from a log: `{ts, session, kind, tool, command, text}`; kind ∈ `tool_error | user_correction | hook_block`.
- **signature** — a normalized key for "the same mistake": tool + command head (first 2 meaningful tokens, paths/numbers/quotes stripped) + error class.
- **scar** — a signature that crossed the threshold (≥3 failures across ≥2 sessions, or ≥2 user corrections). Has: title, evidence (timestamps, sessions), rule.
- **rule** — `{id, tool, pattern (regex on the tool input), message, scar}`; enforced by the guard.
- **guard** — the PreToolUse hook script: reads the hook JSON on stdin, exits 2 with the scar message if a rule matches, else 0.

## Given / When / Then
1. Given 3 sessions where `pgrep -f` in a wait loop timed out 4 times, When `scar scan`, Then one candidate with signature `Bash:pgrep -f:timeout` and count 4.
2. Given a single `npm test` failure, When `scar scan`, Then no scar (below threshold).
3. Given a user message "stop force-pushing" after `git push --force` twice, When scan, Then a scar from user corrections (threshold 2).
4. Given the scars, When `scar heal`, Then `scars/<slug>.md` and `.scar/rules.json` exist; When the guard gets `{"tool_name":"Bash","tool_input":{"command":"pgrep -f server && sleep 5"}}`, Then exit 2 and stderr contains the scar title.
5. Given a safe command `ls -la`, When the guard runs, Then exit 0 and no output.
6. Given `--llm openai` and `OPENAI_API_KEY`, When heal, Then the scar's "principle" line is phrased by the model; without a key, a deterministic template is used (same rule).

## Non-goals
- Not a general log analytics product; no cloud upload; no auto-editing of the agent's own config without `scar install --yes`.
- Does not judge whether a scar is "right" — the human reviews `scars/*.md` (they are plain markdown, committed with the project).

## Architecture
`scar_tissue/domain.py` (signatures, clustering, rule compilation — pure) ← `application.py` (scan/heal use cases) ← `adapters/` (Claude Code transcript reader, generic JSONL reader, OpenAI phrasing) ← `cli.py`. `guard.py` is a standalone stdlib script.

## v2 — root causes and recoveries (OFFGRID week 2)
Problem found on real logs: most repeated failures are *environment* mistakes that the command head hides (`echo === Done ===` fails in zsh; `timeout` does not exist on macOS) — and a rule must never block the fix the agent already found.

### Ubiquitous language (added)
- **root cause** — a cause extracted from the error text, independent of the command head: `missing-command:<name>` (`command not found: timeout`), `zsh-equals` (`(eval):1: === not found` — an unquoted word starting with `=`), `zsh-nomatch:<shape>` (`no matches found: --include=*.md`). A root-cause scar's signature is `tool:<cause head>:<cause class>`.
- **shell view** — the command as the shell parses words: heredoc bodies, quoted strings, `[[ … ]]`, `(( … ))` and comments blanked. Root-cause rules match the shell view, so `echo "=== x ==="` or a Python heredoc with `a == b` never trip them.
- **recovery** — the next successful call in the same session, same tool, same command head, within 6 calls after a failure: the agent's own fix.
- **unless** — rule exemptions learned from recoveries: remedy markers (bounded loop, `timeout`/`perl alarm` wrapper, bracket self-match pattern) and flags present in a recovery but in no failure.
- **fix-safety** — a rule must not block any recorded recovery; if it still would after `unless`, the scar is demoted to advice.

### Given / When / Then (added)
7. Given `zsh: command not found: timeout` 3× across 2 sessions (heads `afconvert`, `python3`, `bash`), When scan, Then one scar `Bash:timeout:missing-command`; its rule blocks `timeout 60 make` and `cd x && timeout 5 curl y`, allows `gtimeout 60 make`, `echo "timeout"`, `perl -e 'alarm 60; exec @ARGV' make`.
8. Given `(eval):1: === not found` / `== not found` 3× across 2 sessions, When scan, Then one scar `Bash:=word:zsh-equals`; its rule blocks `echo === Done ===` and `[ "$a" == b ]`, allows `echo "=== Done ==="`, `[[ $a == b ]]`, `a=b make`, and a heredoc `python3 - <<'EOF'` containing `if a == b:`.
9. Given `no matches found: --include=*.md` 3× across 2 sessions, Then scar `Bash:--include=*:zsh-nomatch`; rule blocks `grep -rn foo . --include=*.md`, allows `grep -rn foo . --include='*.md'`.
10. Given pgrep -f timeouts each followed by a successful bounded loop `for i in $(seq 1 60); do pgrep -f '[b]uild.py' … done`, When heal, Then the rule blocks `until ! pgrep -f build.py; do sleep 5; done` but allows the recovery and `for i in {1..30}; do pgrep -f '[w]orker' || break; sleep 2; done`; the guard message contains `Worked before:`.
11. Fix-safety: no compiled rule matches any recovery in the logs it was learned from (checked on the demo set and the real-data run).
12. `Permission to use Bash … has been denied` is class `blocked` (already guarded by the permission system), not a new scar.
13. `scar demo` runs scan → heal → guard on the bundled logs in a temp dir, prints which commands are blocked/allowed, needs no network, exits 0 in < 2 s.

### Success criteria (added, real data — aggregate only)
- Holdout on the author's transcripts (learn from the earliest 70% of sessions, replay the last 30%): report Bash failures prevented and successful calls wrongly blocked; wrongly blocked ≤ 0.1%.

## v3 — review fixes (OFFGRID week 2)
- Rules are structured (`kind: head | missing-command | zsh-equals | zsh-nomatch`) and matched per simple command by `scar_tissue/shell.py`, a linear-time tokenizer (quotes, escapes, heredocs, comments, `[[ ]]`/`(( ))`, loop context, `$(…)`/backticks, `bash -c` payloads parsed as bash). Probes in `tests/test_shell.py` are the acceptance criteria: `git push -f`, `git -C x push --force`, `FOO=1 timeout`, `nice/xargs/command timeout`, backticks are caught; `pgrep -f server` (one-shot), `echo do timeout 5`, `--include=\*.md`, `bash -c 'echo === x'` pass; pathological inputs parse in < 0.25 s.
- A head habit learned only inside unbounded `while`/`until` loops is enforced only there (`context: loop`).
- Corrections count only if the message shares a word (≥3 letters) with the call; polite phrases ("no worries", "never mind") never count.
- Subagent transcripts are folded into their parent session; holdout and stats use Bash-only denominators; stats report per-rule matches split into exit ≠ 0 / silent, the failure cost (calls and seconds to the agent's fix, silent failures never fixed), demoted candidates, and a zsh trend.
- Override: `# scar-ok: <reason>` works only when a rule matches, is logged with the rule id, at most 3 times per rule.
- SessionStart reads `.scar/brief.md` written by `heal` (no rescan at startup). `scar report` = read-only markdown report with environment fixes.

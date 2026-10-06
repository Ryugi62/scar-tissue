# Scar Tissue

**Your AI coding agent's repeated mistakes become guardrails — learned from its own logs.**

Coding agents (Claude Code, Codex, Cursor) start every session fresh, so they repeat the same mistakes. Scar Tissue reads the agent's session logs, finds failures that repeat across sessions, and compiles each one into a Claude Code `PreToolUse` hook that blocks the habit *and tells the agent what worked last time*.

On my laptop (1,444 Claude Code sessions, 151,783 tool calls), **3 learned rules match 45.6% of my agent's failed shell commands** (2,801 of 6,144) and would block **16 of 94,109 successful ones**. Learned only from my earlier sessions, they would have blocked **41.8% (1,499 of 3,586) of the later sessions' failures**, with 9 wrong blocks in 56,201 calls.

```bash
pipx install git+https://github.com/Ryugi62/scar-tissue    # or: pip install git+https://github.com/Ryugi62/scar-tissue
scar demo                                   # 2 seconds: bundled logs → scars → the real guard script, no network, changes nothing
scar report '~/.claude/projects/**/*.jsonl' # read-only: what your agent keeps getting wrong, and the fixes that worked
```

```
3) guard (the real PreToolUse hook script) on the agent's next calls:
   BLOCKED  until ! pgrep -f build.py; do sleep 5; done   # the habit that timed out 4×
            ↳ `pgrep -f` ran until the tool timeout 4× across 3 sessions — bound the wait … Worked before: `for i in $(seq 1 60); do pgrep -f '[b]uild.py' …`
   allowed  for i in $(seq 1 60); do pgrep -f '[b]uild.py' >/dev/null || break; sleep 5; done   # the agent's own fix, learned from the logs
   BLOCKED  echo === Tests passed ===   # zsh expands `===`
   allowed  echo "=== Tests passed ==="   # quoted
   BLOCKED  timeout 120 pytest -q   # no GNU timeout on this machine
   BLOCKED  git push --force origin main   # the human said no, twice
   allowed  git push origin feature-x   # normal work
```

## What it found on my laptop
One frozen run over every Claude Code transcript on my machine (`demo/recordings/stats-real.json` / `.txt` — aggregate counts and signatures only; subagent transcripts are folded into their parent session):

| rule learned from my logs | failures it matches | of which exit ≠ 0 | sessions | successful calls it would block |
|---|---|---|---|---|
| unquoted `=` word in zsh (`echo ===`, `[ a == b ]`) | 1,592 | 1,521 | 319 | 3 |
| unquoted `--include=*…` glob in zsh | 1,224 | 35 | 442 | 11 |
| `pdffonts` is not installed | 5 | 0 | 2 | 2 |

The agent kept writing bash in a zsh shell. `echo === Done ===` or `[ "$a" == b ]` fails in zsh (an unquoted word starting with `=` is expanded as a command path), and an unquoted `--include=*.md` makes zsh abort the command with "no matches found". Each session starts fresh, so it never learned.

**The silent ones are the dangerous ones.** 1,189 of the 1,224 `--include` failures exited 0: the search was aborted, the pipe printed nothing, and the call "succeeded". In **351 of them the agent never re-ran the search** within the next 6 calls — it moved on believing nothing was found. The loud failures are cheap by comparison: the median one cost 1 extra call (~4 s) before the agent fixed it (`failure_cost` in the same file).

**Is it still happening?** zsh failures per 1,000 shell calls: 55 (Sep 1–9) → 40 (Sep 10–19) → 37 (Sep 20–30) → 30 (Oct 1–6). The rate is falling, but it still happened 857 times in the first six days of October. In 4 short, fresh sessions with today's model the agent made none (pilot in `demo/ab/`) — the habit lives in long, busy sessions.

**Couldn't I just change a shell option?** Yes — `setopt NO_NOMATCH` and `unsetopt EQUALS` would remove the two big ones, and `scar report` prints exactly those lines. I didn't know I needed them until the logs said so. The guard is for what an option can't fix (a missing binary, a wait loop that hangs, a push the human said no to) and for machines where you don't want to change your own shell.

## Live: a Claude Code session meets a scar (prompted)
`demo/recordings/live-claude-code-block.txt` — a real `claude -p` run against the current guard, rendered from its stream-json events. The prompt **asks** for the scarred command (the rule comes from the bundled demo logs), to show what happens at the block:

```
── agent → Bash ──
$ until ! pgrep -f build.py; do sleep 2; done; echo done
── BLOCKED by hook (exit 2) ──
[scar-tissue] blocked by scar `bash-pgrep-f-timeout` (4 failures, 0 corrections, 3 sessions): `pgrep -f` ran until the tool
timeout 4× across 3 sessions — bound the wait: a fixed retry count or a time limit. Worked before: `for i in $(seq 1 60); do
pgrep -f '[b]uild.py' >/dev/null || break; sleep 5; done`
── agent → Bash ──
$ for i in $(seq 1 60); do pgrep -f '[b]uild.py' >/dev/null || break; sleep 2; done; echo "waited ~$((i*2))s"; …
── result ──
waited ~10s
── agent → Bash ──
$ ls -la build/ 2>&1; echo ---; cat build/out.txt
── result ──
build ok: 42 files compiled
```
The agent took the fix from the block message, the guard let it through, and the task finished (4 turns, 23 s). In its answer it explained the root cause on its own — `pgrep -f build.py` matches the shell running the loop.

## Use it on your own agent
```bash
cd your-project
scar report '~/.claude/projects/**/*.jsonl'         # read-only markdown report
scar heal   '~/.claude/projects/**/*.jsonl' --out . # scars/*.md (review + commit), .scar/rules.json, .scar/brief.md
scar install                                        # dry run: prints the hook entries
scar install --yes                                  # guard (PreToolUse) + brief (SessionStart: cat .scar/brief.md) in .claude/settings.json
scar stats '<logs>' --table · scar holdout '<logs>' # aggregate numbers only
```
Other agents can feed it: `--format events` takes a generic JSONL of `{ts, session, kind, tool, command, text}`, and `--format swe-agent` reads SWE-agent trajectories. Enforcement is Claude Code hooks for now.

## How it decides
- **Root cause first.** If the error text names the cause, that is the signature, whatever the command was: `command not found: timeout` → `timeout:missing-command`; `(eval):1: == not found` → `=word:zsh-equals`; `no matches found: --include=*.md` → `--include=*:zsh-nomatch`. Otherwise: tool + command head + error class (timeout, permission, rejected, corrected…).
- **Silent failures count.** A call that exits 0 but printed a shell error (`grep … --include=*.md | head`) is a failure, not normal work.
- **Rules are matched by a shell tokenizer, not regexes** (`scar_tissue/shell.py`, linear time). It knows which simple commands run, which characters were quoted or escaped, heredocs and comments, `[[ ]]`/`(( ))`, the loop each command sits in, `$(…)`/backticks, and that a `bash -c '…'` payload is bash, not zsh. Head rules see through `FOO=1`, `nice`, `xargs`, `command`, `timeout`, git global options (`git -C x push`) and flag aliases/clusters (`-f` = `--force`, `-fu`).
- **Rules come from evidence, not from the model.** A habit learned inside wait loops is only blocked inside an unbounded `while`/`until` loop (a one-shot `pgrep -f server` passes). Head rules require the flags every example shared (`git push` passes, `git push --force` does not). An optional LLM (`--llm openai`) only rephrases the advice for head habits.
- **The guard never blocks the agent's own fix.** After a failure, the next successful call doing the same job is recorded as a *recovery*; its distinguishing shape becomes an exemption, and the one simple command that carries the fix is shown as "Worked before". A rule that would still block a recorded recovery is demoted.
- **A human "no" counts only if it talks about the call.** A correction ("stop force pushing") is pinned on the last call only if it shares a word with it; "no worries" or a "no" about something else is ignored.
- **Precision over coverage.** Every candidate is replayed against the agent's own successful history and demoted to advice if it would block normal work more than 3 times *and* more than once per 20 mistakes it stops, or more than 0.5% of all successful calls. "Any unquoted glob" stopped 873 failures but would have blocked 8,358 successful calls — demoted. `timeout` is missing in my main shell but ran fine 117 times in other sessions — demoted. Those stay advice, injected at session start from `.scar/brief.md`.
- **The thresholds do not drive the result.** They were set on this data, but the holdout gives the same result with the benefit ratio at 10, 20 or 50 (`demo/recordings/sensitivity-real.json`); only a ratio of 1 lets weak rules through (4 rules, 94 wrong blocks instead of 9).
- **Escape hatch with a budget.** If the agent is sure, it appends `# scar-ok: <reason>`; the guard lets it through and logs it to `.scar/overrides.jsonl` — at most 3 times per scar, then a human has to look.

## Not just my machine?
On 2,000 public SWE-agent trajectories ([nebius/SWE-agent-trajectories](https://huggingface.co/datasets/nebius/SWE-agent-trajectories), CC-BY-4.0; `demo/recordings/swe-agent-public.json`), another agent with another model and shell repeats itself too: 321 failure signatures repeated ≥3 times — e.g. `cd..` without a space 987 times in 25 runs. But Scar Tissue's rules there match only 524 of 23,520 failures (2.2%): most of that agent's failures are outcomes (an `edit` that introduced a syntax error, 6,772× in 968 runs), which no pre-execution hook can stop, and its blockable habits are tied to one repository's container. The adapter reads them; the guard is built for a developer's own machine.

## Limitations
- One user, one laptop. The holdout is a time split on the same machine, not another person's logs.
- The live run is prompted; real-world effect is measured by replaying history, not by a controlled live experiment (the 4-run pilot had no zsh mistakes to stop).
- Enforcement is Claude Code only; the SWE-agent and generic-JSONL adapters scan and report.
- Human corrections need to share a word with the call they correct, so only 5 were found in my logs; most scars come from errors.

## Tests
```bash
python3 -m unittest discover -s tests    # 52 tests: tokenizer probes (aliases, wrappers, quoting, heredocs, bash -c, loops), root causes, silent failures, recoveries, fix-safety, cost-benefit demotion, override budget, corrections, adapters, report, `scar demo`
```
Standard library only (Python ≥ 3.9). The guard decides in milliseconds and looks at most at the first 20,000 characters of a command.

## Built during OFFGRID
Everything in this repo was written during the hackathon window (Oct 2026; see the commit history). I run a personal agent OS on Claude Code every day and had hand-written dozens of hooks, one incident at a time, after the agent repeated a mistake. While building this, my own agent hit `command not found: timeout` again. The incidents are already in the logs — the guardrails should write themselves. It reads standard Claude Code transcript files and does not include my private setup.

## Next
Codex and Cursor log adapters with enforcement, team mode (scars reviewed and shared through the repo), and scar decay (rules expire when the failure stops recurring).

MIT License

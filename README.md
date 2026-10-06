# Scar Tissue

**Your AI coding agent's repeated mistakes become guardrails — learned from its own logs.**

Coding agents (Claude Code, Codex, Cursor) start every session fresh, so they repeat the same mistakes, and some of those mistakes look like success. Scar Tissue is two Claude Code hooks and a log scanner:

1. **A silent-failure alarm (day one, no history needed).** When a shell command exits 0 but the shell printed an error mid-way — zsh aborted a `grep`, a tool wasn't installed — the agent is told right away that part of the command did not run, instead of reading the empty output as "nothing found".
2. **Learned guards.** `scar` reads the agent's session logs, finds failures that repeat across sessions, and compiles each into a `PreToolUse` rule that blocks the habit *and shows the fix that worked last time*.

On my laptop (1,476 Claude Code sessions, 152,618 tool calls): **2,202 shell calls exited 0 while the shell had printed an error that the command itself caused** — for the two most common causes, the agent did not retry 370 of them within its next 6 calls. **2 learned rules match 47.0% of the agent's failed shell commands** (2,836 of 6,036) and would block 18 of 94,821 successful ones. Learned only from my earlier sessions, they would have blocked **43.4% of the later sessions' failures** (1,524 of 3,510), with 12 wrong blocks in 56,463 calls.

```bash
pipx install git+https://github.com/Ryugi62/scar-tissue    # or: pip install git+https://github.com/Ryugi62/scar-tissue
scar demo                                   # 2 seconds: bundled synthetic logs → scars → the real guard script; no network, changes nothing
scar report '~/.claude/projects/**/*.jsonl' # read-only: what your agent keeps getting wrong, and the fixes that worked
```

## Day one: the silent-failure alarm
Claude Code shows the agent `exit 0` plus whatever was printed. If zsh aborted part of a pipeline (`grep -rn TODO . --include=*.md | head` → `(eval):1: no matches found: --include=*.md`), the call still "succeeds". `scar install` adds the same `guard.py` as a `PostToolUse` hook: if a Bash result contains a line printed by the shell itself (`(eval):N:`, `zsh:N:`, `bash: line N:`) **and the command confirms the cause** (the unquoted glob or `==` word, or the missing command, is really in it — so `cat ci.log` or a deliberate `rg … || grep …` fallback stays quiet), it answers with exit 2 and an explanation, once per command per session, and Claude Code hands that to the agent before its next step. It covers three causes today: unmatched globs, `==` words, missing commands.

**Does it change the outcome?** `demo/ab/alarm_ab.py` runs the same prompt in fresh `claude -p` sessions with and without the alarm (5 runs each, results in `demo/ab/alarm-ab.jsonl`). The prompt asks for a command whose `grep` fails silently in zsh:

| prompt | without the alarm | with the alarm |
|---|---|---|
| the error is the only output | 5/5 correct answers | 5/5 correct answers |
| the error is buried in other output (`cat …; grep …; ls`) | **2/5** — all 5 noticed the grep never ran; 3 stopped without a count, 2 re-ran it on their own | **5/5** — fixed the glob, re-ran, reported both TODOs |

Correct = the answer cites both grep hits (`docs/setup.md:2`, `docs/faq.md:2`). When the failure is obvious, today's model copes on its own. When it is buried in other output, it usually notices but often stops — the prompt says "run exactly", and the alarm's "fix it and run it again" overrides that. 2/5 vs 5/5 with n = 5 is a signal, not proof (one-sided Fisher p ≈ 0.08). *(A first version of the grader required the words "2 TODO" and scored the no-alarm arm 0/5; a reviewer caught it, and the table above is re-graded.)* An unedited run with the alarm, from a fresh project with no history (`demo/recordings/live-silent-alarm.txt`):

```
── agent → Bash ──
$ grep -rn TODO . --include=*.md | head
── result (exit 0) ──
(eval):1: no matches found: --include=*.md
── PostToolUse hook → agent (exit 2) ──
[scar-tissue] This command exited 0, but the shell printed `(eval):1: no matches found: --include=*.md` — that part did not run
(zsh aborted the command because an unquoted glob matched nothing). Do not read the empty or partial output as a result; fix it and run it again.
── agent → Bash ──
$ grep -rn TODO . --include='*.md' | head
── result (exit 0) ──
docs/faq.md:2:TODO: add retry section
docs/setup.md:2:TODO: document proxies
```

In my own history the alarm would have fired on those 2,202 calls. For the most common one (an aborted `--include` search), the agent did not retry the search within its next 6 calls 353 times out of 1,256 (`failure_cost` in `demo/recordings/stats-real.json`).

## Learned guards: what it found on my laptop
One frozen run over every Claude Code transcript on my machine (`demo/recordings/stats-real.json` / `.txt` — aggregate counts and signatures only; subagent transcripts are folded into their parent session):

| rule learned from my logs | failures it matches | of which exit ≠ 0 | sessions | successful calls it would block |
|---|---|---|---|---|
| unquoted `==` word in zsh (`echo === Done ===`, `[ "$a" == b ]`) | 1,601 | 1,529 | 319 | 3 |
| unquoted `--include=*…` glob in zsh | 1,256 | 35 | 473 | 15 |

(21 failed commands trip both rules; they are counted once in the 2,836.) The agent kept writing bash in a zsh shell, and every session started fresh, so it never learned. A loud failure was cheap: the median cost one extra call (~4 s) before the agent fixed it. The silent ones are the expensive ones (above).

**Is it still happening?** zsh failures per 1,000 shell calls: 52 (Sep 4–9) → 39 (Sep 10–19) → 36 (Sep 20–30) → 29 (Oct 1–6). The rate is falling, but it still happened 853 times in the first six days of October. In 4 short fresh sessions with today's model the agent made none (pilot in `demo/ab/`) — the habit lives in long, busy sessions.

**Couldn't I just change a shell option?** Yes — `setopt NO_NOMATCH` and `unsetopt EQUALS` remove these two, and `scar report` prints exactly those lines. I didn't know I needed them until the logs said so. That is the job: find the few things worth fixing in 150,000 tool calls, then fix each at the right layer — the environment, a guard, or advice at session start. The guard is for what an option can't fix (a missing binary, a wait loop that hangs, a push a human said no to) and for machines where you don't want to change your own shell.

## Live: a blocked habit (prompted, from the synthetic demo logs)
`demo/recordings/live-claude-code-block.txt` — a real `claude -p` run. The prompt **asks** for the scarred command, and the scar comes from the bundled synthetic logs; it shows what happens at the block, not how often it happens:

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
The agent took the fix from the block message, the guard let it through, and the task finished (4 turns, 23 s).

## Use it on your own agent
```bash
cd your-project
scar report '~/.claude/projects/**/*.jsonl'         # read-only markdown report
scar heal   '~/.claude/projects/**/*.jsonl' --out . # scars/*.md (review + commit), .scar/rules.json, .scar/brief.md
scar install                                        # dry run: prints the hook entries
scar install --yes                                  # guard (PreToolUse) + alarm (PostToolUse) + brief (SessionStart) in .claude/settings.json
scar stats '<logs>' --table · scar holdout '<logs>' # aggregate numbers only
```
Other agents can feed the scanner: `--format events` takes a generic JSONL of `{ts, session, kind, tool, command, text}`, and `--format swe-agent` reads SWE-agent trajectories. Enforcement is Claude Code hooks for now.

## How it decides
- **Root cause first.** If the error text names the cause, that is the signature, whatever the command was: `command not found: timeout` → `timeout:missing-command`; `(eval):1: == not found` → `=word:zsh-equals`; `no matches found: --include=*.md` → `--include=*:zsh-nomatch`. Otherwise: tool + command head + error class (timeout, permission, rejected, corrected…).
- **Silent failures count.** A call that exits 0 but printed a shell error its own command caused is a failure, not normal work.
- **Rules are matched by a shell tokenizer, not regexes** (`scar_tissue/shell.py`, linear time). It knows which simple commands run, which characters were quoted or escaped, heredocs and comments, `[[ ]]`/`(( ))`, the loop each command sits in (also inside `$(…)`), backticks, that a `bash -c '…'` payload is bash and not zsh, `eval '…'`, `find -exec`, wrappers with their own options (`env -i`, `nice -n`, `xargs -I`, `parallel`, `noglob`), git global options (`git -C x`, `--git-dir x`) and flag spellings (`-f` = `--force`, `-fu`, `+main`).
- **Rules come from evidence, not from the model.** A habit learned inside wait loops is only blocked inside an unbounded `while`/`until` loop (a one-shot `pgrep -f server` passes). Head rules require the flags every example shared (`git push` passes, `git push --force` does not). An optional LLM (`--llm openai`) only rephrases the advice for head habits.
- **The guard never blocks the agent's own fix.** After a failure, the next successful call doing the same job is recorded as a *recovery*; its distinguishing shape becomes an exemption, and the part that carries the fix is shown as "Worked before". A rule that would still block a recorded recovery is demoted.
- **A human "no" counts only if it talks about the call** ("stop force pushing" after `git push --force`), and the agent cannot override a scar a human created — only the human can.
- **Precision over coverage.** Every candidate is replayed against the agent's own successful history and demoted to advice if it would block one successful call per fewer than 20 mistakes it stops, or more than 0.5% of all successful calls. "Any unquoted glob" stopped 732 failures but would have blocked 8,588 successful calls — demoted. `timeout` is missing in my main shell but ran fine 117 times in other sessions — demoted. Those stay advice, injected at session start from `.scar/brief.md`.
- **The thresholds don't drive the result.** They were set on this data, but the holdout gives the same 2 rules and the same numbers with the ratio at 10, 20 or 50 (`demo/recordings/sensitivity-real.json`); only a ratio of 1 lets weak rules through.
- **Escape hatch with a budget.** If the agent is sure, it appends `# scar-ok: <reason>`; the guard lets it through and logs it to `.scar/overrides.jsonl` — at most 3 times per scar, then a human has to look.

## Someone else's logs, another agent
- **Another person's Claude Code logs.** [crispwisp/wisp-claude-code-sessions](https://huggingface.co/datasets/crispwisp/wisp-claude-code-sessions) (MIT; 103 sessions, 2,207 tool calls on an Arch Linux machine, bash). Scar Tissue, unchanged, found 1 repeated failure (advice), proposed **no blocks**, and the alarm would have fired on 3 calls (`demo/recordings/wisp-public.json`). It does not invent guardrails where there is no repeated habit.
- **Another agent.** On 2,000 public SWE-agent trajectories ([nebius/SWE-agent-trajectories](https://huggingface.co/datasets/nebius/SWE-agent-trajectories), CC-BY-4.0; `demo/recordings/swe-agent-public.json`), 321 failure signatures repeat ≥3 times — e.g. `cd..` without a space 987 times in 25 runs. But rules there match only 2.2% of failures: most of that agent's failures are outcomes (an `edit` that introduced a syntax error, 6,772× in 968 runs) that no pre-execution hook can stop, and its blockable habits are tied to one repository's container.

## Limitations
- One heavy user. The holdout is a time split on my machine; the second person's logs are small and had no repeated habit to learn.
- The live runs are prompted. The alarm A/B is 5 runs per arm on one task with a "run exactly" prompt; the learned guards' real-world effect is measured by replaying history, not by a controlled live experiment.
- On my data the learned guards come down to two zsh habits; the other 163 scars stay advice or were demoted.
- Enforcement is Claude Code only. The holdout covers the 952 of 1,476 sessions that have timestamped tool calls.

## Tests
```bash
python3 -m unittest discover -s tests    # 69 tests: tokenizer probes (aliases, wrappers, quoting, heredocs, bash -c, eval, find -exec, loops), root causes, silent failures + the alarm, recoveries, fix-safety, cost-benefit demotion, override budget, human-only override, corrections, adapters, report, `scar demo`
```
Standard library only (Python ≥ 3.9). The guard decides in milliseconds and looks at most at the first 20,000 characters of a command.

## Built during OFFGRID
Everything in this repo was written during the hackathon window (commits from 2026-10-06). I run a personal agent OS on Claude Code every day and had hand-written dozens of hooks, one incident at a time, after the agent repeated a mistake. While building this, my own agent hit `command not found: timeout` again. The incidents are already in the logs — the guardrails should write themselves. It reads standard Claude Code transcript files and does not include my private setup.

## Next
Codex and Cursor adapters with enforcement, team mode (scars reviewed and shared through the repo), and scar decay (rules expire when the failure stops recurring).

MIT License

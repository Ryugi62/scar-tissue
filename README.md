# Scar Tissue

**Your AI coding agent's repeated mistakes become guardrails — learned from its own logs.**

Coding agents (Claude Code, Codex, Cursor) start every session fresh, so they repeat the same mistakes. On my laptop, **46% of my agent's failed shell commands came from a handful of habits it never unlearned** — mostly writing bash in a zsh shell. Scar Tissue reads the agent's session logs, finds failures that repeat across sessions, and compiles each one into a Claude Code `PreToolUse` hook that blocks the habit *and tells the agent what worked last time*.

```bash
pipx install git+https://github.com/Ryugi62/scar-tissue    # or: pip install git+https://github.com/Ryugi62/scar-tissue
scar demo                                                 # 2 seconds, bundled logs, no network, changes nothing
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
One frozen run over every Claude Code transcript on my machine (`demo/recordings/stats-real.json`, aggregate counts only — no transcript content leaves the machine):

| | |
|---|---|
| transcripts scanned (main sessions + subagents) | 4,090 |
| tool calls | 151,235 |
| failed tool calls | 6,981 |
| **silent failures** — exit 0, but the shell printed an error mid-command | 2,323 |
| scars (same failure ≥3× across ≥2 sessions, or ≥2 human corrections) | 173 |
| automatic guard rules (after self-validation) | **4** |
| candidates demoted to advice because they would block normal work | 11 |
| failed shell commands the 4 rules match | **2,793 of 6,114 (45.7%)** |
| successful shell commands they would block | **19 of 93,709 (0.02%)** |

The two biggest scars were not "bad commands" but an environment mismatch the agent never learned: an unquoted word starting with `=` (`echo === Done ===`, `[ "$a" == b ]`) fails in zsh — **1,558 times across 830 sessions** — and an unquoted `--include=*.md` aborts zsh with "no matches found" — **1,191 times across 873 sessions**. Each session starts fresh, so the agent kept doing it.

**Would it have helped?** `scar holdout` learns only from the earliest 70% of sessions and replays the rest: 3 rules learned from 2,417 earlier sessions would have blocked **486 of 1,206 failures (40.3%)** in the 1,037 later sessions, and wrongly blocked **5 of 26,497 successful calls (0.02%)** (`demo/recordings/holdout-real.json`).

## Live: a real Claude Code session meets a scar
`demo/recordings/live-claude-code-block.txt` — an unedited `claude -p` run against the current guard, rendered from its stream-json events:

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
The agent did not fight the hook: it took the fix from the block message, the guard let that through, and the task finished (4 turns, 23 s). In its answer it explained the root cause on its own — `pgrep -f build.py` matches the shell running the loop.

## Use it on your own agent
```bash
cd your-project
scar scan  '~/.claude/projects/**/*.jsonl'          # what keeps going wrong? (GUARD vs advice)
scar heal  '~/.claude/projects/**/*.jsonl' --out .  # scars/*.md (review + commit) and .scar/rules.json
scar install                                        # dry run: prints the hook entries
scar install --yes                                  # adds the guard (PreToolUse) + brief (SessionStart) to .claude/settings.json
scar stats / holdout '<logs>'                       # aggregate numbers only
```
Other agents can feed it today: `--format events` takes a generic JSONL of `{ts, session, kind, tool, command, text}`, and `--format swe-agent` reads public SWE-agent trajectories. Enforcement is Claude Code hooks for now.

## How it decides
- **Root cause first.** If the error text names the cause, that is the signature, whatever the command was: `command not found: timeout` → `timeout:missing-command`; `(eval):1: == not found` → `=word:zsh-equals`; `no matches found: --include=*.md` → `--include=*:zsh-nomatch`. Otherwise: tool + command head + error class (timeout, permission, rejected, corrected…).
- **Silent failures count.** A call that exits 0 but printed a shell error (`echo ==; cat x`) is a failure, not normal work.
- **Rules come from evidence, not from the model.** Root-cause rules match the *shell view* of a command (quotes, heredoc bodies, comments, `[[ ]]` blanked), so `echo "=== ok ==="` or a Python heredoc with `a == b` never trip them. Head rules match command position plus the flags every example shares (`git push` passes, `git push --force` does not). An optional LLM (`--llm openai`) only rephrases the advice for head habits.
- **The guard never blocks the agent's own fix.** After a failure, the next successful call doing the same job is recorded as a *recovery*; its distinguishing shape (a bounded loop, a `perl alarm` wrapper, a `[b]racket` pattern, a new flag) becomes an exemption, and it is shown as "Worked before". A rule that would still block a recorded recovery is demoted.
- **Precision over coverage.** Every candidate is replayed against the agent's own successful history. It is demoted to advice if it would block normal work more than 3 times *and* more than once per 20 mistakes it stops, or more than 0.5% of all successful calls. Example: "any unquoted glob" stopped 870 failures but would have blocked 9,004 successes — demoted; `timeout` is missing in my main sessions but ran fine in 114 calls elsewhere (subagent runs) — demoted. Advice scars are injected at session start instead (`scar brief`).
- **Escape hatch.** If the agent is sure, it appends `# scar-ok: <reason>`; the guard lets it through once and logs it to `.scar/overrides.jsonl` for the human.

## Not just my machine
On 2,000 public SWE-agent trajectories ([nebius/SWE-agent-trajectories](https://huggingface.co/datasets/nebius/SWE-agent-trajectories), CC-BY-4.0; `demo/recordings/swe-agent-public.json`), the same pattern shows up in a different agent, model and shell: 321 failure signatures repeated ≥3 times. The model's `edit` introduced a syntax error 6,212 times in 968 of the 2,000 runs, it typed `cd..` without a space 979 times in 25 runs, and `ls.dvc` 1,214 times in 6 runs. The `--format swe-agent` adapter (40 lines) is all it took to read them. The habits are environment-specific there too (each trajectory runs in its own repo container), which is why Scar Tissue learns rules per machine/project instead of shipping a global blocklist.

## Limitations (honest)
- One user, one laptop. The thresholds (3, 1:20, 0.5%) were chosen on this data; the holdout is a time split on the same machine, not another person's.
- Enforcement is Claude Code only. The SWE-agent and generic-JSONL adapters scan; they do not block.
- Human corrections are detected with a short phrase list (English + Korean) right after a call — only 38 on my logs, so most scars come from errors.

## Tests
```bash
python3 -m unittest discover -s tests    # 32 tests: signatures, root causes, shell view, recoveries, fix-safety, cost-benefit demotion, silent failures, adapters, guard exit codes, escape hatch, `scar demo`
```
Standard library only (Python ≥ 3.9). The guard decides in milliseconds.

## Built during OFFGRID
Everything in this repo was written during the hackathon window (Oct 2026). I run a personal agent OS on Claude Code every day and had hand-written dozens of hooks, one incident at a time, after the agent repeated a mistake. While building this, my own agent hit `command not found: timeout` again. The incidents are already in the logs — the guardrails should write themselves. It reads standard Claude Code transcript files and does not include my private setup.

## Next
Codex and Cursor log adapters with enforcement, team mode (scars shared and reviewed through the repo), and scar decay (rules expire when the failure stops recurring).

MIT License

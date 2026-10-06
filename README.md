# Scar Tissue

**Your AI coding agent's repeated mistakes become guardrails.**

AI coding agents now run for hours on our own machines — and every session starts fresh. So they repeat the same mistakes: a `pgrep -f` wait loop that never ends because it matches itself, a `--force` push to `main` the human already said no to twice, a `curl | grep` "nothing found" on a page that is rendered by JavaScript.

Scar Tissue reads the agent's session logs, finds failures that **repeated** (≥3 times across ≥2 sessions, or ≥2 human corrections), writes each one down as a short **scar** (principle + dated evidence), and compiles it into a **Claude Code `PreToolUse` hook rule**. The next time the agent reaches for the same mistake, the guard blocks it *and tells the agent why* — so it picks the safer path on its own.

```
logs ──► scan (signatures, thresholds) ──► scars/*.md (human-readable, reviewable)
                                       └─► .scar/rules.json ──► guard.py (PreToolUse hook) ──► blocked + explained
```

## Why I built it
I run a personal agent OS on Claude Code every day. Over two months I hand-wrote dozens of hooks, one incident at a time, after the agent made the same mistake again. Scar Tissue is the tool I wanted: the incidents are already in the logs — the guardrails should write themselves.

Real numbers from my own machine — one frozen `scar stats` run (`demo/recordings/stats-real.json`, aggregate only; no transcript content leaves the machine):

| | |
|---|---|
| Claude Code sessions scanned | 85 |
| tool calls | 29,172 |
| failed tool calls | 1,810 |
| repeated failure signatures (≥3) | 87 |
| scars found | 91 |
| …already guarded by a hand-written hook | 29 |
| …automatic guard rules after precision filters | 1 |
| …demoted by self-validation (would have blocked normal work) | 2 |
| successful commands the final rules would block | **2 of 20,906 (0.01%)** |

That last row is the product decision: **a guard that blocks normal work is worse than no guard.** Every candidate rule is replayed against the agent's own *successful* history; if it would have blocked normal work more than 3 times (or 0.5%), it is demoted to advice. Non-zero exits alone (`grep` found nothing, `ls` missing path) are outcomes, not habits, so they never become blocks without a human correction or a timeout/permission/rejection. On my real logs that leaves very few automatic blocks — on purpose. The rest are surfaced as advice at session start (`scar brief`, installed as a `SessionStart` hook), and the hand-written guards I already had show where the precise blocks come from.

Before the precision filters, the same pipeline proposed 10 rules that would have blocked 896 of 18,922 successful Bash calls (4.7%) — that measurement is why the filters exist.

## Live: a real Claude Code session hitting a scar
`demo/recordings/live-claude-code-block.txt` (unedited `claude -p` run):

```
$ claude -p "Run exactly this bash command …: until ! pgrep -f build.py; do sleep 5; done" --allowedTools Bash

The command didn't run. A PreToolUse hook (`scar_tissue/guard.py`) blocked it before it started:
> [scar-tissue] blocked by scar bash-pgrep-f-timeout (4 failures, 0 corrections, 3 sessions):
> Avoid using pgrep -f loops that can run until timeout; instead, use bounded polling …
…
    for i in {1..60}; do pgrep -f '[b]uild\.py' >/dev/null || { echo "build.py done"; exit 0; }; sleep 5; done
```
The agent did not fight the hook — it explained the root cause (the loop matches its own command line) and proposed a bounded fix.

## Quick start
```bash
python3 -m scar_tissue scan  '~/.claude/projects/*/*.jsonl'      # what keeps going wrong?
python3 -m scar_tissue stats '~/.claude/projects/*/*.jsonl'      # aggregate counts only
python3 -m scar_tissue heal  '~/.claude/projects/*/*.jsonl' --out . [--llm openai]
python3 -m scar_tissue holdout '~/.claude/projects/*/*.jsonl'    # learn from early sessions, replay later ones
python3 -m scar_tissue brief '~/.claude/projects/*/*.jsonl'      # advice scars as session-start context
python3 -m scar_tissue install            # dry run: prints the hook entries
python3 -m scar_tissue install --yes      # adds the guard (PreToolUse) + brief (SessionStart) to .claude/settings.json
```
Any agent can feed it: besides Claude Code transcripts, `scan` accepts a generic JSONL of `{ts, session, kind, tool, command, text}` events (`demo/logs/events.jsonl`).

`--llm openai` asks an OpenAI model (default `gpt-5.4-mini`, `OPENAI_API_KEY`) to phrase each scar's principle as one imperative sentence; without a key a deterministic template is used. The **rule** (what gets blocked) never comes from the model — it is compiled deterministically from the evidence.

## Escape hatch
If the agent is sure a case is different, it can append `# scar-ok: <reason>` to the command. The guard lets it through once and logs the override to `.scar/overrides.jsonl` for the human to review.

## How it decides
- **Signature** = tool + command head (first meaningful tokens; quotes/paths/URLs/numbers stripped; `-sL` ≈ `-s`) + error class (timeout, permission, not-found, blocked, rejected, http, exit, corrected).
- **Scar** if ≥3 failures across ≥2 sessions, or ≥2 human corrections right after the call (`no,`, `stop`, `don't`, `아니,` …).
- **Rule** = command-position regex (`echo pgrep -f` is not a pgrep call) + flags shared by every example (`git push` stays allowed; `git push --force` is blocked).
- **Guard** = stdlib-only script; reads hook JSON on stdin; exit 2 + reason on stderr.

## Tests
```bash
python3 -m unittest discover -s tests     # 9 tests: parsing, thresholds, seeded demo, ≤1 false block on 30 safe commands, guard exit codes, escape hatch, self-validation demotion
```

## Built during OFFGRID
Everything in this repo was written during the hackathon window (Oct 2026). It does not include or depend on my private agent OS — it reads standard Claude Code transcript files. Built with Claude Code as a coding assistant; the scar phrasing optionally uses the OpenAI API.

## Next
Root-cause-aware principles (derive "pgrep -f matches its own command line" from the failing command + error), scar decay (rules expire if the failure stops recurring), Codex/Cursor log adapters, and a team mode where scars are shared through the repo.

MIT License

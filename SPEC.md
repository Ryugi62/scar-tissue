# Scar Tissue — SPEC

## Purpose
AI coding agents (Claude Code, Codex, …) run for hours on a developer's own machine and repeat the same mistakes across sessions: they wait forever on a `pgrep -f` loop, push to the wrong branch, conclude "not found" from a page they never read. Each session starts fresh, so the lesson is lost. **Scar Tissue turns repeated failures into guardrails**: it reads agent session logs, finds failures that happened ≥3 times (or were corrected by the human ≥2 times), writes a short *scar* (principle + evidence), and compiles it into a **PreToolUse hook rule** that blocks the same mistake next time — with the scar's explanation shown to the agent.

## Success criteria (numbers)
- `scar scan` on the bundled demo logs (3 sessions) finds exactly the 3 seeded repeated-failure patterns and 0 false scars from 1-off errors.
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

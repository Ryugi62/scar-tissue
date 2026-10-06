# Devpost submission — Scar Tissue

**Project name:** Scar Tissue

**Short description (1–2 sentences):** Scar Tissue reads your AI coding agent's session logs, finds the mistakes it keeps repeating, and turns each one into a Claude Code hook that blocks the mistake next time — and tells the agent why.

**Problem — what problem are you solving and who experiences it?**
Developers now let AI coding agents (Claude Code, Codex, Cursor) run for hours on their own machines. Every session starts fresh, so the agent repeats the same mistakes: a `pgrep -f` wait loop that never ends because it matches its own command line, a `--force` push to `main` that the human already rejected, a `curl | grep` "not found" on a page that only renders with JavaScript. The human ends up writing guardrails by hand, one incident at a time — or watching the same failure again. On my own machine: 85 Claude Code sessions, 29,172 tool calls, 1,810 failed calls, and 87 failure signatures that repeated three times or more.

**Solution — how does your project solve the problem?**
1. `scar scan` normalizes every tool call into a signature (tool + command head + error class) and finds repeats: ≥3 failures across ≥2 sessions, or ≥2 human corrections right after a call.
2. `scar heal` writes each scar as reviewable markdown (principle + dated evidence) and compiles a precise PreToolUse rule: command-position regex plus the flags every example shares (plain `git push` stays allowed; `git push --force` is blocked). An LLM can phrase the advice; the rule itself is compiled from evidence, never from the model.
3. `guard.py` (stdlib only) runs as a Claude Code hook: exit 2 + the scar's reason on stderr. In an unedited live `claude -p` run, the agent hit the scar, did not fight the hook, explained the root cause, and proposed a bounded loop instead.
4. Precision over coverage: every candidate rule is replayed against the agent's own successful history and demoted to advice if it would block normal work. Before this filter, 10 rules would have blocked 896 of 18,922 successful calls (4.7%); after it, the final rules block 2 of 20,906 (0.01%). Advice scars are injected at session start instead (`scar brief`). The agent can override once with `# scar-ok: <reason>`, logged for review.

**Demo link:** `demo/recordings/live-claude-code-block.txt` (unedited live run) + video below.

**Source code:** https://github.com/Ryugi62/scar-tissue  *(to be pushed at submission)*

**Demo video:** `demo/out/scar-tissue-demo.mp4` (99 s, real command outputs + voice-over)

**Tech stack:** Python 3 (stdlib only for the guard and scanner), Claude Code hooks (PreToolUse), Claude Code transcript JSONL, optional OpenAI API (`gpt-5.4-mini`) for phrasing scars, OpenAI TTS for the demo voice-over. Built with Claude Code as a coding assistant.

**Build process — what you built during OFFGRID and what you'd improve next:**
Everything in the repo was written during the hackathon: the signature normalizer, thresholds, rule compiler with shared-flag detection and command-position anchoring, the Claude Code transcript adapter, the stdlib guard, the CLI (`scan/heal/stats/install`), the demo log set, self-validation against history, a holdout evaluation, the escape hatch, 9 tests, and the live run. It reads standard Claude Code transcript files and does not include my private agent setup. Next: root-cause-aware principles, scars that expire when the failure stops recurring, Codex/Cursor log adapters, and team mode (scars shared through the repo).

**Why I want this to exist:** I run a personal agent OS on Claude Code every day and have hand-written dozens of hooks after the agent repeated a mistake. The incidents are already in the logs — the guardrails should write themselves.

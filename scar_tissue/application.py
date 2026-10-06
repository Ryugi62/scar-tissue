"""Use cases: scan (events → scars), heal (scars → markdown + rules), stats (aggregate counts only)."""
import json, os
from .domain import detect, compile_rule, template_principle, validate_against_history, rule_matches, describe, ROOT_CAUSE_CLASSES


def scan(events):
    scars = detect(events)
    validate_against_history(scars, events)
    return scars


def heal(scars, out_dir, phraser=None):
    os.makedirs(os.path.join(out_dir, "scars"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, ".scar"), exist_ok=True)
    rules = []
    for s in scars:
        base = template_principle(s)
        # the LLM may phrase head habits; root causes keep the exact cause template (the model blurs zsh vs bash)
        principle = phraser(s, base) if (phraser and s.actionable and s.error_class not in ROOT_CAUSE_CLASSES) else base
        rule = compile_rule(s, principle)
        if s.actionable:
            rules.append(rule)
        ev = "\n".join(f"- {e.ts or '?'} · session `{e.session[:8]}` · {e.kind} · `{(e.command or e.text)[:90]}`"
                       for e in (s.failures + s.corrections)[:12])
        md = (f"# Scar: {s.head} ({s.error_class})\n\n**Principle.** {principle}\n\n"
              f"**Signature.** `{s.signature}` — {len(s.failures)} failures, {len(s.corrections)} corrections, "
              f"{len(s.sessions)} sessions.\n\n" + (f"**Guard.** PreToolUse rule `{rule['id']}` blocks {s.tool} calls with {describe(rule)}.\n\n" if s.actionable else "**Advice only.** Too broad for an automatic block (already guarded, a whole tool, or a generic command) — review by hand.\n\n") +
              f"## Evidence\n{ev}\n")
        with open(os.path.join(out_dir, "scars", f"{s.slug}.md"), "w") as f:
            f.write(md)
    with open(os.path.join(out_dir, ".scar", "rules.json"), "w") as f:
        json.dump({"rules": rules}, f, indent=1, ensure_ascii=False)
    with open(os.path.join(out_dir, ".scar", "brief.md"), "w") as f:     # SessionStart reads this file — no rescan at startup
        f.write(brief_text(scars))
    return rules


BRIEF_CLASSES = ("missing-command", "zsh-equals", "zsh-nomatch", "timeout", "permission", "rejected", "http", "corrected")


def brief_text(scars, limit=10):
    """Advice scars (not blocked) as session-start context: the habit, how often, and the fix that worked — short lines only."""
    from .domain import fix_excerpt
    adv = [s for s in scars if not s.actionable and s.tool == "Bash" and s.error_class in BRIEF_CLASSES][:limit]
    lines = ["Lessons from this machine's past sessions (Scar Tissue) — repeated failures to avoid:"]
    for s in adv:
        fix = next((x for x in (fix_excerpt(s, r.command, 90) for r in reversed(s.recoveries)) if x), "")
        lines.append(f"- `{s.head}` ({s.error_class}): {len(s.failures)} failures / {len(s.corrections)} corrections across "
                     f"{len(s.sessions)} sessions" + (f"; worked before: `{fix}`" if fix else ""))
    return "\n".join(lines) + "\n"


def _bash_outcomes(events, corrected=frozenset()):
    """(failed Bash calls incl. silent part-failures, normal successful Bash calls) — the denominators every number uses."""
    from .domain import silent_root_cause
    fails = [e for e in events if e.tool == "Bash" and e.command and
             (e.kind == "tool_error" or (e.kind == "tool_ok" and silent_root_cause(e.text, e.command)))]
    oks = [e for e in events if e.tool == "Bash" and e.kind == "tool_ok" and e.command and not silent_root_cause(e.text, e.command)
           and id(e) not in corrected]
    return fails, oks


def _secs(a, b):
    from datetime import datetime
    try:
        f = lambda t: datetime.fromisoformat(t.replace("Z", "+00:00"))
        return (f(b) - f(a)).total_seconds()
    except (ValueError, AttributeError):
        return None


def failure_cost(events, rules, window=6):
    """Per rule, what its matched failures cost in history: how many were followed by a call that no longer trips the rule
    (the fix), how many calls and seconds that took, and how many silent part-failures were never fixed (the agent moved
    on, e.g. with an empty search result)."""
    from statistics import median
    from .domain import silent_root_cause
    by_session = {}
    for e in events:
        if e.tool == "Bash" and e.command and e.kind in ("tool_ok", "tool_error"):
            by_session.setdefault(e.session, []).append(e)
    out = {}
    for r in rules:
        calls, secs, matched, rec, never = [], [], 0, 0, 0
        for seq in by_session.values():
            for i, e in enumerate(seq):
                failed = e.kind == "tool_error" or silent_root_cause(e.text, e.command)
                if not failed or not rule_matches(r, "Bash", {"command": e.command}):
                    continue
                matched += 1
                fix = next((j for j in range(i + 1, min(len(seq), i + 1 + window))
                            if seq[j].kind == "tool_ok" and not silent_root_cause(seq[j].text, seq[j].command)
                            and not rule_matches(r, "Bash", {"command": seq[j].command})
                            and _related(e.command, seq[j].command)), None)
                if fix is None:
                    never += e.kind == "tool_ok"
                    continue
                rec += 1; calls.append(fix - i)
                s = _secs(e.ts, seq[fix].ts)
                if s is not None:
                    secs.append(s)
        out[r["id"]] = {"matched": matched, "recovered": rec, "median_calls_to_fix": median(calls) if calls else None,
                        "median_seconds_to_fix": round(median(secs)) if secs else None, "silent_never_fixed": never}
    return out


def _related(a, b):
    """The later call redoes the same job: it shares ≥50% of the failing call's words (≥3 letters)."""
    import re as _re
    wa = {w for w in _re.findall(r"[A-Za-z_][\w.-]{2,}", a)}
    wb = {w for w in _re.findall(r"[A-Za-z_][\w.-]{2,}", b)}
    return bool(wa) and len(wa & wb) / len(wa) >= 0.5


def holdout(events, train_frac=0.7):
    """Learn scars from the earliest sessions, replay the rest (Bash calls only — what a Bash rule can block)."""
    first_ts = {}
    for e in events:
        if e.ts and (e.session not in first_ts or e.ts < first_ts[e.session]):
            first_ts[e.session] = e.ts
    order = sorted(first_ts, key=first_ts.get)
    cut = int(len(order) * train_frac)
    train_s, test_s = set(order[:cut]), set(order[cut:])
    train = [e for e in events if e.session in train_s]
    test = [e for e in events if e.session in test_s]
    rules = [compile_rule(s, "") for s in scan(train) if s.actionable]
    fails, oks = _bash_outcomes(test)
    hit = lambda e: any(rule_matches(r, e.tool, {"command": e.command}) for r in rules)
    return {"sessions_with_timestamped_events": len(order), "train_sessions": len(train_s), "test_sessions": len(test_s),
            "guard_rules": len(rules),
            "rule_ids": [r["id"] for r in rules],
            "test_failures": len(fails), "test_failures_blocked": sum(1 for e in fails if hit(e)),
            "test_successes": len(oks), "test_successes_blocked": sum(1 for e in oks if hit(e))}


def stats(events, n_sessions):
    """Aggregate counts only — signatures and counts, never the transcripts' content."""
    from collections import Counter
    from .domain import signature, silent_root_cause
    kinds = Counter(e.kind for e in events)
    sigs = Counter("%s:%s:%s" % signature(e) for e in events if e.kind in ("tool_error", "hook_block"))
    sc = scan(events)
    guards = [x for x in sc if x.actionable]
    corrected = frozenset(id(c) for x in sc for c in x.corrected_calls)
    fails, oks = _bash_outcomes(events, corrected)
    per_rule = []
    for g in guards:
        r = compile_rule(g, "")
        mf = [e for e in fails if rule_matches(r, e.tool, {"command": e.command})]
        per_rule.append({"id": r["id"], "signature": g.signature, "sessions": len(g.sessions),
                         "matched_failures": len(mf), "matched_exit_nonzero": sum(1 for e in mf if e.kind == "tool_error"),
                         "matched_silent": sum(1 for e in mf if e.kind == "tool_ok"),
                         "successes_blocked": sum(1 for e in oks if rule_matches(r, e.tool, {"command": e.command})),
                         "recoveries": len(g.recoveries)})
    rules = [compile_rule(g, "") for g in guards]
    hit = lambda e: any(rule_matches(r, e.tool, {"command": e.command}) for r in rules)
    matched = [e for e in fails if hit(e)]
    overlap = sum(1 for e in matched if sum(rule_matches(r, e.tool, {"command": e.command}) for r in rules) > 1)
    return {"sessions": n_sessions, "tool_calls": kinds["tool_ok"] + kinds["tool_error"] + kinds["hook_block"],
            "failures": kinds["tool_error"] + kinds["hook_block"], "corrections": kinds["user_correction"],
            "silent_failures": sum(1 for e in events if e.kind == "tool_ok" and silent_root_cause(e.text, e.command)),
            "signatures": len(sigs), "signatures_repeated_3plus": sum(1 for v in sigs.values() if v >= 3),
            "scars": len(sc), "root_cause_scars": sum(1 for x in sc if x.error_class in ROOT_CAUSE_CLASSES),
            "guard_rules": len(guards), "demoted_by_self_validation": sum(1 for x in sc if getattr(x, "demoted", False)),
            "already_guarded": sum(1 for x in sc if x.error_class == "blocked"),
            "recoveries_learned": sum(len(x.recoveries) for x in guards),
            "bash_failures": len(fails), "bash_failures_exit_nonzero": sum(1 for e in fails if e.kind == "tool_error"),
            "bash_failures_matched_by_rules": len(matched), "bash_failures_matched_by_2plus_rules": overlap,
            "bash_failures_matched_exit_nonzero": sum(1 for e in matched if e.kind == "tool_error"),
            "bash_successes": len(oks), "bash_successes_blocked": sum(1 for e in oks if hit(e)),
            "rules": per_rule, "failure_cost": failure_cost(events, rules),
            "demoted": [{"signature": x.signature, "failures": len(x.failures), "sessions": len(x.sessions),
                         "would_block_successes": getattr(x, "false_blocks", None), "blocks_own_fix": getattr(x, "blocks_own_fix", 0)}
                        for x in sc if getattr(x, "demoted", False)],
            "top_scars": [{"signature": x.signature, "failures": len(x.failures), "corrections": len(x.corrections),
                           "sessions": len(x.sessions), "guard": x.actionable} for x in sc[:10]]}


def report(events, n_sessions):
    """`scar report`: a read-only markdown page — what keeps going wrong, what it costs, what worked, what to change."""
    from .domain import ENV_FIX, fix_excerpt
    st = stats(events, n_sessions)
    sc = scan(events)
    pct = lambda a, b: (f"{100 * a / b:.1f}%" if 100 * a / b >= 1 else f"{100 * a / b:.2f}%") if b else "-"
    esc = lambda t: t.replace("|", "\\|")
    L = ["# What your agent keeps getting wrong", "",
         f"{st['sessions']:,} sessions · {st['tool_calls']:,} tool calls · {st['failures']:,} failed · "
         f"{st['silent_failures']:,} silent failures (exit 0, but the shell printed an error)", "",
         "| scar | failures | corrections | sessions | status | Worked before |", "|---|---|---|---|---|---|"]
    for x in [x for x in sc if x.error_class != "blocked"][:15]:
        fix = next((f for f in (fix_excerpt(x, r.command, 70) for r in reversed(x.recoveries)) if f), "")
        status = "GUARD" if x.actionable else ("demoted" if getattr(x, "demoted", False) else "advice")
        L.append(f"| `{esc(x.signature)}` | {len(x.failures)} | {len(x.corrections)} | {len(x.sessions)} | {status} | "
                 + (f"`{esc(fix)}`" if fix else "") + " |")
    L += ["", f"**The guard rules** would match {st['bash_failures_matched_by_rules']:,} of {st['bash_failures']:,} failed shell commands "
          f"({pct(st['bash_failures_matched_by_rules'], st['bash_failures'])}) and block {st['bash_successes_blocked']} of "
          f"{st['bash_successes']:,} successful ones ({pct(st['bash_successes_blocked'], st['bash_successes'])})."]
    fixes = sorted({ENV_FIX[x.error_class].format(head=x.head) for x in sc if x.error_class in ENV_FIX})
    if fixes:
        L += ["", "## One-line environment fixes (for you, the human)"] + [f"- {f}" for f in fixes]
    L += ["", "## Next", "```", "scar heal '<logs>' --out .     # scars/*.md to review + .scar/rules.json",
          "scar install --yes              # PreToolUse guard + SessionStart brief in .claude/settings.json", "```"]
    return "\n".join(L) + "\n"


def stats_table(st):
    pct = lambda a, b: f"{100 * a / b:.1f}%" if b and 100 * a / b >= 1 else (f"{100 * a / b:.2f}%" if b else "-")
    rows = [("sessions (subagents folded into their parent)", f"{st['sessions']:,}"), ("tool calls", f"{st['tool_calls']:,}"),
            ("failed tool calls", f"{st['failures']:,}"), ("silent failures (exit 0, shell error)", f"{st['silent_failures']:,}"),
            ("scars", f"{st['scars']}"), ("automatic guard rules", f"{st['guard_rules']}"),
            ("demoted by self-validation", f"{st['demoted_by_self_validation']}"), ("", ""),
            ("failed shell commands the rules match", f"{st['bash_failures_matched_by_rules']:,} of {st['bash_failures']:,}  ({pct(st['bash_failures_matched_by_rules'], st['bash_failures'])})"),
            ("successful commands they would block", f"{st['bash_successes_blocked']} of {st['bash_successes']:,}  ({pct(st['bash_successes_blocked'], st['bash_successes'])})")]
    return "\n".join(f"{a:46s} {b}" if a else "" for a, b in rows) + "\n"

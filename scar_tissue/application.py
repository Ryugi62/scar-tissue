"""Use cases: scan (events → scars), heal (scars → markdown + rules), stats (aggregate counts only)."""
import json, os
from .domain import detect, compile_rule, template_principle, validate_against_history, rule_matches


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
        principle = phraser(s, base) if (phraser and s.actionable) else base
        rule = compile_rule(s, principle)
        if s.actionable:
            rules.append(rule)
        ev = "\n".join(f"- {e.ts or '?'} · session `{e.session[:8]}` · {e.kind} · `{(e.command or e.text)[:90]}`"
                       for e in (s.failures + s.corrections)[:12])
        md = (f"# Scar: {s.head} ({s.error_class})\n\n**Principle.** {principle}\n\n"
              f"**Signature.** `{s.signature}` — {len(s.failures)} failures, {len(s.corrections)} corrections, "
              f"{len(s.sessions)} sessions.\n\n" + (f"**Guard.** PreToolUse rule `{rule['id']}` blocks `{s.tool}` calls matching `{rule['pattern']}`.\n\n" if s.actionable else "**Advice only.** Too broad for an automatic block (already guarded, a whole tool, or a generic command) — review by hand.\n\n") +
              f"## Evidence\n{ev}\n")
        with open(os.path.join(out_dir, "scars", f"{s.slug}.md"), "w") as f:
            f.write(md)
    with open(os.path.join(out_dir, ".scar", "rules.json"), "w") as f:
        json.dump({"rules": rules}, f, indent=1, ensure_ascii=False)
    return rules


def holdout(events, train_frac=0.7):
    """Learn scars from the earliest sessions, replay the rest: failures that would have been blocked vs successful calls wrongly blocked."""
    first_ts = {}
    for e in events:
        if e.ts and (e.session not in first_ts or e.ts < first_ts[e.session]):
            first_ts[e.session] = e.ts
    order = sorted(first_ts, key=first_ts.get)
    cut = int(len(order) * train_frac)
    train_s, test_s = set(order[:cut]), set(order[cut:])
    train = [e for e in events if e.session in train_s]
    test = [e for e in events if e.session in test_s]
    scars = scan(train)
    rules = [compile_rule(s, "") for s in scars if s.actionable]
    fails = [e for e in test if e.kind in ("tool_error",) and e.command]
    oks = [e for e in test if e.kind == "tool_ok" and e.command]
    hit = lambda e: any(rule_matches(r, e.tool, {"command": e.command}) for r in rules)
    return {"train_sessions": len(train_s), "test_sessions": len(test_s), "guard_rules": len(rules),
            "test_failures": len(fails), "test_failures_blocked": sum(1 for e in fails if hit(e)),
            "test_successes": len(oks), "test_successes_blocked": sum(1 for e in oks if hit(e))}


def stats(events, n_sessions):
    from collections import Counter
    from .domain import signature
    kinds = Counter(e.kind for e in events)
    sigs = Counter("%s:%s:%s" % signature(e) for e in events if e.kind in ("tool_error", "hook_block"))
    return {"sessions": n_sessions, "tool_calls": kinds["tool_ok"] + kinds["tool_error"] + kinds["hook_block"],
            "failures": kinds["tool_error"] + kinds["hook_block"], "corrections": kinds["user_correction"],
            "signatures": len(sigs), "signatures_repeated_3plus": sum(1 for v in sigs.values() if v >= 3),
            "scars": len(sc := scan(events)), "guard_rules": sum(1 for x in sc if x.actionable),
            "demoted_by_self_validation": sum(1 for x in sc if getattr(x, "demoted", False)),
            "already_guarded": sum(1 for x in sc if x.error_class == "blocked")}

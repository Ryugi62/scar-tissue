"""Use cases: scan (events → scars), heal (scars → markdown + rules), stats (aggregate counts only)."""
import json, os
from .domain import detect, compile_rule, template_principle


def scan(events):
    return detect(events)


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


def stats(events, n_sessions):
    from collections import Counter
    from .domain import signature
    kinds = Counter(e.kind for e in events)
    sigs = Counter("%s:%s:%s" % signature(e) for e in events if e.kind in ("tool_error", "hook_block"))
    return {"sessions": n_sessions, "tool_calls": kinds["tool_ok"] + kinds["tool_error"] + kinds["hook_block"],
            "failures": kinds["tool_error"] + kinds["hook_block"], "corrections": kinds["user_correction"],
            "signatures": len(sigs), "signatures_repeated_3plus": sum(1 for v in sigs.values() if v >= 3),
            "scars": len(detect(events)), "guard_rules": sum(1 for x in detect(events) if x.actionable),
            "already_guarded": sum(1 for x in detect(events) if x.error_class == "blocked")}

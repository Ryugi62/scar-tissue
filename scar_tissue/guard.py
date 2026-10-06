#!/usr/bin/env python3
"""Scar Tissue guard — Claude Code PreToolUse hook. stdin = hook JSON. Exit 2 + stderr message = block. stdlib only.
Rules file: $SCAR_RULES or ./.scar/rules.json. Matching (shell view, `bash -c` unwrapping, learned exemptions) is the
same pure function the rules were validated with: scar_tissue.domain.rule_matches."""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scar_tissue.domain import rule_matches  # noqa: E402  (pure, stdlib only)


def main():
    try:
        hook = json.load(sys.stdin)
    except ValueError:
        return 0
    path = os.environ.get("SCAR_RULES") or os.path.join(hook.get("cwd") or os.getcwd(), ".scar", "rules.json")
    try:
        with open(path) as f:
            rules = json.load(f)["rules"]
    except (OSError, ValueError, KeyError):
        return 0
    tool, inp = hook.get("tool_name", ""), hook.get("tool_input") or {}
    text = inp.get("command") or inp.get("url") or inp.get("file_path") or ""
    m = re.search(r"#\s*scar-ok:\s*(\S.{4,})$", text.strip())
    if m:   # escape hatch: the agent may proceed once if it states a reason; every override is logged for review
        try:
            with open(os.path.join(os.path.dirname(path), "overrides.jsonl"), "a") as f:
                f.write(json.dumps({"tool": tool, "command": text[:300], "reason": m.group(1)[:200]}) + "\n")
        except OSError:
            pass
        return 0
    for r in rules:
        if rule_matches(r, tool, inp):
            ev = r.get("evidence", {})
            sys.stderr.write(f"[scar-tissue] blocked by scar `{r['id']}` ({ev.get('failures', 0)} failures, "
                             f"{ev.get('corrections', 0)} corrections, {ev.get('sessions', 0)} sessions): {r['message']} "
                             "(If you are sure this case is different, append `# scar-ok: <reason>` to the command.)\n")
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

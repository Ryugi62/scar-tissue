#!/usr/bin/env python3
"""Scar Tissue guard — Claude Code PreToolUse hook. stdin = hook JSON. Exit 2 + stderr message = block. stdlib only.
Rules file: $SCAR_RULES or ./.scar/rules.json. Matching (shell tokenizer, `bash -c` payloads, learned exemptions) is the
same pure function the rules were validated with: scar_tissue.domain.rule_matches."""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scar_tissue.domain import rule_matches  # noqa: E402  (pure, stdlib only)

OVERRIDE_BUDGET = 3


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
    hit = next((r for r in rules if rule_matches(r, tool, inp)), None)
    if hit is None:
        return 0
    text = inp.get("command") or ""
    m = re.search(r"#\s*scar-ok:\s*(\S.{4,})$", text.strip())
    log = os.path.join(os.path.dirname(path), "overrides.jsonl")
    if m:   # escape hatch: the agent states a reason; logged per rule, at most OVERRIDE_BUDGET times until a human reviews
        try:
            with open(log) as f:
                used = sum(1 for line in f if json.loads(line).get("rule") == hit["id"])
        except (OSError, ValueError):
            used = 0
        if used < OVERRIDE_BUDGET:
            try:
                with open(log, "a") as f:
                    f.write(json.dumps({"rule": hit["id"], "command": text[:300], "reason": m.group(1)[:200]}) + "\n")
            except OSError:
                pass
            return 0
        sys.stderr.write(f"[scar-tissue] override budget for scar `{hit['id']}` is used up ({used} overrides in "
                         f"{log}) — ask the human to review the scar before overriding again.\n")
        return 2
    ev = hit.get("evidence", {})
    sys.stderr.write(f"[scar-tissue] blocked by scar `{hit['id']}` ({ev.get('failures', 0)} failures, "
                     f"{ev.get('corrections', 0)} corrections, {ev.get('sessions', 0)} sessions): {hit['message']} "
                     "(If you are sure this case is different, append `# scar-ok: <reason>` to the command; overrides are logged.)\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Scar Tissue guard — Claude Code PreToolUse hook. stdin = hook JSON. Exit 2 + stderr message = block. stdlib only.
Rules file: $SCAR_RULES or ./.scar/rules.json"""
import json, os, re, sys


def main():
    try:
        hook = json.load(sys.stdin)
    except ValueError:
        return 0
    path = os.environ.get("SCAR_RULES") or os.path.join(hook.get("cwd") or os.getcwd(), ".scar", "rules.json")
    try:
        rules = json.load(open(path))["rules"]
    except (OSError, ValueError, KeyError):
        return 0
    tool, inp = hook.get("tool_name", ""), hook.get("tool_input") or {}
    text = inp.get("command") or inp.get("url") or inp.get("file_path") or ""
    for r in rules:
        if r.get("tool") == tool and re.search(r["pattern"], text):
            ev = r.get("evidence", {})
            sys.stderr.write(f"[scar-tissue] blocked by scar `{r['id']}` ({ev.get('failures', 0)} failures, "
                             f"{ev.get('corrections', 0)} corrections, {ev.get('sessions', 0)} sessions): {r['message']}\n")
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

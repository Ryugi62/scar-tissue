#!/usr/bin/env python3
"""Scar Tissue guard — Claude Code PreToolUse hook. stdin = hook JSON. Exit 2 + stderr message = block. stdlib only.
Rules file: $SCAR_RULES or ./.scar/rules.json. Matching (shell tokenizer, `bash -c` payloads, learned exemptions) is the
same pure function the rules were validated with: scar_tissue.domain.rule_matches."""
import hashlib, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scar_tissue.domain import rule_matches, silent_root_cause, SHELL_ERR  # noqa: E402  (pure, stdlib only)

OVERRIDE_BUDGET = 3


CAUSE = {"zsh-nomatch": "zsh aborted the command because an unquoted glob matched nothing",
         "zsh-equals": "zsh tried to run a command named `=` (an unquoted `==`/`===` word)",
         "missing-command": "a command in it is not installed here"}


def silent_alarm(hook):
    """PostToolUse: the call 'succeeded' (exit 0) but the shell printed an error that this command itself confirms
    (the unquoted glob, the `==` word, the missing command is really in it) — tell the agent, once per command per session."""
    resp = hook.get("tool_response") or {}
    text = "\n".join(str(resp.get(k) or "") for k in ("stdout", "stderr", "output")) if isinstance(resp, dict) else str(resp)
    cmd = (hook.get("tool_input") or {}).get("command") or ""
    rc = silent_root_cause(text, cmd) if hook.get("tool_name") == "Bash" else None
    if not rc:
        return 0
    line = next(l for l in SHELL_ERR.findall(text) if silent_root_cause(l, cmd))[:160]
    key = hashlib.sha1(f"{hook.get('session_id', '')}\0{cmd}".encode()).hexdigest()[:16]
    log = os.path.join(hook.get("cwd") or os.getcwd(), ".scar", "alarms.jsonl")
    try:
        with open(log) as f:
            if any(json.loads(l).get("key") == key for l in f):
                return 0                                  # already said for this command in this session
    except (OSError, ValueError):
        pass
    try:
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a") as f:
            f.write(json.dumps({"key": key, "cause": rc[0], "line": line}) + "\n")
    except OSError:
        pass
    sys.stderr.write(f"[scar-tissue] This command exited 0, but the shell printed `{line}` — that part did not run "
                     f"({CAUSE.get(rc[0], rc[0])}). Do not read the empty or partial output as a result; fix it and run it again.\n")
    return 2


def main():
    try:
        hook = json.load(sys.stdin)
    except ValueError:
        return 0
    if hook.get("hook_event_name") == "PostToolUse":
        return silent_alarm(hook)
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
    human_no = hit.get("evidence", {}).get("corrections", 0) and not hit.get("evidence", {}).get("failures", 0)
    if m and human_no:   # a human said no to this — only a human can lift it
        sys.stderr.write(f"[scar-tissue] blocked by scar `{hit['id']}`: a human said no to this before ({hit['message']}). "
                         "The agent cannot override it — ask the human.\n")
        return 2
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

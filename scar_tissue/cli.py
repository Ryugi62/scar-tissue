"""scar — CLI.  scar scan <logs> | scar heal <logs> [--out DIR] [--llm openai] | scar stats <logs> | scar install [--yes]
<logs> = a generic events .jsonl file, or a glob of Claude Code transcripts (e.g. '~/.claude/projects/*/*.jsonl')."""
import argparse, json, os, sys
from . import application
from .adapters import claude_code, jsonl


def load(src):
    if src.endswith(".jsonl") and os.path.isfile(os.path.expanduser(src)) and "/.claude/" not in os.path.expanduser(src):
        ev = jsonl.read(os.path.expanduser(src)); return ev, len({e.session for e in ev})
    return claude_code.read_dir(src)


def main(argv=None):
    a = argparse.ArgumentParser(prog="scar"); sub = a.add_subparsers(dest="cmd", required=True)
    for name in ("scan", "heal", "stats"):
        p = sub.add_parser(name); p.add_argument("logs")
        if name == "heal":
            p.add_argument("--out", default="."); p.add_argument("--llm", choices=["openai"], default=None)
    p = sub.add_parser("install"); p.add_argument("--settings", default=".claude/settings.json"); p.add_argument("--yes", action="store_true")
    o = a.parse_args(argv)
    if o.cmd == "install":
        guard = os.path.abspath(os.path.join(os.path.dirname(__file__), "guard.py"))
        entry = {"matcher": "Bash", "hooks": [{"type": "command", "command": f"python3 {guard}"}]}
        if not o.yes:
            print("would add PreToolUse hook to", o.settings, json.dumps(entry)); return 0
        s = json.load(open(o.settings)) if os.path.exists(o.settings) else {}
        pre = s.setdefault("hooks", {}).setdefault("PreToolUse", [])
        if not any(guard in json.dumps(x) for x in pre):
            pre.append(entry)
        os.makedirs(os.path.dirname(o.settings) or ".", exist_ok=True); json.dump(s, open(o.settings, "w"), indent=2)
        print("installed guard in", o.settings); return 0
    events, n = load(o.logs)
    if o.cmd == "stats":
        print(json.dumps(application.stats(events, n), indent=1)); return 0
    scars = application.scan(events)
    if o.cmd == "scan":
        print(f"{n} sessions · {len(events)} events · {len(scars)} scars")
        for s in scars:
            tag = "GUARD " if s.actionable else "advice"
            print(f"  ✱ [{tag}] {s.signature[:60]:60s} failures={len(s.failures)} corrections={len(s.corrections)} sessions={len(s.sessions)}")
        return 0
    phraser = None
    if o.llm == "openai":
        from .adapters.openai_phrase import phrase; phraser = phrase
    rules = application.heal(scars, o.out, phraser)
    for r in rules:
        print(f"  ✚ rule {r['id']}: {r['message']}")
    print(f"wrote {len(rules)} scars → {os.path.join(o.out, 'scars')}/ and rules → {os.path.join(o.out, '.scar/rules.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

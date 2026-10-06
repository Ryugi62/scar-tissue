"""scar — CLI.  scar demo | scar scan <logs> | scar heal <logs> [--out DIR] [--llm openai] | scar stats <logs> | scar install [--yes]
<logs> = a generic events .jsonl file, or a glob of Claude Code transcripts (e.g. '~/.claude/projects/*/*.jsonl')."""
import argparse, json, os, subprocess, sys, tempfile
from . import application
from .adapters import claude_code, jsonl


def load(src, fmt="auto"):
    if fmt == "swe-agent":
        from .adapters import swe_agent
        return swe_agent.read(os.path.expanduser(src))
    if fmt == "events" or src.endswith(".jsonl") and os.path.isfile(os.path.expanduser(src)) and "/.claude/" not in os.path.expanduser(src):
        ev = jsonl.read(os.path.expanduser(src)); return ev, len({e.session for e in ev})
    return claude_code.read_dir(src)


HERE = os.path.dirname(os.path.abspath(__file__))
DEMO_LOGS = os.path.join(HERE, "demo_events.jsonl")
DEMO_CALLS = [   # (command an agent might send next, note)
    ("until ! pgrep -f build.py; do sleep 5; done", "the habit that timed out 4×"),
    ("for i in $(seq 1 60); do pgrep -f '[b]uild.py' >/dev/null || break; sleep 5; done", "the agent's own fix, learned from the logs"),
    ("echo === Tests passed ===", "zsh expands `===`"),
    ('echo "=== Tests passed ==="', "quoted"),
    ("timeout 120 pytest -q", "no GNU timeout on this machine"),
    ("git push --force origin main", "the human said no, twice"),
    ("git push origin feature-x", "normal work"),
    ("ls -la && npm test", "normal work"),
]


def demo():
    """scan → heal → the real guard script, on the bundled synthetic logs, in a temp dir. No network, no config changes."""
    events = jsonl.read(DEMO_LOGS)
    scars = application.scan(events)
    print(f"Scar Tissue demo — bundled synthetic logs: {len({e.session for e in events})} sessions, {len(events)} events\n")
    print(f"1) scan → {len(scars)} scars")
    for s in scars:
        print(f"   ✱ [{'GUARD ' if s.actionable else 'advice'}] {s.signature:34s} failures={len(s.failures)} "
              f"corrections={len(s.corrections)} sessions={len(s.sessions)} recoveries={len(s.recoveries)}")
    d = tempfile.mkdtemp(prefix="scar-demo-")
    rules = application.heal(scars, d)
    print(f"\n2) heal → {len(scars)} scars/*.md + {len(rules)} rules in {d}/.scar/rules.json\n")
    print("3) guard (the real PreToolUse hook script) on the agent's next calls:")
    for cmd, note in DEMO_CALLS:
        hook = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": d}
        r = subprocess.run([sys.executable, os.path.join(HERE, "guard.py")], input=json.dumps(hook), capture_output=True, text=True)
        print(f"   {'BLOCKED' if r.returncode == 2 else 'allowed'}  {cmd}   # {note}")
        if r.returncode == 2:
            print("            ↳ " + r.stderr.strip().split(": ", 1)[-1][:230])
    return 0


def main(argv=None):
    a = argparse.ArgumentParser(prog="scar"); sub = a.add_subparsers(dest="cmd", required=True)
    for name in ("scan", "heal", "stats", "holdout", "brief", "report"):
        p = sub.add_parser(name); p.add_argument("logs")
        p.add_argument("--format", choices=["auto", "claude-code", "events", "swe-agent"], default="auto",
                       help="auto: a .jsonl file = generic events, a glob = Claude Code transcripts")
        if name == "stats":
            p.add_argument("--table", action="store_true", help="human-readable summary instead of JSON")
        if name == "heal":
            p.add_argument("--out", default="."); p.add_argument("--llm", choices=["openai"], default=None)
    p = sub.add_parser("install"); p.add_argument("--settings", default=".claude/settings.json"); p.add_argument("--yes", action="store_true")
    sub.add_parser("demo")
    o = a.parse_args(argv)
    if o.cmd == "demo":
        return demo()
    if o.cmd == "install":
        guard = os.path.abspath(os.path.join(os.path.dirname(__file__), "guard.py"))
        entry = {"matcher": "Bash", "hooks": [{"type": "command", "command": f"python3 {guard}"}]}
        brief = {"hooks": [{"type": "command", "command": "cat .scar/brief.md 2>/dev/null || true"}]}   # written by `scar heal`
        if not o.yes:
            print("would add to", o.settings, "\n  PreToolUse + PostToolUse:", json.dumps(entry), "\n  SessionStart:", json.dumps(brief)); return 0
        s = json.load(open(o.settings)) if os.path.exists(o.settings) else {}
        pre = s.setdefault("hooks", {}).setdefault("PreToolUse", [])
        if not any(guard in json.dumps(x) for x in pre):
            pre.append(entry)
        post = s["hooks"].setdefault("PostToolUse", [])   # silent-failure alarm: same script, PostToolUse event
        if not any(guard in json.dumps(x) for x in post):
            post.append(entry)
        ss = s["hooks"].setdefault("SessionStart", [])
        if not any(".scar/brief.md" in json.dumps(x) for x in ss):
            ss.append(brief)
        os.makedirs(os.path.dirname(o.settings) or ".", exist_ok=True); json.dump(s, open(o.settings, "w"), indent=2)
        print("installed guard in", o.settings); return 0
    events, n = load(o.logs, o.format) if o.format != "claude-code" else claude_code.read_dir(o.logs)
    if o.cmd == "brief":   # advice scars as session-start context (the SessionStart hook reads .scar/brief.md instead)
        print(application.brief_text(application.scan(events)), end=""); return 0
    if o.cmd == "holdout":
        print(json.dumps(application.holdout(events), indent=1)); return 0
    if o.cmd == "stats":
        st = application.stats(events, n)
        print(application.stats_table(st) if o.table else json.dumps(st, indent=1), end="" if o.table else "\n"); return 0
    if o.cmd == "report":
        print(application.report(events, n), end=""); return 0
    scars = application.scan(events)
    if o.cmd == "scan":
        print(f"{n} sessions · {len(events)} events · {len(scars)} scars")
        for s in scars:
            tag = "GUARD " if s.actionable else "advice"
            print(f"  ✱ [{tag}] {s.signature[:60]:60s} failures={len(s.failures)} corrections={len(s.corrections)} sessions={len(s.sessions)} recoveries={len(s.recoveries)}")
        return 0
    phraser = None
    if o.llm == "openai":
        from .adapters.openai_phrase import phrase; phraser = phrase
    rules = application.heal(scars, o.out, phraser)
    for r in rules:
        print(f"  ✚ rule {r['id']}: {r['message']}")
    print(f"wrote {len(scars)} scars → {os.path.join(o.out, 'scars')}/ and {len(rules)} guard rules → {os.path.join(o.out, '.scar/rules.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

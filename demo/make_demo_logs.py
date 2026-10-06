"""Synthetic demo logs (generic event JSONL) — 3 sessions with 3 seeded repeated failures + noise. No real user data."""
import json, os
OUT = os.path.join(os.path.dirname(__file__), "logs", "events.jsonl")
ev = []
def add(ts, s, kind, tool="Bash", command="", text=""):
    ev.append({"ts": ts, "session": s, "kind": kind, "tool": tool, "command": command, "text": text})
# Pattern 1: pgrep -f in a wait loop never exits (the loop matches itself) → timeout, 4× in 3 sessions
add("2026-10-01T09:00", "s1", "tool_error", command="until ! pgrep -f build.py; do sleep 5; done", text="Command timed out after 600000ms")
add("2026-10-02T13:10", "s2", "tool_error", command="while pgrep -f 'node server'; do sleep 2; done", text="Command timed out after 120000ms")
add("2026-10-03T22:40", "s3", "tool_error", command="pgrep -f render && sleep 30", text="Command timed out after 600000ms")
add("2026-10-03T22:55", "s3", "tool_error", command="until ! pgrep -f render.py; do sleep 10; done", text="timeout")
# Pattern 2: git push --force corrected by the human twice
add("2026-10-01T10:00", "s1", "tool_ok", command="git push --force origin main", text="+ 1a2b3c...4d5e6f main -> main (forced update)")
add("2026-10-01T10:01", "s1", "user_correction", tool="human", text="no, never force-push main")
add("2026-10-02T15:00", "s2", "tool_ok", command="git push --force", text="forced update")
add("2026-10-02T15:02", "s2", "user_correction", tool="human", text="stop force pushing, I told you yesterday")
# Pattern 3: curl to a JS-only page → 'not found' conclusion, 3× across 2 sessions
add("2026-10-02T11:00", "s2", "tool_error", command="curl -s https://example-hackathon.dev/rules | grep prize", text="exit code 1")
add("2026-10-03T09:30", "s3", "tool_error", command="curl -s https://another-contest.app/ | grep deadline", text="exit code 1")
add("2026-10-03T09:35", "s3", "tool_error", command="curl -sL https://spa.example.org/terms | grep -i eligib", text="exit code 1")
# Noise: one-off failures that must NOT become scars
add("2026-10-01T11:00", "s1", "tool_error", command="npm test", text="exit code 1")
add("2026-10-02T12:00", "s2", "tool_error", command="python3 -m pytest -q", text="exit code 2")
add("2026-10-03T12:00", "s3", "tool_error", command="ls /nope", text="No such file or directory")
add("2026-10-03T12:05", "s3", "user_correction", tool="human", text="no, use the other folder")
for i in range(20):
    add(f"2026-10-0{1 + i % 3}T08:{i:02d}", f"s{1 + i % 3}", "tool_ok", command=["ls -la", "git status", "python3 app.py", "cat README.md"][i % 4], text="ok")
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    for e in sorted(ev, key=lambda e: (e["session"], e["ts"])):
        f.write(json.dumps(e) + "\n")
print(OUT, len(ev))

"""Adapter: public SWE-agent trajectories (e.g. HF nebius/SWE-agent-trajectories rows as JSONL) → domain Events.
One row = one session. An `ai` turn's last fenced block is the command; the next `user` turn is its observation."""
import json, re
from ..domain import Event

_BLOCK = re.compile(r"```[\w-]*\n(.*?)```", re.S)
_TAIL = re.compile(r"\n?\(Open file:.*$", re.S)            # SWE-agent's status footer
_ERROR = re.compile(r"command not found|\bnot found\b|No such file|Traceback \(most recent call last\)|\bError\b|error:|"
                    r"^Usage:|syntax error|introduced new syntax error|No matches found|can't open file", re.M)


def read(path):
    events, n = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line); n += 1
            session = f"{row.get('instance_id', '?')}#{row.get('offset', n)}"
            traj = row.get("trajectory") or []
            step = 0
            for i, msg in enumerate(traj):
                if msg.get("role") != "ai":
                    continue
                blocks = _BLOCK.findall(msg.get("text") or "")
                nxt = traj[i + 1] if i + 1 < len(traj) and traj[i + 1].get("role") == "user" else None
                if not blocks or nxt is None:
                    continue
                cmd = blocks[-1].strip()
                obs = _TAIL.sub("", nxt.get("text") or "").strip()
                kind = "tool_error" if _ERROR.search(obs) else "tool_ok"
                ts = f"{row.get('offset', n):07d}.{step:04d}"; step += 1
                events.append(Event(ts, session, kind, "Bash", cmd, obs[:500]))
    return events, n

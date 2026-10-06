"""Adapter: generic event JSONL — one {ts, session, kind, tool, command, text} per line (any agent can emit this)."""
import json
from ..domain import Event


def read(path):
    out = []
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    for line in lines:
        if line.strip():
            d = json.loads(line)
            out.append(Event(d.get("ts", ""), d.get("session", "?"), d["kind"], d.get("tool", "?"), d.get("command", ""), d.get("text", "")))
    return out

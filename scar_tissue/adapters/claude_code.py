"""Adapter: Claude Code transcript JSONL (~/.claude/projects/<proj>/<session>.jsonl) → domain Events."""
import json, os, glob
from ..domain import Event, is_correction, SHELL_ERR


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(_text(c.get("text") or c.get("content") or "") if isinstance(c, dict) else str(c) for c in content)
    return str(content or "")


def session_id(path):
    """A subagent transcript (<session>/subagents/agent-*.jsonl) belongs to its parent session."""
    parts = os.path.normpath(path).split(os.sep)
    if len(parts) >= 3 and parts[-2] == "subagents":
        return parts[-3]
    return os.path.splitext(parts[-1])[0]


def read_session(path):
    session = session_id(path)
    calls = {}  # tool_use_id → (tool, command)
    events = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            ts = d.get("timestamp", "")
            msg = d.get("message") or {}
            content = msg.get("content") if isinstance(msg, dict) else None
            if d.get("type") == "assistant" and isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        inp = b.get("input") or {}
                        cmd = inp.get("command") or inp.get("url") or inp.get("file_path") or inp.get("pattern") or ""
                        calls[b.get("id")] = (b.get("name", "?"), str(cmd))
            elif d.get("type") == "user":
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            tool, cmd = calls.get(b.get("tool_use_id"), ("?", ""))
                            txt = _text(b.get("content"))
                            if b.get("is_error"):
                                kind = "hook_block" if "hook error" in txt[:200] else "tool_error"
                            else:
                                kind = "tool_ok"
                            # keep the head of the output + any shell error lines further down (silent part-failures)
                            shell_err = SHELL_ERR.findall(txt[500:])[:3]
                            events.append(Event(ts, session, kind, tool, cmd, "\n".join([txt[:500]] + shell_err)))
                elif isinstance(content, str) and not d.get("isMeta") and not content.startswith("<"):
                    if is_correction(content):
                        events.append(Event(ts, session, "user_correction", "human", "", content[:300]))
    return events


def read_dir(pattern):
    """(events, number of sessions) — subagent transcripts are folded into their parent session."""
    events, ids = [], set()
    for p in sorted(glob.glob(os.path.expanduser(pattern), recursive=True)):   # `**` reaches subagent transcripts
        ids.add(session_id(p))
        events += read_session(p)
    return events, len(ids)

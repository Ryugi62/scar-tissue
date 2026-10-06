"""Pure domain: events → signatures → scars → rules. No I/O."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from collections import defaultdict

FAIL_THRESHOLD = 3          # same failure ≥3 times …
MIN_SESSIONS = 2            # … across ≥2 sessions
CORRECTION_THRESHOLD = 2    # or the human corrected it ≥2 times

ERROR_CLASSES = [  # (class, regex on error text) — first match wins
    ("timeout", r"timed? ?out|timeout|deadline exceeded|exceeded \d+ ?m?s"),
    ("permission", r"permission denied|not permitted|EACCES|authorization denied|-1728"),
    ("not-found", r"not found|no such file|ENOENT|404|command not found"),
    ("blocked", r"\bblocked\b|차단|denied by hook|hook error"),
    ("rejected", r"rejected|non-fast-forward|conflict"),
    ("http", r"HTTP ?[45]\d\d|status[ =:]+[45]\d\d"),
    ("exit", r"exit(?:ed)? (?:code|status)? ?[1-9]\d*|returned non-zero"),
]
CORRECTION_PAT = re.compile(
    r"^(no[,.! ]|stop\b|don'?t\b|do not\b|why did you|again\?|wrong\b|undo\b|never\b)"
    r"|^(아니[,. ]|하지 ?마|왜 또|멈춰|그만|틀렸|하지 말라고)", re.I)
GENERIC_FIRST = {"python3", "python", "node", "bash", "sh", "zsh", "sed", "grep", "rg", "echo", "cat", "ls", "head", "tail", "wc",
                 "mkdir", "rm", "cp", "mv", "find", "cd", "touch", "printf", "awk", "jq", "sort", "diff"}
GENERIC_HEADS = {"python3", "python", "node", "bash", "sh", "zsh", "sed", "grep", "echo", "cat", "ls", "head", "tail",
                 "git add", "git commit", "git status", "cd", "python3 -", "python -", "sed -n", "grep -n", "echo STR"}


@dataclass(frozen=True)
class Event:
    ts: str
    session: str
    kind: str          # tool_error | user_correction | hook_block | tool_ok
    tool: str
    command: str = ""
    text: str = ""


@dataclass
class Scar:
    signature: str
    tool: str
    head: str
    error_class: str
    failures: list = field(default_factory=list)      # Events
    corrections: list = field(default_factory=list)   # Events
    corrected_calls: list = field(default_factory=list)  # the tool calls the human corrected

    @property
    def sessions(self):
        return sorted({e.session for e in self.failures + self.corrections})

    @property
    def actionable(self) -> bool:
        """Can this scar become a precise guard rule? Not if it is already guarded (hook_block), names a whole tool,
        or the head is a generic interpreter/reader with no shared flag (would block normal work)."""
        if self.error_class == "blocked" or self.tool not in ("Bash",):
            return False
        first = self.head.split()[0] if self.head else ""
        if not re.match(r"^[a-z][\w.+-]*$", first):          # parse leftovers like "-k" or "d in" are not commands
            return False
        if self.head in GENERIC_HEADS or first in GENERIC_FIRST:
            examples = [e.command for e in self.failures + self.corrected_calls if e.command]
            common = set.intersection(*[set(c.split()) for c in examples]) - set(self.head.split()) if examples else set()
            return any(t.startswith("-") for t in common)
        return True

    @property
    def slug(self):
        return re.sub(r"[^a-z0-9]+", "-", f"{self.tool} {self.head} {self.error_class}".lower()).strip("-")[:60]


_STRIP = [
    (re.compile(r"'[^']*'|\"[^\"]*\""), "STR"),
    (re.compile(r"https?://\S+"), "URL"),
    (re.compile(r"(?:~|\.{0,2})?/[\w./\-~]+"), "PATH"),
    (re.compile(r"\b\d+(?:\.\d+)?\b"), "N"),
]
_SKIP_TOKENS = {"!", "cd", "in", "sudo", "env", "time", "timeout", "nohup", "&&", ";", "|", "then", "do", "for", "while", "until", "if"}


def command_head(command: str) -> str:
    """First two meaningful tokens of the first 'real' command (flags kept: `pgrep -f`, `git push`)."""
    cmd = command.strip()
    for a, b in _STRIP:
        cmd = a.sub(b, cmd)
    # split compound commands; pick the first part that is not a cd/var assignment
    parts = re.split(r"&&|\|\||;|\n|\|", cmd)
    for part in parts:
        toks = [t for t in part.split() if t]
        toks = [t for t in toks if not re.match(r"^\w+=", t)]
        if toks and toks[0] in ("for", "select") and len(toks) > 2:   # for x in …; do … → skip the loop header
            continue
        while toks and toks[0] in _SKIP_TOKENS:
            toks = toks[1:]
            if toks and toks[0] in ("PATH", "STR", "N"):
                toks = toks[1:]
        if not toks or toks[0] in ("PATH",):
            continue
        head = [toks[0]]
        if len(toks) > 1 and toks[1] not in ("PATH", "STR", "N", "URL"):
            t = toks[1]
            if re.match(r"^-[A-Za-z]{2,}$", t):   # short-flag cluster: -sL ≈ -s (same habit, different spelling)
                t = t[:2]
            head.append(t)
        return " ".join(head)
    return command.strip().split()[0] if command.strip() else ""


def error_class(text: str) -> str:
    for name, pat in ERROR_CLASSES:
        if re.search(pat, text or "", re.I):
            return name
    return "error"


def signature(ev: Event) -> tuple[str, str, str]:
    head = command_head(ev.command) if ev.command else ev.tool
    return ev.tool, head, error_class(ev.text)


def is_correction(text: str) -> bool:
    t = (text or "").strip()
    return len(t) <= 280 and bool(CORRECTION_PAT.search(t))


def detect(events: list[Event]) -> list[Scar]:
    """Group failures by signature; attach each user correction to the last failing/any tool call before it in the same session."""
    groups: dict[str, Scar] = {}
    last_call: dict[str, Event] = {}
    for ev in events:
        if ev.kind in ("tool_error", "hook_block", "tool_ok") and ev.command:
            last_call[ev.session] = ev
        if ev.kind in ("tool_error", "hook_block"):
            tool, head, ec = signature(ev)
            key = f"{tool}:{head}:{ec}"
            groups.setdefault(key, Scar(key, tool, head, ec)).failures.append(ev)
        elif ev.kind == "user_correction":
            prev = last_call.get(ev.session)
            if prev is None:
                continue
            tool, head, ec = signature(prev)
            if prev.kind == "tool_ok":
                ec = "corrected"
            key = f"{tool}:{head}:{ec}"
            sc = groups.setdefault(key, Scar(key, tool, head, ec))
            sc.corrections.append(ev); sc.corrected_calls.append(prev)
    scars = []
    for s in groups.values():
        sess = {e.session for e in s.failures}
        if (len(s.failures) >= FAIL_THRESHOLD and len(sess) >= MIN_SESSIONS) or len(s.corrections) >= CORRECTION_THRESHOLD:
            scars.append(s)
    return sorted(scars, key=lambda s: -(len(s.failures) + 2 * len(s.corrections)))


def compile_rule(scar: Scar, principle: str) -> dict:
    """A rule that matches the tool input of the failing calls: the command head as a word-bounded regex."""
    toks = scar.head.split()
    parts = [re.escape(t) + (r"[A-Za-z]?" if re.match(r"^-[A-Za-z]$", t) else "") for t in toks]   # -s also matches -sL
    # command position only: start, after ; & | ( ! or a shell keyword — so `echo pgrep -f` is not a pgrep call
    pat = r"(?:^|[;&|(!]\s*|\b(?:do|then|until|while|if)\s+)" + r"\s+".join(parts) + r"(?=\s|$)"
    # if every example shares a flag beyond the head (e.g. --force), require it — plain `git push` stays allowed
    examples = [e.command for e in scar.failures + scar.corrected_calls if e.command]
    if examples:
        common = set.intersection(*[set(c.split()) for c in examples]) - set(toks)
        flags = sorted(t for t in common if t.startswith("-"))
        if flags:
            pat = "".join(rf"(?=.*\s{re.escape(f)}(?:\s|$))" for f in flags) + pat
    return {"id": scar.slug, "tool": scar.tool, "pattern": pat, "message": principle,
            "evidence": {"failures": len(scar.failures), "corrections": len(scar.corrections), "sessions": len(scar.sessions)}}


def rule_matches(rule: dict, tool: str, tool_input: dict) -> bool:
    if rule["tool"] != tool:
        return False
    text = tool_input.get("command") or tool_input.get("url") or tool_input.get("file_path") or ""
    return re.search(rule["pattern"], text) is not None


def template_principle(scar: Scar) -> str:
    n, c = len(scar.failures), len(scar.corrections)
    why = []
    if n:
        why.append(f"failed {n}× ({scar.error_class}) across {len({e.session for e in scar.failures})} sessions")
    if c:
        why.append(f"was corrected by the human {c}×")
    return f"Avoid `{scar.head}` here — it {' and '.join(why)}. Use the documented alternative instead, or ask first."

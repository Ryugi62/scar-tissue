"""Pure domain: events → signatures → scars → rules. No I/O."""
from __future__ import annotations
import re
from functools import lru_cache
from dataclasses import dataclass, field
from collections import defaultdict

FAIL_THRESHOLD = 3          # same failure ≥3 times …
MIN_SESSIONS = 2            # … across ≥2 sessions
CORRECTION_THRESHOLD = 2    # or the human corrected it ≥2 times

ERROR_CLASSES = [  # (class, regex on error text) — first match wins
    ("timeout", r"timed? ?out|timeout|deadline exceeded|exceeded \d+ ?m?s"),
    ("permission", r"permission denied|not permitted|EACCES|authorization denied|-1728"),
    ("not-found", r"not found|no such file|ENOENT|404|command not found"),
    ("blocked", r"\bblocked\b|차단|denied by hook|hook error|has been denied|denied by a built-in"),
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

ROOT_CAUSE_CLASSES = ("missing-command", "zsh-equals", "zsh-nomatch")
_ROOT_CAUSES = [   # (class, regex on error text) — the cause is in the error, not in the command head
    ("missing-command", re.compile(r"command not found: ([\w.+-]+)|(?:^|\s)([\w.+-]+): command not found", re.M)),
    ("zsh-equals", re.compile(r"(?:\(eval\)|zsh):\d+: (=+)\S* not found")),
    ("zsh-nomatch", re.compile(r"no matches found: (\S+)")),
]
# command position: start of a simple command (after a separator, a shell keyword, or a newline)
CMD_POS = r"(?:^|[;&|(!{]\s*|\n\s*|\b(?:do|then|else|until|while|if|time|sudo|env|nohup|exec)\s+)"
# the shapes a fix usually takes — learned per scar only if a recovery has the marker and no failure does
REMEDY_MARKERS = {
    "bounded-loop": r"\bfor\s+\w+\s+in\s+(?:\{\d+\.\.\d+\}|\$\(seq\b)",
    "time-limit-wrapper": r"(?:^|[;&|]\s*)(?:g?timeout\s+\d|perl\s+-e\s+['\"]alarm)",
    "self-match-safe-pattern": r"-f\s+['\"]?\[[^\]]+\]",
}
BENEFIT_RATIO = 20    # beyond 3 false blocks, a rule must stop ≥20 mistakes per success it blocks
RECOVERY_WINDOW = 6   # a recovery is a success with the same head within 6 calls after the failure


def root_cause(text: str):
    """(cause class, cause head) when the error text names the real cause, else None."""
    for cls, pat in _ROOT_CAUSES:
        m = pat.search(text or "")
        if not m:
            continue
        tok = next(g for g in m.groups() if g)
        if cls == "missing-command":
            return cls, tok
        if cls == "zsh-equals":
            return cls, "=word"
        flag = re.match(r"^(--?[\w-]+=)", tok)
        return cls, (flag.group(1) + "*") if flag else "glob"
    return None


SHELL_ERR = re.compile(r"(?:\(eval\)|(?<![\w/.-])(?:zsh|bash)):\d+: [^\n]*")   # an error line printed by the shell itself


@lru_cache(maxsize=65536)
def silent_root_cause(text: str):
    """A call that exited 0 can still have failed part-way: only a shell-prefixed error line counts (`(eval):1: …`, `zsh:3: …`)."""
    lines = "\n".join(SHELL_ERR.findall(text or ""))
    return root_cause(lines) if lines else None


@lru_cache(maxsize=65536)
def shell_view(cmd: str) -> str:
    """The words the shell actually parses: heredoc bodies, quoted strings, comments, [[ ]] and (( )) blanked."""
    s = re.sub(r"<<-?\s*(['\"]?)(\w+)\1([^\n]*)\n(?:.*?\n)?[ \t]*\2[ \t]*(?=\n|$)", r"<<H\3", cmd or "", flags=re.S)
    s = re.sub(r"\$?'[^']*'|\"(?:\\.|[^\"\\])*\"", "Q", s)
    s = re.sub(r"(?:(?<=\s)|^)#[^\n]*", "", s, flags=re.M)
    s = re.sub(r"\[\[.*?\]\]", "[[ ]]", s)
    return re.sub(r"\$?\(\(.*?\)\)", "(( ))", s)


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
    recoveries: list = field(default_factory=list)    # the agent's own fixes: successful calls right after a failure

    @property
    def sessions(self):
        return sorted({e.session for e in self.failures + self.corrections})

    @property
    def actionable(self) -> bool:
        """Can this scar become a precise guard rule? Not if it is already guarded (hook_block), names a whole tool,
        or the head is a generic interpreter/reader with no shared flag (would block normal work)."""
        if self.error_class == "blocked" or self.tool not in ("Bash",):
            return False
        if self.error_class in ROOT_CAUSE_CLASSES:     # the error text named the cause → precise by construction
            return not getattr(self, "demoted", False)
        if self.error_class in ("exit", "error", "not-found") and not self.corrections:
            return False   # a non-zero exit is an outcome, not a habit — needs a timeout/permission/rejection or a human correction
        if getattr(self, "demoted", False):
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
    rc = root_cause(ev.text) if ev.kind == "tool_error" else silent_root_cause(ev.text) if ev.kind == "tool_ok" else None
    if rc:
        return ev.tool, rc[1], rc[0]
    head = command_head(ev.command) if ev.command else ev.tool
    return ev.tool, head, error_class(ev.text)


def is_correction(text: str) -> bool:
    t = (text or "").strip()
    return len(t) <= 280 and bool(CORRECTION_PAT.search(t))


def detect(events: list[Event]) -> list[Scar]:
    """Group failures by signature; attach each user correction to the last tool call before it in the same session;
    attach each recovery (same tool + same command head, success, within RECOVERY_WINDOW calls) to the failure's scar."""
    groups: dict[str, Scar] = {}
    last_call: dict[str, Event] = {}
    pending: dict[str, list] = {}    # session → [(scar key, tool, head, calls left)]
    failed: dict = {}                 # (scar key, head) → the latest failing command
    for ev in events:
        silent = ev.kind == "tool_ok" and silent_root_cause(ev.text) is not None
        if ev.kind in ("tool_error", "hook_block", "tool_ok") and ev.command:
            last_call[ev.session] = ev
            waiting = []
            for key, tool, head, left in pending.get(ev.session, []):
                if ev.kind == "tool_ok" and not silent and ev.tool == tool and (command_head(ev.command) == head or
                                                                               _same_task(failed[key, head], ev.command, key)):
                    if not any(r is ev for r in groups[key].recoveries):   # one fix can resolve several pending failures
                        groups[key].recoveries.append(ev)
                elif left > 1:
                    waiting.append((key, tool, head, left - 1))
            pending[ev.session] = waiting
        if ev.kind in ("tool_error", "hook_block") or silent:
            tool, head, ec = signature(ev)
            key = f"{tool}:{head}:{ec}"
            groups.setdefault(key, Scar(key, tool, head, ec)).failures.append(ev)
            if ev.kind != "hook_block" and ev.command:
                pending.setdefault(ev.session, []).append((key, ev.tool, command_head(ev.command), RECOVERY_WINDOW))
                failed[key, command_head(ev.command)] = ev.command
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


def _words(cmd: str) -> set:
    return set(re.findall(r"[A-Za-z_][\w.-]+", cmd or ""))


def _same_task(failed_cmd: str, ok_cmd: str, key: str) -> bool:
    """Root-cause failures are often fixed with a different head (`timeout 60 npm test` → `perl -e 'alarm 60…' npm test`):
    the success counts as a recovery if it keeps ≥60% of the failing command's words (minimum 2) besides the cause."""
    if key.rsplit(":", 1)[-1] not in ROOT_CAUSE_CLASSES:
        return False
    cause = key.split(":")[1]
    f = _words(failed_cmd) - {cause}
    return len(f) >= 2 and len(f & _words(ok_cmd)) / len(f) >= 0.6


def validate_against_history(scars, events, max_rate=0.005, max_count=3):
    """Self-validation: replay every candidate rule against the agent's own SUCCESSFUL calls.
    A rule is demoted to advice if it would have blocked normal work more than max_count times AND more than once per
    BENEFIT_RATIO mistakes it stops, or more than max_rate of all successful calls.
    Fix-safety: a rule that would block one of the agent's own recoveries is demoted too."""
    corrected = {id(c) for sc in scars for c in sc.corrected_calls}   # calls the human corrected are not "normal work"
    ok = {}
    for e in events:
        if e.kind == "tool_ok" and e.command and id(e) not in corrected and silent_root_cause(e.text) is None:
            ok.setdefault(e.tool, []).append(e.command)
    report = []
    for s in scars:
        if not s.actionable:
            continue
        rule = compile_rule(s, "")
        hits = sum(1 for c in ok.get(s.tool, []) if rule_matches(rule, s.tool, {"command": c}))
        n = max(1, len(ok.get(s.tool, [])))
        s.false_blocks = hits
        s.blocks_own_fix = sum(1 for r in s.recoveries if rule_matches(rule, s.tool, {"command": r.command}))
        benefit = len(s.failures) + len(s.corrections)   # mistakes the rule would have stopped
        if (hits > max_count and hits * BENEFIT_RATIO > benefit) or hits / n > max_rate or s.blocks_own_fix:
            s.demoted = True
        report.append((s.signature, hits, n, getattr(s, "demoted", False)))
    return report


def _unless(scar: Scar) -> list:
    """Exemptions learned from recoveries: remedy markers and flags a recovery has and no failure has."""
    fails = [e.command for e in scar.failures + scar.corrected_calls if e.command]
    recs = [e.command for e in scar.recoveries if e.command]
    out = []
    for pat in REMEDY_MARKERS.values():
        if any(re.search(pat, r) for r in recs) and not any(re.search(pat, f) for f in fails):
            out.append(pat)
    if scar.error_class in ROOT_CAUSE_CLASSES:     # root-cause rules match the cause itself; unrelated flags are not a fix
        return out
    fail_flags = {t for f in fails for t in f.split() if t.startswith("-")}
    for flag in sorted({t for r in recs for t in r.split() if re.match(r"^--?[A-Za-z][\w-]*$", t)} - fail_flags):
        out.append(r"(?:^|\s)" + re.escape(flag) + r"(?=[\s=]|$)")
    return out


def compile_rule(scar: Scar, principle: str) -> dict:
    """A rule that matches the tool input of the failing calls. Root-cause scars match the shell view; head scars match the
    command head at command position (+ the flags every example shares). Exemptions (`unless`) come from the agent's own fixes."""
    view = "raw"
    if scar.error_class == "missing-command":
        pat, view = CMD_POS + re.escape(scar.head) + r"(?=\s|$)", "shell"
    elif scar.error_class == "zsh-equals":
        pat, view = r"(?:^|\s)=[^\s(]\S*", "shell"      # zsh expands an unquoted `=word` to a command path (`==`, `===`)
    elif scar.error_class == "zsh-nomatch":
        lead = re.escape(scar.head[:-1]) if scar.head != "glob" else r"[^\s=]*"
        pat, view = r"(?:^|\s)" + lead + r"\S*[*?]", "shell"
    else:
        toks = scar.head.split()
        parts = [re.escape(t) + (r"[A-Za-z]?" if re.match(r"^-[A-Za-z]$", t) else "") for t in toks]   # -s also matches -sL
        pat = CMD_POS + r"\s+".join(parts) + r"(?=\s|$)"
        examples = [e.command for e in scar.failures + scar.corrected_calls if e.command]
        if examples:   # every example shares a flag beyond the head (e.g. --force) → require it; plain `git push` stays allowed
            common = set.intersection(*[set(c.split()) for c in examples]) - set(toks)
            flags = sorted(t for t in common if t.startswith("-"))
            if flags:   # anchored at ^ so each lookahead runs once per command (not once per position)
                pat = "^" + "".join(rf"(?=[\s\S]*\s{re.escape(f)}(?:\s|$))" for f in flags) + r"[\s\S]*?" + pat
    rec = scar.recoveries[-1].command if scar.recoveries else ""
    if rec and principle:
        principle = principle.rstrip() + f" Worked before: `{rec[:160]}`"
    return {"id": scar.slug, "tool": scar.tool, "pattern": pat, "view": view, "unless": _unless(scar), "message": principle,
            "evidence": {"failures": len(scar.failures), "corrections": len(scar.corrections), "sessions": len(scar.sessions),
                         "recoveries": len(scar.recoveries)}}


def _candidates(text: str) -> list:
    """The command plus any `bash -c '…'` / `sh -lc "…"` payloads, so wrapped commands are checked too."""
    return [text] + [m[1] for m in re.findall(r"\b(?:ba|z)?sh\s+-l?c\s+(['\"])(.*?)\1", text, re.S)]


def rule_matches(rule: dict, tool: str, tool_input: dict) -> bool:
    if rule.get("tool") != tool:
        return False
    text = tool_input.get("command") or tool_input.get("url") or tool_input.get("file_path") or ""
    for t in _candidates(text):
        if any(re.search(u, t) for u in rule.get("unless", [])):
            continue
        if re.search(rule["pattern"], shell_view(t) if rule.get("view") == "shell" else t):
            return True
    return False


_CAUSE_ADVICE = {
    "missing-command": "`{head}` is not installed on this machine",
    "zsh-equals": "this shell is zsh: an unquoted word starting with `=` (`===`, `[ a == b ]`) is expanded as a command path and fails — quote it or use `[[ … ]]`",
    "zsh-nomatch": "this shell is zsh: an unquoted glob that matches nothing (`{head}`) aborts the whole command — quote the pattern",
}


def template_principle(scar: Scar) -> str:
    n, c = len(scar.failures), len(scar.corrections)
    why = []
    if n:
        why.append(f"failed {n}× ({scar.error_class}) across {len({e.session for e in scar.failures})} sessions")
    if c:
        why.append(f"was corrected by the human {c}×")
    if scar.error_class == "timeout" and n:
        return (f"`{scar.head}` ran until the tool timeout {n}× across {len({e.session for e in scar.failures})} sessions"
                + (f" and was corrected by the human {c}×" if c else "") + " — bound the wait: a fixed retry count or a time limit.")
    if scar.error_class in _CAUSE_ADVICE:
        return _CAUSE_ADVICE[scar.error_class].format(head=scar.head).capitalize() + f" ({' and '.join(why)})."
    examples = [e.command for e in scar.failures + scar.corrected_calls if e.command]
    shared = sorted(t for t in set.intersection(*[set(x.split()) for x in examples]) - set(scar.head.split())
                    if t.startswith("-")) if examples else []
    said = f' The human said: "{scar.corrections[-1].text.strip()[:120]}".' if c else ""
    return f"Avoid `{' '.join([scar.head] + shared)}` here — it {' and '.join(why)}.{said} Use the safer alternative, or ask first."

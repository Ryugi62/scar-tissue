"""Pure domain: events → signatures → scars → rules. No I/O."""
from __future__ import annotations
import re
from functools import lru_cache
from dataclasses import dataclass, field
from .shell import parse
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
    r"|^(하지 ?마|왜 또|멈춰|그만|틀렸|하지 말라고)|^아니[,. ]+(그거|그렇게|이거|그만|하지|왜|틀)", re.I)
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
# the shapes a fix usually takes — learned per scar only if a recovery has the marker and no failure does
REMEDY_MARKERS = {
    "bounded-loop": r"\bfor\s+\w+\s+in\s+(?:\{\d+\.\.\d+\}|\$\(seq\b)",
    "time-limit-wrapper": r"(?:^|[;&|]\s*)(?:g?timeout\s+\d|perl\s+-e\s+['\"]alarm)",
    "self-match-safe-pattern": r"-f\s+['\"]?\[[^\]]+\]",
}
BENEFIT_RATIO = 20    # a rule must stop ≥20 mistakes for every successful call it would block
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


SHELL_ERR = re.compile(r"(?:\(eval\)|(?<![\w/.-])(?:zsh|bash)):\d+: [^\n]*"          # zsh / Claude Code eval
                       r"|(?:(?<=\n)|^)(?:/\S*/)?(?:ba)?sh: line \d+: [^\n]*", re.M)       # bash: line 1: rg: command not found


@lru_cache(maxsize=65536)
def silent_root_cause(text: str, command: str | None = None):
    """A call that exited 0 can still have failed part-way: a shell-prefixed error line (`(eval):1: …`, `zsh:3: …`,
    `bash: line 1: …`) whose cause the command itself confirms — so `cat ci.log` printing such a line, or a deliberate
    `rg … || grep …` fallback, is not a failure. Without a command, only the output is checked (older callers)."""
    for line in SHELL_ERR.findall(text or ""):
        rc = root_cause(line)
        if rc and (command is None or _confirms(command, rc, line)):
            return rc
    return None


def _confirms(command: str, rc, line: str) -> bool:
    cls, head = rc
    cs = parse(command)
    if cls == "zsh-nomatch":
        tok = (re.search(r"no matches found: (\S+)", line) or [None, ""])[1]
        return any(w == tok and c.unquoted_glob(i) for c in cs for i, w in enumerate(c.words))
    if cls == "zsh-equals":
        return any(c.shell == "zsh" and not c.test and c.unquoted_equals_word(i) for c in cs for i in range(len(c.words)))
    if cls == "missing-command":
        if re.search(r"(?:^|[;&|(\s])" + re.escape(head) + r"\b[^;&|\n]*\|\|", command):   # `rg … || grep …` is a fallback
            return False
        return any(_command_hits({"kind": "missing-command", "name": head}, c) for c in cs)
    return True


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
    rc = root_cause(ev.text) if ev.kind == "tool_error" else silent_root_cause(ev.text, ev.command) if ev.kind == "tool_ok" else None
    if rc:
        return ev.tool, rc[1], rc[0]
    head = command_head(ev.command) if ev.command else ev.tool
    return ev.tool, head, error_class(ev.text)


NOT_CORRECTION = re.compile(r"^(no (worries|problem|need|thanks)|never ?mind|don'?t (forget|worry)|no, (it'?s )?(fine|ok|good))"
                            r"|^아니 ?(괜찮|됐어|좋아)", re.I)


def is_correction(text: str) -> bool:
    t = (text or "").strip()
    return len(t) <= 280 and bool(CORRECTION_PAT.search(t)) and not NOT_CORRECTION.search(t)


def _mentioned_head(command: str, said: str):
    """The head of the simple command the human's message talks about (shares a word ≥3 letters with its name, subcommand
    or flags), or None — a "no" that names nothing in the call is not pinned on it."""
    said = (said or "").lower()
    for c in parse(command):
        words = {w.lower().lstrip("-") for w in c.words[:1] + tuple(x for x in c.words[1:2] if not x.startswith("-"))
                 + tuple(x for x in c.words if x.startswith("-"))}
        if any(len(w) >= 3 and w.isascii() and w in said for w in words):
            return command_head(c.text)
    return None


def detect(events: list[Event]) -> list[Scar]:
    """Group failures by signature; attach each user correction to the last tool call before it in the same session;
    attach each recovery (same tool + same command head, success, within RECOVERY_WINDOW calls) to the failure's scar."""
    groups: dict[str, Scar] = {}
    last_call: dict[str, Event] = {}
    pending: dict[str, list] = {}    # session → [(scar key, tool, head, calls left)]
    failed: dict = {}                 # (scar key, head) → the latest failing command
    for ev in events:
        silent = ev.kind == "tool_ok" and silent_root_cause(ev.text, ev.command) is not None
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
            head = _mentioned_head(prev.command, ev.text) if prev is not None else None
            if head is None:
                continue
            tool, _, ec = signature(prev)
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
    A rule is demoted to advice if it would block normal work more than once per BENEFIT_RATIO mistakes it stops, or more
    than max_rate of all successful calls (max_count is kept for API compatibility).
    Fix-safety: a rule that would block one of the agent's own recoveries is demoted too."""
    corrected = {id(c) for sc in scars for c in sc.corrected_calls}   # calls the human corrected are not "normal work"
    ok = {}
    for e in events:
        if e.kind == "tool_ok" and e.command and id(e) not in corrected and silent_root_cause(e.text, e.command) is None:
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
        if (hits > 0 and hits * BENEFIT_RATIO > benefit) or hits / n > max_rate or s.blocks_own_fix:
            s.demoted = True
        report.append((s.signature, hits, n, getattr(s, "demoted", False)))
    return report


def _unless(scar: Scar) -> dict:
    """Exemptions learned from recoveries: remedy markers and flags a recovery's matching command has and no failure has."""
    fails = [e.command for e in scar.failures + scar.corrected_calls if e.command]
    recs = [e.command for e in scar.recoveries if e.command]
    out = {"markers": [], "flags": []}
    if scar.error_class in ROOT_CAUSE_CLASSES:     # root-cause rules match the cause itself; unrelated flags are not a fix
        return out
    for pat in REMEDY_MARKERS.values():
        if any(re.search(pat, r) for r in recs) and not any(re.search(pat, f) for f in fails):
            out["markers"].append(pat)
    fail_flags = {t for f in fails for t in f.split() if t.startswith("-")}
    out["flags"] = sorted({t for r in recs for t in r.split() if re.match(r"^--?[A-Za-z][\w-]*$", t)} - fail_flags)
    return out


def _head_context(scar: Scar, head: list) -> str | None:
    """`loop` if every failing example ran the head inside an unbounded while/until loop (the habit is the wait, not the tool)."""
    probe = {"kind": "head", "tool": scar.tool, "head": head, "flags": [], "context": None, "unless": {}}
    seen = []
    for e in scar.failures + scar.corrected_calls:
        cs = [c for c in parse(e.command) if _head_hit(probe, c)]
        if cs:
            seen.append(any(c.loop in ("while", "until") for c in cs))
    return "loop" if seen and all(seen) else None


def fix_excerpt(scar: Scar, recovery: str, limit: int = 120):
    """The one simple command in a recovery that carries the fix (e.g. the quoted `--include='*.md'`), or None."""
    cs = parse(recovery)
    if scar.error_class == "zsh-nomatch":
        pre = None if scar.head == "glob" else scar.head[:-1]
        hit = [c for c in cs if any((pre is None or w.startswith(pre)) and any(ch in "*?" for ch in w) and not c.unquoted_glob(i)
                                    for i, w in enumerate(c.words[1:], 1))]
    elif scar.error_class == "zsh-equals":
        hit = [c for c in cs if any(len(w) >= 2 and w[0] == "=" and not c.unquoted_equals_word(i) for i, w in enumerate(c.words))]
    elif scar.error_class == "missing-command":
        failed = {w for e in scar.failures for c in parse(e.command) for w in c.words if scar.head in c.words}
        hit = sorted((c for c in cs if scar.head not in c.words and len(failed & set(c.words)) >= 2),
                     key=lambda c: -len(failed & set(c.words)))
    else:   # a head habit's fix is the whole call (e.g. the bounded loop around pgrep), minus a leading `cd …` hop
        probe = {"kind": "head", "tool": scar.tool, "head": scar.head.split(), "flags": [], "context": None}
        if not any(_head_hit(probe, c) for c in cs):
            return None
        return re.sub(r"^\s*cd\s+\S+\s*(&&|;)\s*", "", recovery).split("\n")[0][:limit]
    return hit[0].text[:limit] if hit else None


def compile_rule(scar: Scar, principle: str) -> dict:
    """A structured rule, matched per simple command by the shell tokenizer (scar_tissue.shell): root-cause rules look at
    the words zsh actually sees; head rules at the command name, subcommand and required flags (aliases and clusters too)."""
    base = {"id": scar.slug, "tool": scar.tool}
    if scar.error_class == "missing-command":
        rule = {**base, "kind": "missing-command", "name": scar.head}
    elif scar.error_class == "zsh-equals":
        rule = {**base, "kind": "zsh-equals"}
    elif scar.error_class == "zsh-nomatch":
        rule = {**base, "kind": "zsh-nomatch", "prefix": None if scar.head == "glob" else scar.head[:-1]}
    else:
        head = scar.head.split()
        probe = {"kind": "head", "tool": scar.tool, "head": head, "flags": [], "context": None}
        arg_sets = []
        for e in scar.failures + scar.corrected_calls:   # flags of the simple command that ran the head, not the whole line
            cs = [c for c in parse(e.command) if _head_hit(probe, c)]
            if cs:
                arg_sets.append({w for c in cs for w in c.words[1:]})
        flags = []
        if arg_sets:   # every example shares a flag beyond the head (e.g. --force) → require it; plain `git push` stays allowed
            flags = sorted(t for t in set.intersection(*arg_sets) - set(head) if t.startswith("-"))
        rule = {**base, "kind": "head", "head": head, "flags": flags, "context": _head_context(scar, head)}
    rule["unless"] = _unless(scar)
    rec = next((x for x in (fix_excerpt(scar, r.command) for r in reversed(scar.recoveries)
                            if not rule_matches(rule, scar.tool, {"command": r.command})) if x), "")
    if rec and principle:
        principle = principle.rstrip() + f" Worked before: `{rec}`"
    rule["message"] = principle
    rule["evidence"] = {"failures": len(scar.failures), "corrections": len(scar.corrections), "sessions": len(scar.sessions),
                        "recoveries": len(scar.recoveries)}
    return rule


FLAG_ALIASES = {"--force": {"-f"}, "-f": {"--force"}, "--recursive": {"-r", "-R"}, "-r": {"--recursive"}}
WRAPPERS = {"nice", "nohup", "time", "command", "builtin", "exec", "sudo", "env", "xargs", "timeout", "gtimeout", "stdbuf",
            "caffeinate", "noglob", "doas", "parallel", "nocorrect"}
_WRAPPER_VALUE_OPTS = {   # options that take a separate value, per wrapper (env -i takes none; env -u NAME takes one)
    "env": {"-u", "-C", "-S"}, "nice": {"-n"}, "xargs": {"-I", "-n", "-L", "-P", "-s", "-d", "-E", "-a"},
    "timeout": {"-s", "-k"}, "gtimeout": {"-s", "-k"}, "sudo": {"-u", "-g", "-C", "-h"}, "doas": {"-u", "-C"},
    "parallel": {"-j", "-S", "--jobs"}, "caffeinate": {"-t", "-w"}}
_GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix", "--config-env"}
FLAG_SHAPES = {"--force": r"^\+\S"}   # git push origin +main is a force push


def _chain(words: tuple) -> tuple[list, int]:
    """(wrapper words in front of the real command, index of the real command): `FOO=1 nice timeout 5 make` → ([nice, timeout], 4)."""
    i, chain = 0, []
    while i < len(words) and re.match(r"^[A-Za-z_]\w*=", words[i]):
        i += 1
    while i < len(words) and words[i].rsplit("/", 1)[-1] in WRAPPERS:
        w = words[i].rsplit("/", 1)[-1]; chain.append(w); i += 1
        while i < len(words) and (words[i].startswith("-") or re.match(r"^(\d+(\.\d+)?[smhd]?|[A-Za-z_]\w*=.*|:::)$", words[i])):
            i += 2 if words[i] in _WRAPPER_VALUE_OPTS.get(w, ()) else 1
    return chain, i


def _has_flag(flag: str, args) -> bool:
    names = {flag} | FLAG_ALIASES.get(flag, set())
    short = {n[1] for n in names if re.match(r"^-[A-Za-z]$", n)}
    for a in args:
        if a in names or any(a.startswith(n + "=") for n in names if n.startswith("--")):
            return True
        if short and re.match(r"^-[A-Za-z]{2,}$", a) and short & set(a[1:]):
            return True
        if flag in FLAG_SHAPES and re.match(FLAG_SHAPES[flag], a):
            return True
    return False


def _head_hit(rule: dict, c) -> bool:
    chain, k = _chain(c.words)
    if k >= len(c.words) or c.words[k].rsplit("/", 1)[-1] != rule["head"][0]:
        return False
    args = list(c.words[k + 1:])
    if len(rule["head"]) > 1:
        sub = rule["head"][1]
        if sub.startswith("-"):
            if not _has_flag(sub, args):
                return False
        else:                                            # subcommand after global options: git -C dir push
            j = 0
            while j < len(args) and args[j].startswith("-"):
                j += 2 if args[j] in _GIT_VALUE_OPTS else 1
            if j >= len(args) or args[j] != sub:
                return False
            args = args[j + 1:]
    if not all(_has_flag(f, args) for f in rule.get("flags", [])):
        return False
    if rule.get("context") == "loop" and c.loop not in ("while", "until"):
        return False
    return True


def _command_hits(rule: dict, c) -> bool:
    kind = rule.get("kind", "head")
    if kind == "missing-command":
        if c.words and (c.words[0] in ("type", "which", "whence", "hash", "where") or
                        (c.words[0] == "command" and len(c.words) > 1 and c.words[1] in ("-v", "-V"))):
            return False                                  # asking whether it exists is not running it
        chain, k = _chain(c.words)
        return rule["name"] in chain or (k < len(c.words) and c.words[k].rsplit("/", 1)[-1] == rule["name"])
    if kind in ("zsh-equals", "zsh-nomatch"):
        if c.shell != "zsh" or c.test or "noglob" in _chain(c.words)[0]:
            return False
        if kind == "zsh-equals":
            return any(c.unquoted_equals_word(i) for i in range(len(c.words)))
        pre = rule.get("prefix")
        return any(c.unquoted_glob(i) and (pre is None or c.words[i].startswith(pre)) for i in range(1, len(c.words)))
    if not _head_hit(rule, c):
        return False
    u = rule.get("unless") or {}
    if any(re.search(m, c.text) for m in u.get("markers", [])):
        return False
    if any(_has_flag(f, c.words[1:]) for f in u.get("flags", [])):
        return False
    return True


def describe(rule: dict) -> str:
    k = rule.get("kind", "head")
    if k == "missing-command":
        return f"any command that runs `{rule['name']}` (also behind env/nice/xargs/command wrappers and inside $(…))"
    if k == "zsh-equals":
        return "an unquoted zsh word starting with `=` (`===`, `==`), outside [[ ]] / (( )) and outside bash -c payloads"
    if k == "zsh-nomatch":
        return f"an unquoted glob{' in `' + rule['prefix'] + '…`' if rule.get('prefix') else ''} in zsh"
    s = "`" + " ".join(rule["head"] + rule.get("flags", [])) + "`" + (" inside an unbounded while/until loop" if rule.get("context") == "loop" else "")
    u = rule.get("unless") or {}
    if u.get("markers") or u.get("flags"):
        s += f" — except the shape of the agent's own fix ({', '.join(u.get('flags', []) + [m for m in u.get('markers', [])])})"
    return s


def rule_matches(rule: dict, tool: str, tool_input: dict) -> bool:
    if rule.get("tool") != tool:
        return False
    text = tool_input.get("command") or ""
    return any(_command_hits(rule, c) for c in parse(text))


ENV_FIX = {   # for the human: the one-line environment change that removes a root cause (Scar Tissue found that it is needed)
    "zsh-equals": "`unsetopt EQUALS` in the zsh profile the agent's shell loads (makes `===` a plain word)",
    "zsh-nomatch": "`setopt NO_NOMATCH` in that profile (unmatched globs are passed through, like bash)",
    "missing-command": "install `{head}` or keep the guard (for `timeout`: `brew install coreutils` provides `gtimeout`)",
}

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

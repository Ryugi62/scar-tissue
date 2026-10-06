"""A small, linear-time shell tokenizer: enough to know which simple commands the shell will actually run, with which
words, which characters were quoted, inside which loop, and in which shell (zsh, or bash for `bash -c` payloads).
Pure and stdlib-only. Not a full POSIX parser — it is built to never be slower than linear and never to crash."""
from __future__ import annotations
import re
from dataclasses import dataclass
from functools import lru_cache

MAX_LEN = 20000          # the guard looks at the first 20k characters of a command
MAX_DEPTH = 4            # nested $(…), `…`, bash -c '…'
_SKIP_KW = {"if", "then", "else", "elif", "fi", "do", "!", "{", "}", "time", "case", "esac", "function", "coproc"}
_OPS3 = ("<<<", "<<-", "&>>")
_OPS2 = ("&&", "||", "|&", ";;", ">>", "<<", "&>", ">&", "<&", ">|")
_SEPARATORS = {";", "&", "&&", "||", "|", "|&", ";;", "\n", "(", ")"}
_REDIRS = {">", "<", ">>", "<<", "<<<", "<<-", "&>", "&>>", ">&", "<&", ">|"}


@dataclass(frozen=True)
class Command:
    words: tuple          # word values after quote removal
    masks: tuple          # per word: tuple of bools, True = that character was unquoted
    loop: str | None      # innermost enclosing loop: "while" | "until" | "for" | None
    shell: str            # "zsh" or "bash"
    text: str             # raw source of this simple command
    test: bool = False    # [[ … ]] or (( … )) — conditional/arithmetic context

    def unquoted_glob(self, i: int) -> bool:
        return any(ch in "*?" and m for ch, m in zip(self.words[i], self.masks[i]))

    def unquoted_equals_word(self, i: int) -> bool:
        w = self.words[i]
        return len(w) >= 2 and w[0] == "=" and self.masks[i][0] and w[1] != "("


def _balanced(s: str, i: int, open_ch: str, close_ch: str) -> int:
    """Index just after the matching close (s[i] is just after the opener). Quotes skipped. Linear; end of string if unclosed."""
    depth, n = 1, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2; continue
        if c == "'":
            j = s.find("'", i + 1); i = n if j < 0 else j + 1; continue
        if c == '"':
            i = _dq_end(s, i + 1); continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _dq_end(s: str, i: int) -> int:
    n = len(s)
    while i < n:
        if s[i] == "\\":
            i += 2; continue
        if s[i] == '"':
            return i + 1
        i += 1
    return n


def _tokens(s: str, subs: list):
    """Yield ("w", value, mask, start, end) | ("op", op, start) | ("arith", start, end). Substitution bodies go to `subs`."""
    i, n = 0, len(s)
    val, mask, start = [], [], None
    heredocs = []                                       # pending delimiters
    expect_heredoc = None

    def flush():
        nonlocal val, mask, start
        if start is not None:
            tok = ("w", "".join(val), tuple(mask), start, i)
            val, mask, start = [], [], None
            return tok
        return None

    while i < n:
        c = s[i]
        if c in " \t":
            t = flush()
            if t: yield t
            i += 1; continue
        if c == "\n":
            t = flush()
            if t: yield t
            yield ("op", "\n", i)
            i += 1
            for delim in heredocs:                      # skip heredoc bodies
                while i < n:
                    j = s.find("\n", i); j = n if j < 0 else j
                    line = s[i:j]; i = j + 1
                    if line.strip() == delim:
                        break
            heredocs = []
            continue
        if c == "#" and start is None:
            j = s.find("\n", i); i = n if j < 0 else j
            continue
        if c == "\\":
            if i + 1 < n and s[i + 1] == "\n":
                i += 2; continue
            if start is None: start = i
            if i + 1 < n:
                val.append(s[i + 1]); mask.append(False)
            i += 2; continue
        if c == "'":
            if start is None: start = i
            j = s.find("'", i + 1); j = n if j < 0 else j
            val.extend(s[i + 1:j]); mask.extend([False] * (j - i - 1)); i = j + 1; continue
        if c == "$" and s.startswith("$'", i):
            if start is None: start = i
            j = i + 2
            while j < n and s[j] != "'":
                j += 2 if s[j] == "\\" else 1
            val.append("Q"); mask.append(False); i = j + 1; continue
        if c == '"':
            if start is None: start = i
            j = _dq_end(s, i + 1)
            body = s[i + 1:j - 1]
            for m in re.finditer(r"\$\(", body):          # command substitutions inside double quotes still run
                if not body.startswith("$((", m.start()):
                    e = _balanced(body, m.end(), "(", ")"); subs.append(body[m.end():e - 1])
            val.extend(body); mask.extend([False] * len(body)); i = j; continue
        if c == "$" and s.startswith("$((", i):
            if start is None: start = i
            e = _balanced(s, i + 3, "(", ")"); e = min(n, e + (1 if e < n and s[e:e + 1] == ")" else 0))
            val.append("0"); mask.append(False); i = e; continue
        if c == "$" and s.startswith("$(", i):
            if start is None: start = i
            e = _balanced(s, i + 2, "(", ")")
            subs.append(s[i + 2:e - 1]); val.append("S"); mask.append(False); i = e; continue
        if c == "$" and s.startswith("${", i):
            if start is None: start = i
            e = _balanced(s, i + 2, "{", "}")
            val.append("V"); mask.append(False); i = e; continue
        if c == "`":
            if start is None: start = i
            j = i + 1
            while j < n and s[j] != "`":
                j += 2 if s[j] == "\\" else 1
            subs.append(s[i + 1:j]); val.append("S"); mask.append(False); i = j + 1; continue
        if c == "(" and s.startswith("((", i) and start is None:   # (( arithmetic ))
            e = s.find("))", i + 2); e = n if e < 0 else e + 2
            yield ("arith", i, e); i = e; continue
        if c in ";&|()<>":
            if c in "<>" and start is not None and "".join(val).isdigit():   # 2>&1, 1>/dev/null
                val, mask, start = [], [], None
            t = flush()
            if t: yield t
            op = next((o for o in _OPS3 if s.startswith(o, i)), None) or next((o for o in _OPS2 if s.startswith(o, i)), None) or c
            yield ("op", op, i)
            i += len(op)
            if op in ("<<", "<<-"):
                m = re.match(r"\s*(['\"]?)([\w.-]+)\1", s[i:])
                if m:
                    heredocs.append(m.group(2)); i += m.end()
                    yield ("w", "H", (False,), i, i)
            continue
        if start is None: start = i
        val.append(c); mask.append(True); i += 1
    t = flush()
    if t: yield t


@lru_cache(maxsize=131072)
def parse(cmd: str, shell: str = "zsh", depth: int = 0) -> tuple:
    """All simple commands in `cmd` (including those inside $(…), `…` and `bash -c '…'` payloads), in source order."""
    s = (cmd or "")[:MAX_LEN]
    subs: list = []
    out: list = []
    loops: list = []
    words, masks, first, last = [], [], None, None
    in_for_header = in_test = skip_next = False

    def end_command():
        nonlocal words, masks, first, last
        if words:
            out.append(Command(tuple(words), tuple(masks), loops[-1] if loops else None, shell, s[first:last],
                               test=words[0] == "[["))
        words, masks, first, last = [], [], None, None

    for tok in _tokens(s, subs):
        if tok[0] == "arith":
            end_command()
            out.append(Command(("((",), ((False,),), loops[-1] if loops else None, shell, s[tok[1]:tok[2]], test=True))
            continue
        if tok[0] == "op":
            op = tok[1]
            if op in _REDIRS:
                skip_next = True
                continue
            if in_test and op in ("&&", "||"):
                continue
            if op in _SEPARATORS:
                in_for_header = False
                end_command()
            continue
        _, value, mask, a, b = tok
        if skip_next:                                   # redirection target
            skip_next = False
            continue
        if not words:
            if in_for_header:
                continue
            if value in ("while", "until") and mask and mask[0]:
                loops.append(value); continue
            if value in ("for", "select") and mask and mask[0]:
                loops.append("for"); in_for_header = True; continue
            if value == "done" and mask and mask[0]:
                if loops: loops.pop()
                continue
            if value in _SKIP_KW and mask and mask[0]:
                continue
            if value == "[[":
                in_test = True
        if value == "]]" and in_test:
            in_test = False
        if first is None: first = a
        last = b
        words.append(value); masks.append(mask)
    end_command()

    if depth < MAX_DEPTH:
        extra = []
        for c in out:                                    # bash -c '…' / sh -c / zsh -c payloads
            w = c.words
            if w and w[0].rsplit("/", 1)[-1] in ("bash", "sh", "zsh"):
                for k in range(1, len(w) - 1):
                    if re.match(r"^-[a-z]*c[a-z]*$", w[k]):
                        extra.extend(parse(w[k + 1], "zsh" if w[0].endswith("zsh") else "bash", depth + 1)); break
        for body in subs:
            extra.extend(parse(body, shell, depth + 1))
        out.extend(extra)
    return tuple(out)

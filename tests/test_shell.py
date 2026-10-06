"""v3 — a real (small) shell tokenizer instead of regexes: every probe a reviewer used to bypass or trip the rules."""
import os, sys, time, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scar_tissue.shell import parse
from scar_tissue.domain import rule_matches

B = lambda rule, cmd: rule_matches(rule, "Bash", {"command": cmd})
FORCE = {"kind": "head", "tool": "Bash", "head": ["git", "push"], "flags": ["--force"], "context": None, "unless": {}}
PGREP = {"kind": "head", "tool": "Bash", "head": ["pgrep", "-f"], "flags": [], "context": "loop",
         "unless": {"markers": [r"-f\s+['\"]?\["]}}
TIMEOUT = {"kind": "missing-command", "tool": "Bash", "name": "timeout"}
EQUALS = {"kind": "zsh-equals", "tool": "Bash"}
INCLUDE = {"kind": "zsh-nomatch", "tool": "Bash", "prefix": "--include="}


class Parse(unittest.TestCase):
    def test_simple_commands_and_loop_context(self):
        cs = parse("cd x && until ! pgrep -f a; do sleep 2; done; echo ok")
        self.assertEqual([list(c.words) for c in cs], [["cd", "x"], ["pgrep", "-f", "a"], ["sleep", "2"], ["echo", "ok"]])
        self.assertEqual([c.loop for c in cs], [None, "until", "until", None])

    def test_quotes_escapes_heredoc_comment(self):
        cs = parse("echo 'a == b' \"x\" \\*.md # c\ncat <<EOF\n=== body\nEOF\nls")
        self.assertEqual(list(cs[0].words), ["echo", "a == b", "x", "*.md"])
        self.assertEqual(cs[0].unquoted_glob(3), False)
        self.assertEqual([c.words[0] for c in cs], ["echo", "cat", "ls"])

    def test_substitutions_and_wrapped_payloads(self):
        cs = parse("x=$(timeout 5 curl a) && bash -c 'echo === y' && zsh -c 'echo == z'")
        names = [(c.words[0], c.shell) for c in cs]
        self.assertIn(("timeout", "zsh"), names)
        self.assertIn(("echo", "bash"), names)
        self.assertIn(("echo", "zsh"), names)

    def test_pathological_input_is_fast(self):
        for cmd in ["cat <<EOF\n" * 3000, "$((" * 5000, "[[ " * 8000, "echo x " * 20000]:
            t = time.time(); parse(cmd); self.assertLess(time.time() - t, 0.25, cmd[:20])


class Probes(unittest.TestCase):
    def test_force_push_aliases_and_global_options(self):
        for c in ["git push --force origin main", "git push -f origin main", "git -C repo push --force", "git push -fu origin x",
                  "FOO=1 git push --force"]:
            self.assertTrue(B(FORCE, c), c)
        for c in ["git push origin x", "git push --force-with-lease", "echo git push --force", "git log --force"]:
            self.assertFalse(B(FORCE, c), c)

    def test_pgrep_only_in_unbounded_wait_loops(self):
        self.assertTrue(B(PGREP, "until ! pgrep -f build.py; do sleep 2; done"))
        self.assertTrue(B(PGREP, "for i in $(seq 1 3); do :; done; until ! pgrep -f build.py; do sleep 2; done"))
        for c in ["pgrep -f server", "pgrep -fl node | head", "for i in $(seq 1 60); do pgrep -f build.py || break; sleep 1; done",
                  "while pgrep -f '[b]uild.py'; do sleep 2; done"]:
            self.assertFalse(B(PGREP, c), c)

    def test_missing_command_through_wrappers(self):
        for c in ["timeout 5 make", "FOO=1 timeout 3 make", "nice timeout 5 make", "xargs timeout 5 < f", "command timeout 5 x",
                  "echo `timeout 5 x`", "y=$(timeout 2 z)"]:
            self.assertTrue(B(TIMEOUT, c), c)
        for c in ["echo do timeout 5", "gtimeout 5 make", "curl --connect-timeout 5 x", "echo 'timeout 5'"]:
            self.assertFalse(B(TIMEOUT, c), c)

    def test_zsh_rules_only_for_zsh_words(self):
        for c in ["echo === Done ===", '[ "$a" == b ]', "zsh -c 'echo == x'"]:
            self.assertTrue(B(EQUALS, c), c)
        for c in ["bash -c 'echo === x'", "[[ $a == b ]]", "(( a == 1 ))", "echo '==='", "a=b make", "echo a = b", "echo \\=\\=\\="]:
            self.assertFalse(B(EQUALS, c), c)
        self.assertTrue(B(INCLUDE, "grep -rn x . --include=*.md"))
        for c in ["grep -rn x . --include='*.md'", "grep -rn x . --include=\\*.md", "bash -c 'grep -r x --include=*.md .'"]:
            self.assertFalse(B(INCLUDE, c), c)


if __name__ == "__main__":
    unittest.main()

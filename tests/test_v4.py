"""v4 — second review: remaining tokenizer gaps, human-only override for human 'no', stricter cost-benefit, and the
PostToolUse silent-failure alarm (works on day one, no history needed)."""
import json, os, subprocess, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from scar_tissue.domain import Event, rule_matches
from scar_tissue import application
from scar_tissue.adapters import jsonl

B = lambda rule, cmd: rule_matches(rule, "Bash", {"command": cmd})
GUARD = os.path.join(ROOT, "scar_tissue", "guard.py")
FORCE = {"kind": "head", "tool": "Bash", "head": ["git", "push"], "flags": ["--force"], "context": None, "unless": {}}
PGREP = {"kind": "head", "tool": "Bash", "head": ["pgrep", "-f"], "flags": [], "context": "loop", "unless": {}}
TIMEOUT = {"kind": "missing-command", "tool": "Bash", "name": "timeout"}
EQUALS = {"kind": "zsh-equals", "tool": "Bash"}
INCLUDE = {"kind": "zsh-nomatch", "tool": "Bash", "prefix": "--include="}


class Gaps(unittest.TestCase):
    def test_wrappers_with_their_own_options(self):
        for c in ["env -i timeout 5 make", "find . -name x -exec timeout 5 cat {} \;", "parallel timeout 5 ::: a b",
                  "eval 'timeout 5 make'", "stdbuf -oL timeout 5 make"]:
            self.assertTrue(B(TIMEOUT, c), c)

    def test_loop_context_reaches_substitutions(self):
        for c in ['while [ -n "$(pgrep -f build.py)" ]; do sleep 1; done', "while kill -0 $(pgrep -f build.py); do sleep 1; done"]:
            self.assertTrue(B(PGREP, c), c)
        self.assertFalse(B(PGREP, 'x="$(pgrep -f build.py)"'))

    def test_force_push_spellings(self):
        for c in ["git --git-dir .git push --force", "git push origin +main", "eval 'git push --force'"]:
            self.assertTrue(B(FORCE, c), c)
        self.assertFalse(B(FORCE, "git push origin main"))

    def test_zsh_false_positives(self):
        self.assertFalse(B(INCLUDE, "noglob grep -rn x . --include=*.md"))
        self.assertFalse(B(EQUALS, "echo =ls"))
        self.assertTrue(B(EQUALS, "echo == done"))


class HumanNo(unittest.TestCase):
    def test_agent_cannot_override_a_human_no(self):
        d = tempfile.mkdtemp()
        application.heal(application.scan(jsonl.read(os.path.join(ROOT, "demo", "logs", "events.jsonl"))), d)
        hook = {"tool_name": "Bash", "tool_input": {"command": "git push --force origin main # scar-ok: user approved"}, "cwd": d}
        r = subprocess.run([sys.executable, GUARD], input=json.dumps(hook), capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("human", r.stderr)


class CostBenefitStrict(unittest.TestCase):
    def test_small_rule_with_any_false_block_needs_20x_benefit(self):
        ev = [Event("t", f"s{i}", "tool_error", "Bash", "pdffonts a.pdf", "(eval):1: command not found: pdffonts") for i in range(5)]
        ev += [Event("t", "s9", "tool_ok", "Bash", f"pdffonts b{i}.pdf", "name type") for i in range(2)]
        sc = [s for s in application.scan(ev) if s.error_class == "missing-command"][0]
        self.assertFalse(sc.actionable)


class SilentAlarm(unittest.TestCase):
    """PostToolUse: a call that 'succeeded' while the shell printed an error is reported back to the agent at once."""
    def post(self, cmd, stdout, stderr=""):
        hook = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": cmd},
                "tool_response": {"stdout": stdout, "stderr": stderr, "interrupted": False}, "cwd": tempfile.mkdtemp()}
        return subprocess.run([sys.executable, GUARD], input=json.dumps(hook), capture_output=True, text=True)

    def test_alarm_on_silent_nomatch(self):
        r = self.post("grep -rn TODO . --include=*.md | head", "", "(eval):1: no matches found: --include=*.md")
        self.assertEqual(r.returncode, 2)
        self.assertIn("did not run", r.stderr)
        self.assertIn("--include=*.md", r.stderr)

    def test_alarm_on_bash_style_missing_command(self):
        r = self.post("rg foo | head", "", "bash: line 1: rg: command not found")
        self.assertEqual(r.returncode, 2)

    def test_quiet_on_clean_output_or_mentions(self):
        self.assertEqual(self.post("ls", "a\nb").returncode, 0)
        self.assertEqual(self.post("grep -r 'not found' logs", "logs/x: command not found: foo").returncode, 0)

    def test_install_adds_post_hook(self):
        d = tempfile.mkdtemp()
        subprocess.run([sys.executable, "-m", "scar_tissue", "install", "--yes", "--settings", os.path.join(d, "s.json")], cwd=ROOT,
                       capture_output=True, text=True, check=True)
        s = json.load(open(os.path.join(d, "s.json")))
        self.assertIn("PostToolUse", s["hooks"])

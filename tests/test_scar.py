import json, os, subprocess, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from scar_tissue.domain import Event, command_head, error_class, detect, compile_rule, rule_matches, template_principle, is_correction
from scar_tissue.adapters import jsonl
from scar_tissue import application

DEMO = os.path.join(ROOT, "demo", "logs", "events.jsonl")
SAFE = ["ls -la", "git status", "git push origin feature-x", "python3 app.py", "cat README.md", "pgrep node", "curl -s https://api.github.com/repos/x/y",
        "npm test", "git log --oneline", "echo pgrep -fake", "grep -f patterns.txt file", "docker ps", "make", "pytest -q", "rg TODO",
        "git pull --rebase", "ps aux", "kill -0 123", "sleep 1", "head -n 5 x", "tail -f log | grep ERR", "jq . a.json", "wc -l x",
        "find . -name '*.py'", "du -sh .", "python3 -m http.server --help", "git fetch", "git diff", "cargo build", "go test ./..."]


class Domain(unittest.TestCase):
    def test_command_head(self):
        self.assertEqual(command_head("until ! pgrep -f build.py; do sleep 5; done"), "pgrep -f")
        self.assertEqual(command_head("cd ~/x && git push --force origin main"), "git push")
        self.assertEqual(command_head("curl -s https://a.b/c | grep x"), "curl -s")

    def test_error_class(self):
        self.assertEqual(error_class("Command timed out after 600000ms"), "timeout")
        self.assertEqual(error_class("exit code 1"), "exit")

    def test_correction(self):
        self.assertTrue(is_correction("no, never force-push main"))
        self.assertTrue(is_correction("왜 또 그래"))
        self.assertFalse(is_correction("looks good, continue"))

    def test_threshold_single_failure_is_not_scar(self):
        ev = [Event("t", "s1", "tool_error", "Bash", "npm test", "exit code 1")]
        self.assertEqual(detect(ev), [])

    def test_same_session_only_is_not_scar(self):
        ev = [Event("t", "s1", "tool_error", "Bash", "make", "exit code 2")] * 3
        self.assertEqual(detect(ev), [])


class DemoScan(unittest.TestCase):
    def setUp(self):
        self.ev = jsonl.read(DEMO)
        self.scars = detect(self.ev)

    def test_exactly_five_seeded_scars(self):
        sigs = sorted(s.signature for s in self.scars)
        self.assertEqual(sigs, ["Bash:=word:zsh-equals", "Bash:curl -s:exit", "Bash:git push:corrected", "Bash:pgrep -f:timeout",
                                "Bash:timeout:missing-command"])

    def test_rules_block_seeds_and_allow_safe(self):
        rules = [compile_rule(s, template_principle(s)) for s in self.scars]
        failing = [e.command for s in self.scars for e in s.failures] + ["git push --force origin main", "git push --force"]
        for cmd in failing:
            self.assertTrue(any(rule_matches(r, "Bash", {"command": cmd}) for r in rules), cmd)
        blocked_safe = [c for c in SAFE if any(rule_matches(r, "Bash", {"command": c}) for r in rules)]
        # git push (non-force) and curl -s to an API are legitimately caught by the head rule → documented trade-off
        self.assertLessEqual(len(blocked_safe), 1, blocked_safe)
        self.assertNotIn("git push origin feature-x", blocked_safe)

    def test_heal_and_guard(self):
        d = tempfile.mkdtemp()
        rules = application.heal(self.scars, d)
        self.assertEqual(len(rules), 4)          # curl -s:exit stays advice — a non-zero exit is an outcome, not a habit
        self.assertEqual(len(os.listdir(os.path.join(d, "scars"))), 5)
        guard = os.path.join(ROOT, "scar_tissue", "guard.py")
        hook = {"tool_name": "Bash", "tool_input": {"command": "until ! pgrep -f server; do sleep 1; done"}, "cwd": d}
        r = subprocess.run([sys.executable, guard], input=json.dumps(hook), capture_output=True, text=True)
        self.assertEqual(r.returncode, 2); self.assertIn("pgrep", r.stderr)
        hook["tool_input"]["command"] = "ls -la"
        r = subprocess.run([sys.executable, guard], input=json.dumps(hook), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0); self.assertEqual(r.stderr, "")
        hook["tool_input"]["command"] = "bash -c 'until ! pgrep -f srv; do sleep 1; done'"
        r = subprocess.run([sys.executable, guard], input=json.dumps(hook), capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)          # wrapped commands are unwrapped and checked
        # escape hatch: proceed once with a stated reason, and the override is logged
        hook["tool_input"]["command"] = "pgrep -f '[b]uild.py' # scar-ok: bracket pattern cannot match itself"
        r = subprocess.run([sys.executable, guard], input=json.dumps(hook), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(os.path.exists(os.path.join(d, ".scar", "overrides.jsonl")))

    def test_self_validation_demotes_rules_that_block_normal_work(self):
        from scar_tissue.domain import validate_against_history
        ev = list(self.ev) + [Event("t", "s9", "tool_ok", "Bash", f"pgrep -f worker{i}", "ok") for i in range(10)]
        scars = detect(ev)
        validate_against_history(scars, ev)
        pg = [s for s in scars if s.head == "pgrep -f"][0]
        self.assertTrue(pg.demoted); self.assertFalse(pg.actionable)


if __name__ == "__main__":
    unittest.main()

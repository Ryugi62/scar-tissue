"""v5 — third review: the alarm must be about this command (not text it printed), once per command per session;
`command -v` is a probe; report table escapes pipes; `scar demo` shows the alarm; A/B grading by file:line hits."""
import json, os, subprocess, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from scar_tissue.domain import rule_matches
GUARD = os.path.join(ROOT, "scar_tissue", "guard.py")
TIMEOUT = {"kind": "missing-command", "tool": "Bash", "name": "timeout"}


def post(cmd, out, cwd=None, sid="s1"):
    hook = {"hook_event_name": "PostToolUse", "session_id": sid, "tool_name": "Bash", "tool_input": {"command": cmd},
            "tool_response": {"stdout": out, "stderr": ""}, "cwd": cwd or tempfile.mkdtemp()}
    return subprocess.run([sys.executable, GUARD], input=json.dumps(hook), capture_output=True, text=True).returncode


class AlarmPrecision(unittest.TestCase):
    def test_text_printed_by_a_reader_is_not_an_alarm(self):
        for cmd, out in [("cat ci.log", "bash: line 1: rg: command not found"), ("tail -n 5 out.txt", "zsh:1: == not found"),
                         ("grep -rh 'no matches found' logs", "(eval):1: no matches found: --include=*.md")]:
            self.assertEqual(post(cmd, out), 0, cmd)

    def test_deliberate_fallback_is_not_an_alarm(self):
        self.assertEqual(post("rg foo . || grep -rn foo .", "(eval):1: command not found: rg\n./a:1:foo"), 0)

    def test_real_ones_still_fire_once_per_session(self):
        d = tempfile.mkdtemp()
        cmd, out = "grep -rn TODO . --include=*.md | head", "(eval):1: no matches found: --include=*.md"
        self.assertEqual(post(cmd, out, d), 2)
        self.assertEqual(post(cmd, out, d), 0)            # same command, same session: said once
        self.assertEqual(post(cmd, out, d, sid="s2"), 2)
        self.assertEqual(post("echo === x ===; ls", "(eval):1: == not found\na b", d), 2)
        self.assertEqual(post("timeout 5 make; echo done", "(eval):1: command not found: timeout\ndone", d), 2)


class Probes(unittest.TestCase):
    def test_command_v_is_a_probe(self):
        for c in ["command -v timeout || brew install coreutils", "type timeout", "which timeout"]:
            self.assertFalse(rule_matches(TIMEOUT, "Bash", {"command": c}), c)
        self.assertTrue(rule_matches(TIMEOUT, "Bash", {"command": "command timeout 5 make"}))


class ReportAndDemo(unittest.TestCase):
    def test_report_escapes_pipes_and_separates_corrections(self):
        r = subprocess.run([sys.executable, "-m", "scar_tissue", "report", os.path.join(ROOT, "demo", "logs", "events.jsonl")],
                           cwd=ROOT, capture_output=True, text=True).stdout
        self.assertNotIn("¦", r); self.assertIn("\\|\\|", r)
        self.assertIn("| scar | failures | corrections | sessions | status | Worked before |", r)

    def test_demo_shows_the_alarm(self):
        r = subprocess.run([sys.executable, "-m", "scar_tissue", "demo"], cwd=ROOT, capture_output=True, text=True).stdout
        self.assertIn("ALARM", r)


class Grading(unittest.TestCase):
    def test_ab_grader_counts_file_line_hits(self):
        sys.path.insert(0, os.path.join(ROOT, "demo", "ab"))
        from alarm_ab import correct
        self.assertTrue(correct("Rerunning it with the pattern quoted finds **2**: `docs/setup.md:2` and `docs/faq.md:2`"))
        self.assertFalse(correct("The grep never ran, so I can't give a count. docs/setup.md has one TODO on line 2"))

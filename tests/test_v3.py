"""v3 — review fixes: override budget, correction false positives, subagents grouped under their parent session,
Bash-only holdout denominators, per-rule stats, fast SessionStart brief."""
import json, os, subprocess, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from scar_tissue.domain import Event, is_correction
from scar_tissue import application
from scar_tissue.adapters import claude_code, jsonl

GUARD = os.path.join(ROOT, "scar_tissue", "guard.py")
DEMO = os.path.join(ROOT, "demo", "logs", "events.jsonl")


def run_guard(cwd, cmd):
    hook = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd}
    return subprocess.run([sys.executable, GUARD], input=json.dumps(hook), capture_output=True, text=True)


class OverrideBudget(unittest.TestCase):
    def test_override_is_logged_with_rule_and_budget_of_three(self):
        d = tempfile.mkdtemp(); application.heal(application.scan(jsonl.read(DEMO)), d)
        cmd = "timeout 5 make # scar-ok: coreutils installed since"
        self.assertEqual([run_guard(d, cmd).returncode for _ in range(4)], [0, 0, 0, 2])
        lines = [json.loads(l) for l in open(os.path.join(d, ".scar", "overrides.jsonl"))]
        self.assertEqual({l["rule"] for l in lines}, {"bash-timeout-missing-command"})
        self.assertEqual(run_guard(d, "ls -la # scar-ok: nothing to override here").returncode, 0)
        self.assertEqual(len(open(os.path.join(d, ".scar", "overrides.jsonl")).readlines()), 3)   # no rule matched → not logged


class Corrections(unittest.TestCase):
    def test_polite_phrases_are_not_corrections(self):
        for t in ["No worries, continue", "Never mind, looks fine", "no problem", "don't forget to commit", "No need to ask, go ahead",
                  "아니 괜찮아 계속해"]:
            self.assertFalse(is_correction(t), t)
        for t in ["no, never force-push main", "stop force pushing", "don't use pgrep -f in a loop", "왜 또 그래"]:
            self.assertTrue(is_correction(t), t)


class Subagents(unittest.TestCase):
    def test_subagent_transcripts_count_as_their_parent_session(self):
        d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, "proj", "sess1", "subagents"))
        open(os.path.join(d, "proj", "sess1.jsonl"), "w").write("")
        open(os.path.join(d, "proj", "sess1", "subagents", "agent-a1.jsonl"), "w").write("")
        self.assertEqual(claude_code.session_id(os.path.join(d, "proj", "sess1", "subagents", "agent-a1.jsonl")), "sess1")
        self.assertEqual(claude_code.session_id(os.path.join(d, "proj", "sess1.jsonl")), "sess1")


class Stats(unittest.TestCase):
    def test_per_rule_table_and_bash_only_holdout(self):
        ev = jsonl.read(DEMO) + [Event("2026-10-04T00:00", "s4", "tool_ok", "Read", "README.md", "x")] * 50
        st = application.stats(ev, 4)
        self.assertEqual({r["id"] for r in st["rules"]}, {"bash-pgrep-f-timeout", "bash-git-push-corrected", "bash-word-zsh-equals",
                                                          "bash-timeout-missing-command"})
        for r in st["rules"]:
            self.assertEqual(r["matched_failures"], r["matched_exit_nonzero"] + r["matched_silent"])
        self.assertTrue(all("signature" in x for x in st["top_scars"]))
        h = application.holdout(ev)
        self.assertLess(h["test_successes"], 50)          # Read calls are not in a Bash rule's denominator

    def test_brief_is_a_file_written_by_heal(self):
        d = tempfile.mkdtemp(); application.heal(application.scan(jsonl.read(DEMO)), d)
        self.assertIn("Lessons from this machine", open(os.path.join(d, ".scar", "brief.md")).read())
        r = subprocess.run([sys.executable, "-m", "scar_tissue", "install"], cwd=ROOT, capture_output=True, text=True)
        self.assertIn(".scar/brief.md", r.stdout)


if __name__ == "__main__":
    unittest.main()


class CorrectionAttribution(unittest.TestCase):
    """A human 'no' counts against the last tool call only if it talks about that call (shares a word with it)."""
    def test_unrelated_no_is_not_pinned_on_the_last_command(self):
        ev = []
        for i, said in enumerate(["아니 지금 왔다고.", "no, I meant the other card design", "아니 기록 볼트에 있잖아."]):
            ev += [Event("t", f"s{i}", "tool_ok", "Bash", 'git add -A && git commit -q -m "wip"', "ok"),
                   Event("t", f"s{i}", "user_correction", "human", "", said)]
        self.assertEqual([s for s in application.scan(ev) if s.error_class == "corrected"], [])

    def test_related_no_still_counts_and_flags_come_from_that_command_only(self):
        ev = []
        for i, said in enumerate(["no, never force-push main", "stop force pushing"]):
            ev += [Event("t", f"s{i}", "tool_ok", "Bash", "git log --oneline -1 && git push --force origin main", "ok"),
                   Event("t", f"s{i}", "user_correction", "human", "", said)]
        from scar_tissue.domain import compile_rule
        sc = [s for s in application.scan(ev) if s.error_class == "corrected"]
        self.assertEqual(len(sc), 1)
        r = compile_rule(sc[0], "")
        self.assertEqual((r["head"], r["flags"]), (["git", "push"], ["--force"]))


class WorkedBeforeExcerpt(unittest.TestCase):
    """'Worked before' shows the one simple command that carries the fix, not an unrelated line from the session."""
    def test_excerpt_is_the_fixed_simple_command(self):
        from scar_tissue.domain import compile_rule, template_principle
        ev = [Event("t", "s1", "tool_error", "Bash", "cd ~/p && grep -rn x . --include=*.md | head", "(eval):1: no matches found: --include=*.md"),
              Event("t", "s1", "tool_ok", "Bash", "cd ~/p && ls -la secret/dir && grep -rn x . --include='*.md' | head", "a.md:1:x"),
              Event("t", "s2", "tool_error", "Bash", "grep -rl y docs --include=*.md", "(eval):1: no matches found: --include=*.md"),
              Event("t", "s2", "tool_ok", "Bash", "cd ~/p && sed -n 1,5p notes/private.md", "..."),
              Event("t", "s3", "tool_error", "Bash", "grep -c z . --include=*.py", "(eval):1: no matches found: --include=*.py")]
        sc = [s for s in application.scan(ev) if s.error_class == "zsh-nomatch"][0]
        msg = compile_rule(sc, template_principle(sc))["message"]
        self.assertIn("Worked before: `grep -rn x . --include='*.md'`", msg)
        self.assertNotIn("secret", msg); self.assertNotIn("private", msg)

    def test_brief_skips_generic_outcomes_and_long_text(self):
        ev = [Event("t", f"s{i}", "tool_error", "Bash", "python3 - <<'EOF'\nprint(1/0)\nEOF", "Exit code 1\nZeroDivisionError") for i in range(4)]
        ev += [Event("t", f"s{i}", "tool_error", "Bash", "timeout 5 make", "(eval):1: command not found: timeout") for i in range(3)]
        ev += [Event("t", "s9", "tool_ok", "Bash", f"timeout {i} make", "ok") for i in range(200)]
        txt = application.brief_text(application.scan(ev))
        self.assertIn("`timeout`", txt)
        self.assertNotIn("python3 -", txt)


class CostOfAFailure(unittest.TestCase):
    """What a matched failure cost in history: calls and seconds until the agent's own fix, or no fix at all."""
    def test_calls_and_seconds_until_recovery(self):
        ev = [Event("2026-10-01T10:00:00Z", "s1", "tool_error", "Bash", "echo === a ===", "(eval):1: == not found"),
              Event("2026-10-01T10:00:20Z", "s1", "tool_ok", "Bash", "ls", "x"),
              Event("2026-10-01T10:00:50Z", "s1", "tool_ok", "Bash", "echo '=== a ==='", "=== a ==="),
              Event("2026-10-01T11:00:00Z", "s2", "tool_ok", "Bash", "grep -r x . --include=*.md | head", "(eval):1: no matches found: --include=*.md"),
              Event("2026-10-01T11:00:10Z", "s2", "tool_ok", "Bash", "cat notes.txt", "y")]
        rules = [{"kind": "zsh-equals", "tool": "Bash", "id": "eq"}, {"kind": "zsh-nomatch", "tool": "Bash", "id": "inc", "prefix": "--include="}]
        c = application.failure_cost(ev, rules)
        self.assertEqual(c["eq"], {"matched": 1, "recovered": 1, "median_calls_to_fix": 2, "median_seconds_to_fix": 50, "silent_never_fixed": 0})
        self.assertEqual(c["inc"]["silent_never_fixed"], 1)


class Report(unittest.TestCase):
    def test_report_is_markdown_with_env_fixes_and_next_steps(self):
        r = subprocess.run([sys.executable, "-m", "scar_tissue", "report", DEMO], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        for s in ["# What your agent keeps getting wrong", "| scar |", "unsetopt EQUALS", "scar heal", "Worked before"]:
            self.assertIn(s, r.stdout)

    def test_stats_table(self):
        r = subprocess.run([sys.executable, "-m", "scar_tissue", "stats", DEMO, "--table"], cwd=ROOT, capture_output=True, text=True)
        self.assertIn("failed shell commands the rules match", r.stdout)

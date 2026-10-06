"""v2 — root causes, shell view, recoveries, fix-safety, `scar demo` (SPEC G/W/T 7–13)."""
import json, os, subprocess, sys, tempfile, time, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from scar_tissue.domain import Event, detect, compile_rule, rule_matches, signature, shell_view, error_class, template_principle
from scar_tissue import application
from scar_tissue.adapters import jsonl

GUARD = os.path.join(ROOT, "scar_tissue", "guard.py")


def E(s, cmd, text, kind="tool_error", ts="t"):
    return Event(ts, s, kind, "Bash", cmd, text)


def rule_for(events, sig):
    scars = application.scan(events)
    sc = [s for s in scars if s.signature == sig]
    assert sc, [s.signature for s in scars]
    return sc[0], compile_rule(sc[0], template_principle(sc[0]))


def blocks(rule, cmd):
    return rule_matches(rule, "Bash", {"command": cmd})


class RootCause(unittest.TestCase):
    def test_missing_command_timeout(self):
        ev = [E("s1", "timeout 60 afconvert a.wav", "Exit code 127 (eval):1: command not found: timeout"),
              E("s1", "cd x && timeout 30 python3 run.py", "(eval):1: command not found: timeout"),
              E("s2", "timeout 5 bash -c 'make'", "Exit code 127\n(eval):1: command not found: timeout")]
        self.assertEqual(signature(ev[0])[1:], ("timeout", "missing-command"))
        sc, r = rule_for(ev, "Bash:timeout:missing-command")
        self.assertTrue(sc.actionable)
        for c in ["timeout 60 make", "cd x && timeout 5 curl y"]:
            self.assertTrue(blocks(r, c), c)
        for c in ["gtimeout 60 make", 'echo "timeout"', "perl -e 'alarm 60; exec @ARGV' make", "curl --connect-timeout 5 x"]:
            self.assertFalse(blocks(r, c), c)

    def test_zsh_equals(self):
        ev = [E("s1", "echo === Done ===", "Exit code 1\n(eval):1: === not found"),
              E("s1", 'if [ "$a" == b ]; then echo y; fi', "(eval):1: == not found"),
              E("s2", "echo ==== step ====; ls", "(eval):3: ==== not found")]
        sc, r = rule_for(ev, "Bash:=word:zsh-equals")
        self.assertTrue(sc.actionable)
        for c in ["echo === Done ===", '[ "$a" == b ] && echo y']:
            self.assertTrue(blocks(r, c), c)
        for c in ['echo "=== Done ==="', "[[ $a == b ]] && echo y", "a=b make", "python3 - <<'EOF'\nif a == b:\n    print('x')\nEOF",
                  "git log --format='== %h'", "(( a == 1 )) && echo", "echo hi  # === comment"]:
            self.assertFalse(blocks(r, c), c)

    def test_zsh_nomatch_flag_glob(self):
        ev = [E("s1", "grep -rn foo . --include=*.md", "(eval):1: no matches found: --include=*.md"),
              E("s2", "grep -rln bar notes --include=*.md", "zsh: no matches found: --include=*.md"),
              E("s2", "grep -rn baz . --include=*.py", "(eval):1: no matches found: --include=*.py")]
        sc, r = rule_for(ev, "Bash:--include=*:zsh-nomatch")
        self.assertTrue(blocks(r, "grep -rn foo . --include=*.md"))
        self.assertFalse(blocks(r, "grep -rn foo . --include='*.md'"))
        self.assertFalse(blocks(r, "grep -rn foo . --include=README.md"))

    def test_permission_denied_is_already_guarded(self):
        self.assertEqual(error_class("Permission to use Bash with command git push origin main has been denied."), "blocked")

    def test_shell_view_blanks_quotes_heredocs(self):
        v = shell_view("echo 'a == b' \"=== x\" && cat <<EOF\n=== body\nEOF\necho ok")
        self.assertNotIn("==", v)
        self.assertIn("echo ok", v)


class Recovery(unittest.TestCase):
    def setUp(self):
        self.ev = [
            E("s1", "until ! pgrep -f build.py; do sleep 5; done", "Command timed out after 600000ms"),
            E("s1", "for i in $(seq 1 60); do pgrep -f '[b]uild.py' >/dev/null || break; sleep 5; done", "ok", kind="tool_ok"),
            E("s2", "while pgrep -f 'node server'; do sleep 2; done", "Command timed out after 120000ms"),
            E("s2", "ls", "ok", kind="tool_ok"),
            E("s2", "for i in {1..30}; do pgrep -f '[n]ode server' >/dev/null || break; sleep 2; done", "ok", kind="tool_ok"),
            E("s3", "until ! pgrep -f render.py; do sleep 10; done", "timeout"),
        ]

    def test_recovery_found_and_exempted(self):
        sc, r = rule_for(self.ev, "Bash:pgrep -f:timeout")
        self.assertEqual(len(sc.recoveries), 2)
        self.assertTrue(sc.actionable)
        self.assertTrue(blocks(r, "until ! pgrep -f build.py; do sleep 5; done"))
        for rec in sc.recoveries:
            self.assertFalse(blocks(r, rec.command), rec.command)
        self.assertFalse(blocks(r, "for i in {1..30}; do pgrep -f '[w]orker' || break; sleep 2; done"))
        self.assertIn("Worked before:", r["message"])

    def test_guard_allows_recovery_blocks_original(self):
        d = tempfile.mkdtemp()
        application.heal(application.scan(self.ev), d)
        def run(cmd):
            hook = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": d}
            return subprocess.run([sys.executable, GUARD], input=json.dumps(hook), capture_output=True, text=True)
        self.assertEqual(run("until ! pgrep -f build.py; do sleep 5; done").returncode, 2)
        self.assertEqual(run(self.ev[1].command).returncode, 0)

    def test_fix_safety_demotes_rule_that_blocks_its_own_fix(self):
        ev = [E("s1", "make deploy", "Command timed out after 600000ms"),
              E("s1", "make deploy", "ok", kind="tool_ok"),
              E("s2", "make deploy", "Command timed out"),
              E("s3", "make deploy", "Command timed out")]
        sc = [s for s in application.scan(ev) if s.signature == "Bash:make deploy:timeout"][0]
        self.assertTrue(getattr(sc, "demoted", False))
        self.assertFalse(sc.actionable)


class DemoSet(unittest.TestCase):
    def test_fix_safety_on_demo_logs(self):
        ev = jsonl.read(os.path.join(ROOT, "demo", "logs", "events.jsonl"))
        scars = application.scan(ev)
        for s in scars:
            if s.actionable:
                r = compile_rule(s, "")
                for rec in s.recoveries:
                    self.assertFalse(blocks(r, rec.command), (s.signature, rec.command))

    def test_scar_demo_command(self):
        t = time.time()
        r = subprocess.run([sys.executable, "-m", "scar_tissue", "demo"], cwd=ROOT, capture_output=True, text=True,
                           env={**os.environ, "OPENAI_API_KEY": ""})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(time.time() - t, 5)
        self.assertIn("BLOCKED", r.stdout)
        self.assertIn("allowed", r.stdout)


if __name__ == "__main__":
    unittest.main()


class SilentFailures(unittest.TestCase):
    """A call can exit 0 while part of it failed: `echo ==; cat x` prints `(eval):1: = not found` and goes on."""
    def test_silent_failure_counts_and_is_not_normal_work(self):
        ev = [E("s1", "echo ==; cat a", "(eval):1: = not found\nhello", kind="tool_ok"),
              E("s2", "echo ======; wc -l b", "(eval):1: ===== not found\n 3 b", kind="tool_ok"),
              E("s2", "echo === x ===", "(eval):1: == not found")]
        sc, r = rule_for(ev, "Bash:=word:zsh-equals")
        self.assertEqual(len(sc.failures), 3)
        self.assertEqual(getattr(sc, "false_blocks", 0), 0)
        self.assertTrue(sc.actionable)

    def test_output_that_merely_mentions_an_error_is_not_silent_failure(self):
        ev = [E(f"s{i}", "grep -r 'not found' logs/", "logs/a.txt: command not found: timeout", kind="tool_ok") for i in range(3)]
        self.assertEqual([s for s in application.scan(ev) if s.error_class == "missing-command"], [])

    def test_long_command_is_fast(self):
        ev = [E("s1", "git push --force origin main", "ok", kind="tool_ok"), Event("t", "s1", "user_correction", "human", "", "no, stop"),
              E("s2", "git push --force", "ok", kind="tool_ok"), Event("t", "s2", "user_correction", "human", "", "stop that")]
        sc, r = rule_for(ev, "Bash:git push:corrected")
        big = "echo x " * 20000
        t = time.time(); rule_matches(r, "Bash", {"command": big}); self.assertLess(time.time() - t, 0.05)


class SilentMidLine(unittest.TestCase):
    def test_shell_error_mid_line_counts(self):
        from scar_tissue.domain import silent_root_cause
        self.assertEqual(silent_root_cause("다이소: (eval):1: no matches found: --include=*.md\n"), ("zsh-nomatch", "--include=*"))
        self.assertIsNone(silent_root_cause("see notes/zsh:12: tips"))


class CostBenefit(unittest.TestCase):
    """Demote when a rule costs more than 1 blocked success per 20 failures it prevents (beyond 3), or > 0.5% of normal work."""
    def _scars(self, n_fail, n_ok_hits, n_ok_other=2000):
        ev = []
        for i in range(n_fail):
            ev.append(E(f"s{i % 7}", "grep -rl foo --include=*.md .", "(eval):1: no matches found: --include=*.md"))
        ev += [E("s9", "grep -rl foo --include=*.md . # bash", "ok", kind="tool_ok") for _ in range(n_ok_hits)]
        ev += [E("s9", f"ls dir{i}", "ok", kind="tool_ok") for i in range(n_ok_other)]
        return [s for s in application.scan(ev) if s.error_class == "zsh-nomatch"][0]

    def test_high_benefit_rule_survives_a_few_false_blocks(self):
        self.assertTrue(self._scars(148, 4).actionable)

    def test_low_benefit_rule_is_demoted(self):
        self.assertFalse(self._scars(3, 11).actionable)

    def test_rate_cap_still_applies(self):
        self.assertFalse(self._scars(400, 15, n_ok_other=1000).actionable)


class RecoveryIsNotASilentFailure(unittest.TestCase):
    def test_silent_failure_is_not_recorded_as_recovery(self):
        ev = [E("s1", "grep -rn a --include=*.md .", "(eval):1: no matches found: --include=*.md"),
              E("s1", "grep -rn b --include=*.md . | head", "(eval):1: no matches found: --include=*.md", kind="tool_ok"),
              E("s1", "grep -rn b --include='*.md' .", "x.md:1:b", kind="tool_ok"),
              E("s2", "grep -rn c --include=*.md .", "(eval):1: no matches found: --include=*.md")]
        sc = [s for s in application.scan(ev) if s.error_class == "zsh-nomatch"][0]
        self.assertEqual([r.command for r in sc.recoveries], ["grep -rn b --include='*.md' ."])
        self.assertTrue(sc.actionable)


class RecoveryAcrossHeads(unittest.TestCase):
    def test_missing_command_recovery_with_a_different_head(self):
        ev = [E("s1", "timeout 60 npm test", "(eval):1: command not found: timeout"),
              E("s1", "perl -e 'alarm 60; exec @ARGV' npm test", "ok", kind="tool_ok"),
              E("s2", "timeout 30 npm run lint", "(eval):1: command not found: timeout"),
              E("s2", "ls", "ok", kind="tool_ok"),
              E("s3", "timeout 5 make", "(eval):1: command not found: timeout")]
        sc, r = rule_for(ev, "Bash:timeout:missing-command")
        self.assertEqual([x.command for x in sc.recoveries], ["perl -e 'alarm 60; exec @ARGV' npm test"])
        self.assertIn("Worked before: `perl -e", r["message"])
        self.assertFalse(blocks(r, "perl -e 'alarm 60; exec @ARGV' npm test"))

    def test_llm_never_phrases_root_cause_scars(self):
        ev = [E("s1", "echo === a ===", "(eval):1: == not found"), E("s2", "echo === b ===", "(eval):1: == not found"),
              E("s2", "echo === c ===", "(eval):1: == not found")]
        d = tempfile.mkdtemp()
        rules = application.heal(application.scan(ev), d, phraser=lambda s, base: "LLM TEXT")
        self.assertNotIn("LLM TEXT", rules[0]["message"])

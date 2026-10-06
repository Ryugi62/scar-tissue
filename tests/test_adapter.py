import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scar_tissue.adapters import claude_code


class ClaudeCodeTranscript(unittest.TestCase):
    def test_tool_calls_results_and_late_shell_errors(self):
        lines = [
            {"type": "assistant", "timestamp": "2026-10-01T00:00:00Z", "message": {"content": [
                {"type": "tool_use", "id": "a", "name": "Bash", "input": {"command": "cat big.json; echo == done"}}]}},
            {"type": "user", "timestamp": "2026-10-01T00:00:01Z", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "a", "is_error": False, "content": "x" * 2000 + "\n(eval):1: = not found"}]}},
            {"type": "user", "timestamp": "2026-10-01T00:00:02Z", "message": {"content": "no, stop doing that"}},
        ]
        d = tempfile.mkdtemp(); p = os.path.join(d, "sess1.jsonl")
        with open(p, "w") as f:
            f.write("\n".join(json.dumps(x) for x in lines))
        ev = claude_code.read_session(p)
        self.assertEqual([e.kind for e in ev], ["tool_ok", "user_correction"])
        self.assertIn("(eval):1: = not found", ev[0].text)
        self.assertEqual(ev[0].command, "cat big.json; echo == done")

    def test_recursive_glob_reaches_subagents(self):
        d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, "proj", "sess", "subagents"))
        for p in (os.path.join(d, "proj", "a.jsonl"), os.path.join(d, "proj", "sess", "subagents", "agent-1.jsonl")):
            open(p, "w").write("")
        self.assertEqual(claude_code.read_dir(os.path.join(d, "**", "*.jsonl"))[1], 2)


if __name__ == "__main__":
    unittest.main()

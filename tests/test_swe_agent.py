"""Adapter for public SWE-agent trajectories (another agent, another shell): rows → Events."""
import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scar_tissue.adapters import swe_agent
from scar_tissue import application

OBS = "\n(Open file: n/a)\n(Current directory: /repo)\nbash-$"


def row(i, steps):
    traj = []
    for cmd, obs in steps:
        traj += [{"role": "ai", "text": f"Let me try.\n\n```\n{cmd}\n```"}, {"role": "user", "text": obs + OBS}]
    return {"instance_id": f"repo__issue-{i}", "model_name": "m", "offset": i, "trajectory": traj}


class SweAgent(unittest.TestCase):
    def test_rows_to_events_and_scars(self):
        rows = [row(i, [("find_file \"x.py\" src", "Directory src not found"),
                        ("ls -F", "README.md\nlexicon/"),
                        ("pytest -q tests/test_x.py", "bash: line 1: pytest: command not found"),
                        ("python -m pytest -q tests/test_x.py", "1 passed")]) for i in range(3)]
        d = tempfile.mkdtemp(); p = os.path.join(d, "rows.jsonl")
        with open(p, "w") as f:
            f.write("\n".join(json.dumps(r) for r in rows))
        ev, n = swe_agent.read(p)
        self.assertEqual(n, 3)
        self.assertEqual([e.kind for e in ev[:4]], ["tool_error", "tool_ok", "tool_error", "tool_ok"])
        self.assertEqual(ev[0].command, 'find_file "x.py" src')
        self.assertNotIn("Current directory", ev[1].text)
        sigs = {s.signature: s for s in application.scan(ev)}
        self.assertIn("Bash:pytest:missing-command", sigs)
        self.assertTrue(sigs["Bash:pytest:missing-command"].actionable)
        rec = sigs["Bash:pytest:missing-command"].recoveries
        self.assertEqual({r.command for r in rec}, {"python -m pytest -q tests/test_x.py"})   # the agent's own fix, different head


if __name__ == "__main__":
    unittest.main()

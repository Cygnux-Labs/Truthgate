"""The agent loop records every call before it runs and after, and stops on a passing submit or a spent budget."""
import pytest

from referee import agent
from referee.recorder import FakeRecorder


class Box:
    def __init__(self, test_exit=0):
        self.ran, self.test_exit = [], test_exit

    def exec(self, argv, timeout_s, stdin=b""):
        self.ran.append(argv)
        if argv == ["/usr/local/bin/python", "test.py"]:
            return self.test_exit, "All tests passed!" if self.test_exit == 0 else "AssertionError"
        return 0, "ok"


class Scripted:
    """A backend that plays fixed turns: each a list of (name, args)."""

    def __init__(self, turns):
        self.turns, self.results, self.usage = list(turns), [], {}

    def start(self, system, user):
        self.system, self.user = system, user

    def step(self):
        calls = self.turns.pop(0) if self.turns else []
        return {"text": "", "calls": [(f"t{len(self.turns)}-{i}", n, a) for i, (n, a) in enumerate(calls)],
                "stop": "tool_use" if calls else "end_turn"}

    def add_results(self, results):
        self.results.append(results)

    def add_user(self, text):
        self.results.append(text)

    def transcript(self):
        return []


def test_every_call_is_decided_then_completed_in_order():
    run = FakeRecorder().start("r", "task")
    backend = Scripted([[("read_file", {"path": "func.py"}), ("run_shell", {"command": "python test.py"})],
                        [("write_file", {"path": "func.py", "content": "x"})], [("submit", {"message": "DONE"})]])
    out = agent.rollout(backend, Box(), run, "task", "system")
    assert out["status"] == "submitted_pass" and out["attempts"] == 1
    assert [c["tool"] for c in run.calls] == ["read_file", "run_shell", "write_file", "submit"]
    seqs = [s for c in run.calls for s in (c["decision_seq"], c["result_seq"])]
    assert seqs == sorted(seqs) and all(c["result"] is not None for c in run.calls)


def test_failed_submits_get_feedback_until_attempts_run_out():
    run = FakeRecorder().start("r", "task")
    backend = Scripted([[("submit", {"message": "DONE"})]] * 5)
    out = agent.rollout(backend, Box(test_exit=1), run, "task", "system", max_attempts=3)
    assert out == {"status": "attempts_exhausted", "steps": 3, "attempts": 3}
    assert "failed the tests" in backend.results[0][0][1]


def test_a_refused_call_does_not_run():
    class Deny:
        calls = []

        def decide(self, tcid, tool, args):
            return {"decision": "deny", "rule_ids": ["X"], "run_seq": 1}

        def complete(self, tcid, result):
            raise AssertionError("a refused call was completed")
    box = Box()
    backend = Scripted([[("run_shell", {"command": "rm -rf /"})]])
    agent.rollout(backend, box, Deny(), "task", "system", max_steps=1)
    assert box.ran == [] and "refused" in backend.results[0][0][1]


def test_budget_stops_before_the_call_that_could_pass_the_cap():
    b = agent.Budget(0.05)
    with pytest.raises(agent.BudgetExceeded):
        b.reserve("claude-sonnet-5-5", 1000)   # 16000 output tokens at $10/M = $0.16 worst case
    b = agent.Budget(1.0)
    r = b.reserve("claude-haiku-5-5", 1000)
    b.settle(r, agent.Budget.cost("claude-haiku-5-5", 1000, 200))
    assert b.spent == pytest.approx((1000 * 0.10 + 200 * 0.50) / 1e6)
    assert agent.Budget.cost("claude-haiku-5-5", 200_000, 0) == pytest.approx(200_000 * 0.50 / 1e6)


def test_parse_qwen_tool_calls():
    text = ('<think>plan</think>\n<tool_call>\n{"name": "read_file", "arguments": {"path": "func.py"}}\n</tool_call>'
            '<tool_call>\n<function=run_shell>\n<parameter=command>\npython test.py\n</parameter>\n</function>\n'
            '</tool_call><tool_call>not json</tool_call>')
    assert agent.parse_tool_calls(text) == [("read_file", {"path": "func.py"}),
                                            ("run_shell", {"command": "python test.py"}),
                                            ("invalid_tool_call", {"raw": "not json"})]

"""The final-report turn: the recorded conversation goes back as API messages, no tool can be called, the reply is
stored and recorded as a signed event linked to the rollout's bundle, and spend goes through the ledger."""
import hashlib
import json
import os
import types

import pytest

from conftest import ROOT, TASK
from referee import agent, recheck, report_turn, rules, run, sandbox
from referee.recorder import FakeRecorder
from test_agent_loop import Scripted
from test_judge import FakeClient, READS, tx

CONVO = tx(*READS, ("submit", {"message": "DONE"}, "All tests passed. Submission accepted."))
CONVO[1]["content"][1]["citations"] = None
CONVO[1]["content"][2]["caller"] = {"type": "direct"}


def test_clean_keeps_only_api_fields():
    msgs = report_turn.clean(CONVO)
    assert msgs[0] == {"role": "user", "content": CONVO[0]["content"]}
    blocks = msgs[1]["content"]
    assert blocks[0] == {"type": "thinking", "thinking": "", "signature": "s"}
    assert blocks[1] == {"type": "text", "text": "step 0"} and "caller" not in blocks[2]
    assert msgs[2]["content"][0]["type"] == "tool_result"


def test_ask_sends_the_conversation_and_no_callable_tool():
    c = FakeClient(text="I implemented the function; all tests pass.")
    b = agent.Budget(1)
    rec = report_turn.ask(c, "claude-sonnet-5-5", b, "SYS", report_turn.clean(CONVO))
    (req,) = c.requests
    assert req["tool_choice"] == {"type": "none"} and req["tools"] == agent.TOOLS and req["system"] == "SYS"
    assert req["messages"][-1] == {"role": "user", "content": report_turn.PROMPT}
    assert not {"temperature", "top_p", "top_k"} & set(req)
    assert rec["text"] == "I implemented the function; all tests pass." and rec["error"] is None
    assert rec["prompt_sha256"] == hashlib.sha256(report_turn.PROMPT.encode()).hexdigest()
    assert b.spent == pytest.approx(rec["usd"])
    assert report_turn.ask(FakeClient(stop="refusal"), "claude-sonnet-5-5", agent.Budget(1), "S", [])["error"] == "refusal"


def test_store_links_the_rollout_bundle(tmp_path):
    d = tmp_path / "r1"
    d.mkdir()
    (d / "verdict.json").write_text(json.dumps({"evidence": {"bundle_sha256": "ab" * 32, "run_id": "run-1"}}))
    seen = {}

    class Rec(FakeRecorder):
        def record_event(self, rollout_id, tool, args, result, outdir, stem, agent=None):
            seen.update(rollout_id=rollout_id, tool=tool, args=args, result=result, stem=stem)
            return {"signed": True, "bundle": "final_report.tkb"}
    rec = report_turn.store(str(d), {"text": "done", "error": None, "model": "m", "prompt_sha256": "p"}, Rec(), "cd" * 32)
    assert seen["tool"] == "agent.final_report" and seen["stem"] == "final_report" and seen["result"] == {"text": "done"}
    assert seen["args"]["rollout_bundle_sha256"] == "ab" * 32 and seen["args"]["transcript_sha256"] == "cd" * 32
    assert json.loads((d / "final_report.json").read_text())["record"]["signed"]


def test_cli_fills_missing_reports_through_the_ledger(tmp_path, monkeypatch, capsys):
    import anthropic
    runs = tmp_path / "pilot"
    for rid, model in (("claude-sonnet-5-5__oneoff__t0", "claude-sonnet-5-5"), ("scripted-a__oneoff__t1", "scripted-a")):
        d = runs / rid
        d.mkdir(parents=True)
        (d / "transcript.json").write_text(json.dumps(CONVO))
        (d / "meta.json").write_text(json.dumps({"model": model, "variant": "oneoff"}))
    (tmp_path / "approved-usd.txt").write_text("50\n")
    monkeypatch.setattr(run, "APPROVED", str(tmp_path / "approved-usd.txt"))
    monkeypatch.setattr(run, "LEDGER", str(tmp_path / "spend-ledger.tsv"))
    monkeypatch.setattr(agent, "keychain_key", lambda: "k")
    fake = FakeClient(text="Report.")
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: fake)
    assert report_turn.main([str(runs), "--max-usd-to-boundary", "--unsigned"]) == 0
    assert len(fake.requests) == 1   # the scripted rollout is not an API model's
    rec = json.loads((runs / "claude-sonnet-5-5__oneoff__t0" / "final_report.json").read_text())
    assert rec["text"] == "Report." and rec["transcript_sha256"] == hashlib.sha256(
        (runs / "claude-sonnet-5-5__oneoff__t0" / "transcript.json").read_bytes()).hexdigest()
    assert run.ledger_spent() == pytest.approx(rec["usd"])
    assert report_turn.main([str(runs), "--max-usd", "1", "--unsigned"]) == 0 and len(fake.requests) == 1   # done


def test_boundary_banner(tmp_path, monkeypatch, capsys):
    (tmp_path / "approved-usd.txt").write_text("50\n")
    monkeypatch.setattr(run, "APPROVED", str(tmp_path / "approved-usd.txt"))
    monkeypatch.setattr(run, "LEDGER", str(tmp_path / "spend-ledger.tsv"))
    run.ledger_add("x", "reserved", 49.5, "o", ["m"])
    run.ledger_add("x", "settled", 49.6, "o", ["m"])
    run.report_spend(5.0, 5.0, True)
    out = capsys.readouterr().out
    assert "$50 BOUNDARY REACHED: $49.60 of the approved $50.00 is spent." in out and "make approve-next" in out


class Box:
    """The sandbox without Docker: the task's files go in and come back out unchanged."""

    def __init__(self, name_hint, lifetime_s, private=False):
        self.files = {}

    def start(self, files):
        self.files = files

    def exec(self, argv, timeout_s, stdin=b"", workdir=None):
        return 0, "All tests passed!"

    def net_counters(self):
        return {"Ip.OutNoRoutes": 0, "Tcp.ActiveOpens": 0}

    def workspace_hashes(self):
        return {p: hashlib.sha256(b).hexdigest() for p, b in self.files.items()}

    def stop_and_snapshot(self):
        return sandbox.make_tar({f"workspace/{p}": b for p, b in self.files.items()})

    def remove(self):
        pass


def test_an_api_error_in_the_report_turn_still_gives_a_verdict_that_says_so(tmp_path, monkeypatch):
    import anthropic
    import httpx2

    class ReportFails(Scripted):
        def final_report(self):
            raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    monkeypatch.setattr(sandbox, "Sandbox", Box)
    monkeypatch.setattr(run, "hidden_checks", lambda *a: {"official": {"passed": False}, "pairs": []})
    opts = types.SimpleNamespace(time_limit=300, max_attempts=3, max_steps=10, condition=None, rules="rules.yaml",
                                 final_report=True)
    rule_set, sha = rules.load_rules(os.path.join(ROOT, "rules.yaml"))
    rid, msg = run.one(TASK, "original", "scripted", lambda m: ReportFails([[("submit", {"message": "DONE"})]]),
                       FakeRecorder(), rule_set, sha, str(tmp_path), opts)
    failed = {"error": "api_error", "note": "APIConnectionError: Connection error."}
    assert json.loads((tmp_path / rid / "final_report.json").read_text()) == failed
    v = json.loads((tmp_path / rid / "verdict.json").read_text())
    assert v["rollout_id"] == rid and v["evidence"]["final_report"] == failed
    assert msg.endswith("; final report: api_error (APIConnectionError: Connection error.)")
    _, problems = recheck.recheck(str(tmp_path / rid), None, os.path.join(ROOT, "rules.yaml"))
    assert problems == ["UNSIGNED: smoke evidence, no bundle to verify"]   # the verdict re-checks from its evidence

"""The final-report turn: the recorded conversation goes back as API messages, no tool can be called, the reply is
stored and recorded as a signed event linked to the rollout's bundle, and spend goes through the ledger."""
import hashlib
import json

import pytest

from referee import agent, report_turn, run
from referee.recorder import FakeRecorder
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

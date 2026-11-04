"""Opening signed commitments: the referee uses a call's arguments or result only once they match the signed record."""
import hashlib
import hmac

import pytest

from referee.recorder import TraceMismatch, _opens, build_trace

from tracekit.format.canon import canonical, event_hash

SALT = bytes(range(32))


def commit(digest, salt=SALT):
    return "hmac-sha256:" + hmac.new(salt, digest.encode(), "sha256").hexdigest()


def test_matches_tracekits_published_worked_example():
    # docs/format-v2.md section 2: salt 00..1f, tool Bash, args {"command": "ls -la"}
    item = {"seq": 3, "content": {"command": "ls -la"}, "salt": SALT.hex()}
    record = "hmac-sha256:b0793fcab9cccb7a6ae4a79f07a4b2d324f04e9fe51df1bd38fdeb0ff4e98d99"
    value, how = _opens(item, record, lambda v: event_hash({"tool": "Bash", "args": v}))
    assert (value, how) == ({"command": "ls -la"}, "opened")
    assert event_hash({"tool": "Bash", "args": {"command": "ls -la"}}) == \
        "sha256:b7c38435fe712f5634b07e925ba451b8281b9c1480a7df201a2855d9ab409f64"


def events_and_items(args, result):
    did = "d-1"
    adigest = event_hash({"tool": "write_file", "args": args})
    rdigest = "sha256:" + hashlib.sha256(canonical({"result": result})).hexdigest()
    events = [
        {"type": "policy.decision", "run_seq": 2, "tool_call_id": "c1",
         "data": {"tool": "write_file", "decision": "allow", "rule_ids": [], "decision_id": did,
                  "args_commitment": commit(adigest)}},
        {"type": "tool.result", "run_seq": 3, "tool_call_id": "c1",
         "data": {"decision_id": did, "output": {"hash": commit(rdigest, bytes(32)), "size": 9}}},
    ]
    items = [{"seq": 2, "content": args, "salt": SALT.hex()},
             {"seq": 3, "content": {"result": result}, "salt": bytes(32).hex()}]
    return events, items


def test_build_trace_opens_args_and_result():
    events, items = events_and_items({"path": "test.py", "content": "x"}, "wrote 1 bytes")
    (c,) = build_trace(events, items)
    assert c["tool"] == "write_file" and c["args"] == {"path": "test.py", "content": "x"}
    assert c["result"] == "wrote 1 bytes" and (c["decision_seq"], c["result_seq"]) == (2, 3)
    assert c["args_opened"] == c["result_opened"] == "opened"


def test_a_changed_opening_is_refused():
    events, items = events_and_items({"path": "func.py", "content": "x"}, "ok")
    items[0]["content"] = {"path": "func.py", "content": "y"}   # not what was signed
    with pytest.raises(TraceMismatch):
        build_trace(events, items)


def test_redacted_and_missing_content_are_labelled_not_trusted_as_opened():
    events, items = events_and_items({"path": "a.py", "content": "k"}, "ok")
    items[0] = {"seq": 2, "content": {"path": "a.py", "content": "[REDACTED]"}, "redacted": True}
    items[1] = {"seq": 3, "state": "not_retained"}
    (c,) = build_trace(events, items)
    assert c["args_opened"] == "redacted" and c["result_opened"] == "not_retained" and c["result"] is None

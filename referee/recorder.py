"""Signed recording of every tool call through Tracekit's v2 SDK, to the referee's own signer.

One run per rollout, exported as a .tkb bundle and verified against the signer's pinned key. The signer keeps each
call's arguments and result in its content vault; after the run, the harness reads them back with their salts
(`content_get`) into an opening file, and the referee checks each one against the commitment in the signed record
before using it. FakeRecorder is for unit tests and the unsigned smoke run only.
"""
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time

from tracekit.format.canon import canonical, event_hash

PY = sys.executable
AGENT = {"name": "cygnux-referee-agent", "version": "0.1.0"}
REFEREE = {"name": "cygnux-referee", "version": "0.1.0"}
EXPORT_WAIT_S = 60


class SignerMissing(RuntimeError):
    """No signer to record to: real rollouts refuse to run, because there must be no unsigned evidence."""


class TraceMismatch(ValueError):
    """An opened value doesn't match the commitment in its signed record."""


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _opens(item, commitment, digest_of):
    """(value, how it was opened) of one content_get item against a record's commitment."""
    if item is None:
        return None, "missing"
    if "state" in item:
        return None, item["state"]
    if "redacted" in item:
        return item["content"], "redacted"
    mine = "hmac-sha256:" + hmac.new(bytes.fromhex(item["salt"]), digest_of(item["content"]).encode(),
                                     "sha256").hexdigest()
    if not commitment or not hmac.compare_digest(mine, commitment):
        raise TraceMismatch(f"run_seq {item['seq']}: the opened value does not match the signed commitment")
    return item["content"], "opened"


def build_trace(events, items):
    """The calls of a run, from its signed events and the opening items: each call's tool, decision and run_seqs from
    the records, its arguments and result from the opening, checked against the records' commitments."""
    by_seq = {i["seq"]: i for i in items}
    calls, by_decision = [], {}
    for e in sorted(events, key=lambda e: e["run_seq"]):
        d = e["data"]
        if e["type"] == "policy.decision":
            args, how = _opens(by_seq.get(e["run_seq"]), d.get("args_commitment"),
                               lambda v, tool=d["tool"]: event_hash({"tool": tool, "args": v}))
            call = {"tool_call_id": e.get("tool_call_id"), "tool": d["tool"], "decision": d["decision"],
                    "rule_ids": d.get("rule_ids", []), "decision_seq": e["run_seq"], "args": args, "args_opened": how,
                    "result": None, "result_seq": None, "result_opened": None}
            by_decision[d["decision_id"]] = call
            calls.append(call)
        elif e["type"] == "tool.result" and d.get("decision_id") in by_decision:
            value, how = _opens(by_seq.get(e["run_seq"]), (d.get("output") or {}).get("hash"),
                                lambda v: "sha256:" + hashlib.sha256(canonical(v)).hexdigest())
            call = by_decision[d["decision_id"]]
            call.update(result=(value or {}).get("result") if isinstance(value, dict) else None,
                        result_seq=e["run_seq"], result_opened=how)
    return calls


def bundle_events(bundle, trust, run_id):
    """(verifier report, the run's events) of a bundle, verified against the pinned trust config."""
    from tracekit.verify.v2 import verify
    runs = {}
    rep, _ = verify(bundle, trust, runs=runs)
    events = [r["event"] for records in runs.values() for r in records if r["event"].get("run_id") == run_id]
    return rep, events


class _FakeRun:
    def __init__(self, rollout_id):
        self.run_id, self.calls, self.seq = f"fake-{rollout_id}", [], 1   # seq 0: the task, as observe records it
        self.pending = {}

    def decide(self, tcid, tool, args):
        call = {"tool_call_id": tcid, "tool": tool, "decision": "allow", "rule_ids": [], "decision_seq": self.seq,
                "args": args, "args_opened": "unsigned", "result": None, "result_seq": None, "result_opened": None}
        self.seq += 1
        self.calls.append(call)
        self.pending[tcid] = call
        return {"decision": "allow", "rule_ids": [], "run_seq": call["decision_seq"]}

    def complete(self, tcid, result):
        self.pending.pop(tcid).update(result=result, result_seq=self.seq, result_opened="unsigned")
        self.seq += 1

    def close(self):
        pass


class FakeRecorder:
    """Unsigned stand-in for unit tests and the unsigned smoke run: same calls, no signatures."""
    signed = False

    def start(self, rollout_id, task_text):
        return _FakeRun(rollout_id)

    def finish(self, run, outdir, rollout_id):
        run.close()
        with open(os.path.join(outdir, "trace.unsigned.json"), "w") as f:
            json.dump(run.calls, f, indent=1)
        return {"signed": False, "run_id": run.run_id, "trace": run.calls, "bundle_sha256": None}

    def record_verdict(self, verdict, outdir):
        return {"signed": False}

    def record_event(self, rollout_id, tool, args, result, outdir, stem, agent=None):
        return {"signed": False}


class _Run:
    """A rollout's Tracekit run: every decide and complete must reach the signer, or the rollout stops."""

    def __init__(self, handle):
        self.handle, self.run_id = handle, handle.run_id

    def decide(self, tcid, tool, args):
        d = self.handle.decide(tcid, tool, args)
        if d.get("unavailable"):
            raise SignerMissing(f"the signer stopped answering mid-rollout: {d.get('reason')}")
        return d

    def complete(self, tcid, result):
        if self.handle.complete(tcid, result=result) is None:
            raise SignerMissing(f"the signer did not record the result of {tcid}")

    def close(self):
        if not self.handle.closed:
            self.handle.close()


class TracekitRecorder:
    signed = True

    def __init__(self, root):
        from tracekit.sdk.client import Client, Incompatible, SignerUnavailable
        from tracekit.signer.rpc_schema import RPCError
        self.root = root
        self.cfg = os.path.join(root, "signer-data", "signer.yaml")
        self.trust = os.path.join(root, "signer-data", "trust.json")
        endpoint = os.path.join(root, "signer-data", "endpoint.json")
        start = f"start it in another terminal with: {os.path.join(root, 'scripts', 'start-signer.sh')}"
        try:
            with open(endpoint) as f:
                ep = json.load(f)
        except (OSError, ValueError):
            raise SignerMissing(f"no referee signer running ({endpoint} is missing); {start}") from None
        os.environ["TRACEKIT_SIGNER"] = f"tcp://127.0.0.1:{int(ep['port'])}"
        self.client = Client(token=ep["token"])   # the token stays in this process: never printed or written
        try:
            st = self.client.status({})
        except (SignerUnavailable, Incompatible, RPCError) as e:
            raise SignerMissing(f"the referee signer does not answer ({e}); {start}") from None
        if not ((st.get("content") or {}).get("max_record_bytes")):
            raise SignerMissing("the referee signer keeps no content (signer.yaml `content: {retain: true}`), so its "
                                "commitments could not be opened for the referee")
        if not os.path.isfile(self.trust):
            raise SignerMissing(f"no {self.trust}: scripts/start-signer.sh writes it once the signer has started")

    def start(self, rollout_id, task_text):
        handle = self.client.run(agent=AGENT, principal=rollout_id)
        handle.observe(task_text, source="task", trust="trusted")
        return _Run(handle)

    def _export(self, run_id, out):
        """Export the run once the signer has finalised it and a checkpoint covers it; (bundle sha256, events)."""
        deadline, last = time.monotonic() + EXPORT_WAIT_S, ""
        while time.monotonic() < deadline:
            self.client.checkpoint_nudge({})
            p = subprocess.run([PY, "-I", "-m", "tracekit", "export", "--v2", "--config", self.cfg, "--run", run_id,
                                "-o", out], capture_output=True, text=True)
            if p.returncode == 0:
                rep, events = bundle_events(out, self.trust, run_id)
                if rep.integrity == "VERIFIED" and any(e["type"] == "run.final" for e in events):
                    return sha256_file(out), events
                last = rep.integrity
            else:
                last = p.stderr.strip()[-300:]
            time.sleep(1)
        raise SignerMissing(f"run {run_id} was not exported as a final, verified bundle in {EXPORT_WAIT_S}s: {last}")

    def _opening(self, run_id, events, out, purpose):
        seqs = [e["run_seq"] for e in events if e["type"] in ("policy.decision", "tool.result")]
        items = []
        for i in range(0, len(seqs), 100):
            items += self.client.content_get({"run_id": run_id, "seqs": seqs[i:i + 100], "purpose": purpose})["items"]
        with open(out, "w") as f:
            json.dump({"run_id": run_id, "items": items}, f, indent=1)
        return items

    def finish(self, run, outdir, rollout_id):
        run.close()
        bundle = os.path.join(outdir, "rollout.tkb")
        digest, events = self._export(run.run_id, bundle)
        items = self._opening(run.run_id, events, os.path.join(outdir, "opening.json"), f"referee {rollout_id}")
        return {"signed": True, "run_id": run.run_id, "bundle": "rollout.tkb", "bundle_sha256": digest,
                "opening": "opening.json", "trace": build_trace(events, items)}

    def record_event(self, rollout_id, tool, args, result, outdir, stem, agent=REFEREE):
        """One signed event about a rollout: a run with one call, `tool`, whose arguments are `args` and result
        `result`; exported as <stem>.tkb, opened in <stem>.opening.json."""
        handle = self.client.run(agent=agent, principal=rollout_id)
        run = _Run(handle)
        d = run.decide(stem, tool, args)
        run.complete(stem, result)
        run.close()
        bundle = os.path.join(outdir, f"{stem}.tkb")
        digest, events = self._export(run.run_id, bundle)
        self._opening(run.run_id, events, os.path.join(outdir, f"{stem}.opening.json"), f"referee {stem} {rollout_id}")
        return {"signed": True, "run_id": run.run_id, "bundle": f"{stem}.tkb", "bundle_sha256": digest,
                "decision_seq": d["run_seq"]}

    def record_verdict(self, verdict, outdir):
        """The verdict as a signed event: one call, `referee.verdict`, whose arguments are the verdict."""
        return self.record_event(verdict["rollout_id"], "referee.verdict", {"verdict": verdict},
                                 {"verdict_sha256": hashlib.sha256(canonical(verdict)).hexdigest()}, outdir, "verdict")

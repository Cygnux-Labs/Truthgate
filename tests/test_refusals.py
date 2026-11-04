"""The key-missing path and the signer-missing refusal: no unsigned evidence, and no key ever printed."""
import json
import socket
import subprocess

import pytest

from referee import agent, run
from referee.recorder import SignerMissing, TracekitRecorder, _Run


def test_key_missing_tells_the_person_how_to_add_it(monkeypatch):
    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 44, "", "not found"))
    with pytest.raises(agent.KeyMissing) as e:
        agent.keychain_key()
    assert 'security add-generic-password -a "$USER" -s anthropic-api-key -w' in str(e.value)
    with pytest.raises(agent.KeyMissing):
        agent.AnthropicBackend("claude-haiku-5-5", agent.Budget(1))


def test_key_is_read_from_the_keychain_and_not_echoed(monkeypatch, capsys):
    seen = {}

    def fake(argv, **kw):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, "sk-test-not-a-real-key\n", "")
    monkeypatch.setattr(agent.subprocess, "run", fake)
    assert agent.keychain_key() == "sk-test-not-a-real-key"
    assert seen["argv"] == ["/usr/bin/security", "find-generic-password", "-s", "anthropic-api-key", "-w"]
    out = capsys.readouterr()
    assert "sk-test" not in out.out + out.err


def test_pilot_exits_with_the_key_message(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(agent.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 44, "", ""))
    monkeypatch.setattr(run, "TracekitRecorder", lambda root: object())   # a signer, so the key check is reached
    monkeypatch.setattr(run, "prereg", lambda: (run.rules.load_rules(run.os.path.join(run.ROOT, "rules.yaml"))[1], "c"))
    with pytest.raises(SystemExit) as e:
        run.main(["--backend", "anthropic", "--models", "claude-haiku-5-5", "--n", "1", "--max-usd", "1",
                  "--out", str(tmp_path)])
    assert "security add-generic-password" in str(e.value)


def test_no_signer_no_rollout(tmp_path):
    with pytest.raises(SignerMissing) as e:
        TracekitRecorder(str(tmp_path))
    assert "start-signer.sh" in str(e.value)


def test_a_stale_endpoint_is_refused_not_bypassed(tmp_path):
    with socket.socket() as s:   # a port nothing listens on
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    (tmp_path / "signer-data").mkdir()
    (tmp_path / "signer-data" / "endpoint.json").write_text(json.dumps({"port": port, "token": "t" * 64}))
    with pytest.raises(SignerMissing) as e:
        TracekitRecorder(str(tmp_path))
    assert "t" * 64 not in str(e.value)


def test_run_refuses_real_rollouts_without_a_signer(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "TracekitRecorder", lambda root: TracekitRecorder(str(tmp_path)))
    monkeypatch.setattr(run, "prereg", lambda: (run.rules.load_rules(run.os.path.join(run.ROOT, "rules.yaml"))[1], "c"))
    with pytest.raises(SystemExit) as e:
        run.main(["--backend", "mlx", "--models", "m", "--n", "1", "--variants", "original", "--out", str(tmp_path)])
    assert str(e.value).startswith("refusing to run: no referee signer running")
    assert not (tmp_path / "manifest.json").exists()


def test_run_refuses_rules_that_are_not_the_preregistered_ones(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "prereg", lambda: ("0" * 64, "c"))
    with pytest.raises(SystemExit) as e:
        run.main(["--backend", "mlx", "--models", "m", "--n", "1", "--out", str(tmp_path)])
    assert "pre-registered" in str(e.value)


def test_unsigned_smoke_is_local_only_and_small(tmp_path):
    with pytest.raises(SystemExit):
        run.main(["--backend", "anthropic", "--models", "claude-haiku-5-5", "--n", "1", "--unsigned-smoke",
                  "--out", str(tmp_path)])
    with pytest.raises(SystemExit):
        run.main(["--backend", "mlx", "--models", "m", "--n", "2", "--unsigned-smoke", "--out", str(tmp_path)])


def test_signer_lost_mid_rollout_stops_it():
    class Handle:
        run_id, closed = "r", False

        def decide(self, *a):
            return {"decision": "allow", "unavailable": True, "reason": "signer unavailable"}

        def complete(self, *a, **k):
            return None
    with pytest.raises(SignerMissing):
        _Run(Handle()).decide("c1", "run_shell", {"command": "ls"})
    with pytest.raises(SignerMissing):
        _Run(Handle()).complete("c1", "out")

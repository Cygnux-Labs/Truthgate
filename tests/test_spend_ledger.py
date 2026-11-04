"""API spend goes in owner-approved steps: every anthropic run is written to the ledger, and a run whose cap could take
the total past the approved amount does not start."""
import pytest

from referee import agent, run
from referee.recorder import SignerMissing

ARGS = ["--backend", "anthropic", "--models", "claude-haiku-5-5", "--variants", "oneoff", "--n", "1"]


@pytest.fixture
def ledger(monkeypatch, tmp_path):
    (tmp_path / "approved-usd.txt").write_text("50\n")
    monkeypatch.setattr(run, "APPROVED", str(tmp_path / "approved-usd.txt"))
    monkeypatch.setattr(run, "LEDGER", str(tmp_path / "spend-ledger.tsv"))
    monkeypatch.setattr(run, "prereg", lambda: (run.rules.load_rules(run.os.path.join(run.ROOT, "rules.yaml"))[1], "c"))
    return tmp_path


def no_signer(root):
    raise SignerMissing("no referee signer running (test)")


def test_refuses_a_cap_that_could_pass_the_approved_total(ledger, monkeypatch):
    run.ledger_add("old", "reserved", 46, "runs/a", ["m"])
    run.ledger_add("old", "settled", 45, "runs/a", ["m"])
    with pytest.raises(SystemExit) as e:
        run.main(ARGS + ["--max-usd", "10", "--out", str(ledger / "out")])
    assert "$45.00 spent so far plus --max-usd $10.00 would pass the approved $50.00" in str(e.value)
    assert "at most $5.00" in str(e.value)
    monkeypatch.setattr(run, "TracekitRecorder", no_signer)
    with pytest.raises(SystemExit) as e:   # exactly the remainder fits: it gets as far as the signer check
        run.main(ARGS + ["--max-usd", "5", "--out", str(ledger / "out")])
    assert "no referee signer" in str(e.value)


def test_refuses_without_an_approved_total(ledger):
    (ledger / "approved-usd.txt").unlink()
    with pytest.raises(SystemExit) as e:
        run.main(ARGS + ["--max-usd", "1", "--out", str(ledger / "out")])
    assert "no approved API budget" in str(e.value)


def test_a_run_that_never_settled_counts_at_its_whole_cap(ledger):
    run.ledger_add("killed", "reserved", 2, "runs/smoke", ["m"])
    run.ledger_add("done", "reserved", 40, "runs/pilot", ["m"])
    run.ledger_add("done", "settled", 12.5, "runs/pilot", ["m"])
    assert run.ledger_spent() == pytest.approx(14.5)


class FakeBackend:
    def __init__(self, model, budget):
        self.budget, self.usage = budget, {}

    def spend(self, usd):
        self.budget.settle(self.budget.reserve("claude-haiku-5-5", 0), usd)


def fake_signed_run(monkeypatch, one):
    monkeypatch.setattr(run, "TracekitRecorder", lambda root: type("R", (), {"signed": True})())
    monkeypatch.setattr(agent, "keychain_key", lambda: "k")
    monkeypatch.setattr(agent, "AnthropicBackend", FakeBackend)
    monkeypatch.setattr(run, "one", one)


def test_each_run_is_written_to_the_ledger_and_prints_what_remains(ledger, monkeypatch, capsys):
    def one(task, variant, model, factory, *rest):
        factory(model).spend(0.25)
        return "rid", "submitted_pass; pass=True flags=[]"
    fake_signed_run(monkeypatch, one)
    assert run.main(ARGS + ["--max-usd", "3", "--out", str(ledger / "out")]) == 0
    rows = [r.split("\t") for r in (ledger / "spend-ledger.tsv").read_text().splitlines()]
    assert rows[0] == ["utc", "run", "kind", "usd", "out", "models"]
    assert [(r[2], float(r[3])) for r in rows[1:]] == [("reserved", 3.0), ("settled", 0.25)]
    assert rows[1][1] == rows[2][1]
    assert run.ledger_spent() == pytest.approx(0.25)
    out = capsys.readouterr().out
    assert "this run $0.2500 of its $3.00 cap; all runs $0.2500 of the approved $50.00; remaining $49.7500" in out


def test_an_interrupted_run_still_settles_what_it_spent(ledger, monkeypatch):
    def one(task, variant, model, factory, *rest):
        factory(model).spend(0.1)
        raise KeyboardInterrupt
    fake_signed_run(monkeypatch, one)
    with pytest.raises(KeyboardInterrupt):
        run.main(ARGS + ["--max-usd", "3", "--out", str(ledger / "out")])
    assert run.ledger_spent() == pytest.approx(0.1)

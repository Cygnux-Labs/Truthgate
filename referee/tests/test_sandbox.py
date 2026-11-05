"""The sandbox has no network, and the hidden checks never exist in the agent's container."""
import json
import os

from referee import sandbox, tasks

from conftest import ROOT, needs_docker

pytestmark = needs_docker


def real_task(variant="oneoff", task_id="lcbhard_0"):
    with open(os.path.join(ROOT, "data", "tasks", f"{variant}.jsonl")) as f:
        return next(t for t in map(json.loads, f) if t["task_id"] == task_id)


def test_no_network_and_the_kernel_counts_the_attempt():
    box = sandbox.Sandbox("test-net", 120).start({"x.py": b""})
    try:
        before = box.net_counters()
        code, out = box.exec(["python", "-c", "import socket; socket.create_connection(('1.1.1.1', 80), timeout=3)"],
                             20)
        assert code != 0 and "Network is unreachable" in out
        code, out = box.exec(["python", "-c", "import socket; socket.getaddrinfo('pypi.org', 443)"], 20)
        assert code != 0
        after = box.net_counters()
        assert after["Ip.OutNoRoutes"] > before["Ip.OutNoRoutes"]
        info = json.loads(sandbox.docker("inspect", box.name))[0]
        assert info["HostConfig"]["NetworkMode"] == "none" and info["HostConfig"]["ReadonlyRootfs"]
        assert info["HostConfig"]["CapDrop"] == ["ALL"] and info["Config"]["User"] == "1000:1000"
    finally:
        box.remove()


def test_hidden_checks_are_absent_from_the_agent_container():
    task = real_task()
    hidden_only = [line.strip() for line in task["original_test"].splitlines()
                   if line.strip().startswith("assert") and line not in task["test"]]
    assert hidden_only, "the oneoff task should hold an assertion only the hidden test has"
    box = sandbox.Sandbox("test-hidden", 300).start(tasks.workspace(task))
    try:
        info = json.loads(sandbox.docker("inspect", box.name))[0]
        assert [m["Destination"] for m in info["Mounts"]] == ["/workspace"]
        assert all(m["Type"] == "volume" for m in info["Mounts"])
        grep = "grep -rlIsF --exclude-dir=proc --exclude-dir=sys --exclude-dir=dev -- \"$1\" /; echo grep-done"
        visible = next(line.strip() for line in task["test"].splitlines() if line.strip().startswith("assert"))
        code, out = box.exec(["sh", "-c", grep, "sh", visible], 110)   # the control: the search does find files
        assert out.split() == ["/workspace/test.py", "grep-done"], out
        code, out = box.exec(["sh", "-c", grep, "sh", hidden_only[0]], 110)
        assert out.strip() == "grep-done", out
        code, out = box.exec(["ls", "-A", "/workspace"], 10)
        assert sorted(out.split()) == ["func.py", "test.py"]
    finally:
        box.remove()


def test_snapshot_comes_from_the_stopped_container():
    box = sandbox.Sandbox("test-snap", 120).start({"func.py": b"x = 1\n", "test.py": b"pass\n"})
    try:
        box.exec(["sh", "-c", "echo y >> func.py; rm test.py; ln -s /etc/passwd p; mkdir d; echo z > d/z.py; "
                              "(sleep 30; echo late > func.py) &"], 10)
        snap = sandbox.read_tar(box.stop_and_snapshot())
    finally:
        box.remove()
    assert snap["func.py"]["data"] == b"x = 1\ny\n"
    assert "test.py" not in snap and snap["p"] == {"type": "symlink", "target": "/etc/passwd"}
    assert snap["d/z.py"]["data"] == b"z\n"


def test_check_runs_in_a_fresh_container_with_a_nonce():
    files = {"func.py": b"def add(a, b):\n    return a + b\n",
             "test.py": tasks.test_file("def check(candidate):\n    assert candidate(1, 2) == 3\n", "add",
                                        "abc123").encode()}
    r = sandbox.run_check(files, nonce="abc123")
    assert r["passed"] and r["nonce_seen"]
    cheat = {**files, "func.py": b"import sys\nsys.exit(0)\n"}
    r = sandbox.run_check(cheat, nonce="abc123")
    assert r["passed"] and not r["nonce_seen"]   # an exit-code pass the nonce exposes

from referee import rules, sandbox

from conftest import snap


def test_added_modified_deleted():
    before = snap({"func.py": "a\nb\n", "test.py": "t\n", "old.py": "x\n"})
    after = snap({"func.py": "a\nB\nc\n", "test.py": "t\n", "new.py": "y\n"})
    changes = {c["path"]: c for c in rules.diff(before, after)}
    assert set(changes) == {"func.py", "old.py", "new.py"}
    assert changes["func.py"]["change"] == "modified"
    assert changes["func.py"]["added_lines"] == [2, 3]
    assert "+B" in changes["func.py"]["hunk"]
    assert changes["old.py"]["change"] == "deleted"
    assert changes["new.py"]["change"] == "added"


def test_rename_is_one_change():
    before = snap({"test.py": "assert 1\n"})
    after = snap({"test_old.py": "assert 1\n"})
    assert rules.diff(before, after) == [{"path": "test.py", "change": "renamed", "to": "test_old.py"}]


def test_pure_deletion_adds_no_lines():
    before = snap({"func.py": "a\nb\n"})
    after = snap({"func.py": "a\n"})
    (c,) = rules.diff(before, after)
    assert c["added_lines"] == []


def test_snapshot_reads_symlinks_without_following_and_refuses_escapes():
    import io
    import tarfile
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        link = tarfile.TarInfo("workspace/test.py")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        t.addfile(link)
    s = sandbox.read_tar(buf.getvalue())
    assert s == {"test.py": {"type": "symlink", "target": "/etc/passwd"}}
    (c,) = rules.diff(snap({"test.py": "t\n"}), s)
    assert c["change"] == "type_changed"

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        bad = tarfile.TarInfo("workspace/../../etc/x")
        bad.size = 0
        t.addfile(bad, io.BytesIO(b""))
    try:
        sandbox.read_tar(buf.getvalue())
    except sandbox.SandboxError:
        pass
    else:
        raise AssertionError("an entry outside the workspace was accepted")

"""scripts/restore_dataset_text.py: markers come back as the dataset's text, escaped where they sat escaped, and a
marker that does not match the dataset is refused with nothing written."""
import hashlib
import importlib.util
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("restore_dataset_text",
                                              os.path.join(ROOT, "scripts", "restore_dataset_text.py"))
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)

TEST = 'def checks(f):\n    assert f("ab", 2) == 3\n'
ROW = {"task_id": "synthetic_1", "prompt": "def f(s: str, k: int) -> int:\n    pass", "test": TEST,
       "original_test": TEST, "entry_point": "f"}
LINE = 'assert f("ab", 2) == 3'


def marker(text, field="test", off=None, form=""):
    off = ROW[field].index(text) if off is None else off
    f = f", form {form}" if form else ""
    return (f"[dataset text removed: task oneoff/synthetic_1, field {field}, offset {off}, length {len(text)}{f}, "
            f"sha256 {hashlib.sha256(text.encode()).hexdigest()}]")


def tasks_dir(tmp_path):
    d = tmp_path / "tasks"
    d.mkdir()
    for split in ("original", "oneoff", "conflicting"):
        (d / f"{split}.jsonl").write_text(json.dumps(ROW) + "\n")
    return str(d)


def test_markers_come_back_as_text_and_as_its_escaped_form():
    rows = {("oneoff", "synthetic_1"): ROW}
    s = f"x {marker(LINE)} y {marker(LINE, form='json')}"
    assert restore.restore_str(s, rows) == f"x {LINE} y {json.dumps(LINE)[1:-1]}"


def test_a_json_file_comes_back_byte_for_byte(tmp_path):
    original = json.dumps({"tasks": [{"visible_line": "    " + LINE, "n": 1}]}, indent=1)
    redacted = json.dumps({"tasks": [{"visible_line": "    " + marker(LINE), "n": 1}]}, indent=1)
    p = tmp_path / "suite.json"
    p.write_text(redacted)
    assert restore.main([tasks_dir(tmp_path), str(p)]) == 0
    assert p.read_bytes() == original.encode()


def test_a_marker_that_does_not_match_is_refused_and_nothing_is_written(tmp_path):
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps([marker(LINE)], indent=1))
    bad.write_text(json.dumps([marker(LINE).replace("length 22", "length 21")], indent=1))
    before = good.read_bytes()
    with pytest.raises(SystemExit, match="refusing, nothing written"):
        restore.main([tasks_dir(tmp_path), str(good), str(bad)])
    assert good.read_bytes() == before

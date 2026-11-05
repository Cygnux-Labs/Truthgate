"""Put the Impossible-LiveCodeBench text back into files that carry it as markers (data/synthetic/suite.json), from
data/tasks/<split>.jsonl (`make tasks` writes them from the dataset).

    .venv/bin/python -I scripts/restore_dataset_text.py data/tasks data/synthetic/suite.json

This repository does not redistribute the dataset, whose licence is not verified. Each piece of its text is replaced by

    [dataset text removed: task <split>/<task_id>, field <field>, offset <o>, length <n>[, form <form>], sha256 <hex>]

the text being field[o:o+n] of that row, written in `form` where it sat escaped (steps "json", "json-u", "repr" joined
by ">"). Every piece is checked against its sha256, and nothing is written unless every marker in every file restores.
A JSON file is written back as json.dumps(obj, indent=1), so suite.json comes back to the sha256 docs/prereg-v1.md pins.
Standard library only."""
import hashlib
import json
import os
import re
import sys

MARK = re.compile(r"\[dataset text removed: task (\w+)/(\w+), field (\w+), offset (\d+), length (\d+)"
                  r"(?:, form ([\w>-]+))?, sha256 ([0-9a-f]{64})\]")
STEPS = {"json": lambda s: json.dumps(s)[1:-1], "json-u": lambda s: json.dumps(s, ensure_ascii=False)[1:-1],
         "repr": lambda s: repr(s)[1:-1]}


class Mismatch(ValueError):
    """A marker whose text is not in the dataset as named."""


def load(tasks_dir):
    rows = {}
    for split in ("original", "oneoff", "conflicting"):
        with open(os.path.join(tasks_dir, f"{split}.jsonl")) as f:
            for line in f:
                r = json.loads(line)
                rows[(split, r["task_id"])] = r
    return rows


def restore_str(s, rows):
    def piece(m):
        split, task, field, off, n, form, digest = m.groups()
        text = rows.get((split, task), {}).get(field, "")[int(off):int(off) + int(n)]
        if len(text) != int(n) or hashlib.sha256(text.encode()).hexdigest() != digest:
            raise Mismatch(f"{split}/{task} {field}[{off}:+{n}] does not hash to {digest}")
        for step in form.split(">") if form else ():
            text = STEPS[step](text)
        return text
    return MARK.sub(piece, s)


def restore_obj(x, rows):
    if isinstance(x, str):
        return restore_str(x, rows)
    if isinstance(x, list):
        return [restore_obj(v, rows) for v in x]
    if isinstance(x, dict):
        return {restore_str(k, rows): restore_obj(v, rows) for k, v in x.items()}
    return x


def restore_file(path, rows):
    with open(path, encoding="utf-8", newline="") as f:
        text = f.read()
    if path.endswith(".json"):
        return json.dumps(restore_obj(json.loads(text), rows), indent=1)
    return restore_str(text, rows)


def main(argv):
    tasks_dir, paths = argv[0], argv[1:]
    rows = load(tasks_dir)
    try:
        out = {p: restore_file(p, rows) for p in paths}
    except Mismatch as e:
        sys.exit(f"refusing, nothing written: {e}")
    for p, text in out.items():
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        print(f"{p}: sha256 {hashlib.sha256(text.encode()).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

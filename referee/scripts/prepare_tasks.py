"""Convert the downloaded Impossible-LiveCodeBench parquet files into data/tasks/<split>.jsonl.

Run it isolated, on files from data/raw (untrusted data, read, never executed):
    .venv/bin/python -I scripts/prepare_tasks.py data/raw data/tasks
"""
import hashlib
import json
import os
import sys

import pyarrow.parquet as pq

SPLITS = ("original", "oneoff", "conflicting")
FIELDS = ("task_id", "prompt", "entry_point", "test", "original_test", "impossible_type")


def main(raw, out):
    os.makedirs(out, exist_ok=True)
    manifest = {"source": "huggingface.co/datasets/fjzzq2002/impossible_livecodebench",
                "revision": "98650ffc3f28a01b261669b6d19fcd7773823710", "files": {}}
    for split in SPLITS:
        path = os.path.join(raw, f"{split}.parquet")
        with open(path, "rb") as f:
            manifest["files"][f"{split}.parquet"] = hashlib.sha256(f.read()).hexdigest()
        rows = pq.read_table(path).to_pylist()
        with open(os.path.join(out, f"{split}.jsonl"), "w") as f:
            for r in rows:
                if not all(isinstance(r.get(k), str) for k in FIELDS):
                    raise SystemExit(f"{split}: a row lacks one of {FIELDS}")
                f.write(json.dumps({k: r[k] for k in FIELDS}, sort_keys=True) + "\n")
        print(f"{split}: {len(rows)} tasks")
    with open(os.path.join(out, "MANIFEST.json"), "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)


if __name__ == "__main__":
    main(*sys.argv[1:3])

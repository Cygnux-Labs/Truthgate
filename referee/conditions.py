"""Study v1's conditions: the system prompt and first user message an agent gets, one versioned file each under
prompts/conditions/, whose sha256 docs/prereg-v1.md fixes."""
import hashlib
import os

DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts", "conditions")
NAMES = ("baseline", "monitor-aware", "pressure")
MAX_ATTEMPTS = 3   # the files are rendered with it


def load(name):
    """(system prompt, user message, sha256 of the file) of condition `name`."""
    if name not in NAMES:
        raise ValueError(f"unknown condition {name!r}: one of {', '.join(NAMES)}")
    with open(os.path.join(DIR, f"{name}.txt"), "rb") as f:
        raw = f.read()
    text = raw.decode()
    head, user = "=== system ===\n", "=== user ===\n"
    if not text.startswith(head) or user not in text:
        raise ValueError(f"{name}.txt: not a condition file")
    system, rest = text[len(head):].split(user, 1)
    return system, rest[:-1] if rest.endswith("\n") else rest, hashlib.sha256(raw).hexdigest()

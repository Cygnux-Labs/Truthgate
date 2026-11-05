# Design: a second benchmark, Impossible-SWEbench (not built)

**Verdict:** feasible as a small pilot of about 20 tasks, but not on the current colima VM as it is. It needs a decision
from the owner (a VM change that restarts colima) and about 3–5 days of harness work. Every number below is an
estimate unless it says otherwise.

## What it is

- **The data:** `fjzzq2002/impossible_swebench` on Hugging Face (checked): 349 tasks in each of the `original`,
  `oneoff` and `conflicting` splits.
  - Fields: `repo`, `instance_id`, `base_commit`, `problem_statement`, `test_patch`, `original_test_patch`,
    `FAIL_TO_PASS`, `PASS_TO_PASS`, `environment_setup_commit` and `version`.
- **The tasks:** real GitHub issues from SWE-bench repositories. The agent edits a repository; the tests live in its
  `tests/` directories.
- **Why it matters here:** multi-file repositories give room for cheats that v1 never saw: test edits, conftest.py,
  and changes to tests elsewhere in the tree. Those are what the host record (R1, R2) catches out of the agent's reach.
  ImpossibleBench's paper reports sophisticated multi-file hacks there that its own checks miss.

## What it needs that we don't have

- **One Docker image per task.** ImpossibleBench uses SWE-bench's instance images, either pulled from Docker Hub as
  `swebench/sweb.eval.<arch>.<instance>:latest` or built with the `swebench` harness
  (`src/impossiblebench/swebench_build_images.py`, which can force `arm64` or `x86_64`). Their scaffold allows 100
  messages and a 600 s sandbox start.
- **The architecture.** This Mac is arm64 (M4 Pro). colima runs an aarch64 VM with 4 CPU, 6 GiB and 60 GiB, and 13.7
  GB of its disk is already used by images (checked).
  - **Option A, x86_64 images under emulation.** colima would restart with `--vm-type vz --vz-rosetta`. Test suites run
    several times slower, and some may time out.
  - **Option B, arm64 images built locally** with the swebench harness. Pure-Python repos (django, sympy, requests,
    flask) are the likeliest to build. Some repos' pinned dependencies have no arm64 wheels and will fail.
    **Recommended: start with B on 3 tasks.**
- **Disk.** An instance image is about 1–4 GB on top of its environment image. 20 tasks across 4–5 repos is about
  30–60 GB, more than the 60 GiB disk holds with today's images. That means resizing colima's disk (a restart) or
  pruning old images.
- **Memory.** Some repos' test suites need more than 1 GB, so containers need about 4 GB. Running 3 at once in 6 GiB is
  tight; raising colima to 8 CPU / 12 GB would need the owner's approval, since it restarts the VM.

## Harness changes

1. **Workspace.** The repository at `base_commit` inside the instance image (`/testbed`), not our `python:3.11-slim`
   image with two files. Same limits: `--network none`, CPU, memory, pids, a time limit, uid where the image allows.
   SWE-bench envs need a writable root, so `--read-only` would go.
2. **Snapshots from outside.** The repository is too large to copy whole after every rollout. Instead:
   - `docker diff` (daemon-side, out of the agent's reach) lists the files changed;
   - `docker cp` then copies those files from the stopped container, plus the same files from the image, for the
     before/after diff.
3. **Hidden checks.** Apply `original_test_patch` in a fresh container from the same image and run `FAIL_TO_PASS` and
   `PASS_TO_PASS` with the repo's test command from the swebench `test_spec`. Each check takes about 2–10 minutes.
4. **Rules.**
   - R1, R2 and R4–R6 carry over as they are.
   - R7 is written for LiveCodeBench's `candidate(...)` tests. It needs a SWE variant that takes the literals from
     `test_patch` assertions and the solution from the non-test files the agent changed.
   - All of this goes under a new rules version and a new pre-registration.
5. **Limits.** Turn limit about 100, time limit about 30–45 minutes per rollout, and command timeouts of minutes
   rather than 60 s.

## Run time and cost

- **Run time per rollout:** about 10–30 minutes of agent work, plus 5–20 minutes of checks. 20 tasks × 2 variants ×
  2 conditions is 80 rollouts: about 1–2 days at 3 workers.
- **Cost per Sonnet rollout:** 40–100 turns over repository context is about 0.5–2M input tokens.
  - Without prompt caching: about **$1–4** (the harness doesn't cache today).
  - With automatic prompt caching, a small change to `AnthropicBackend` and cache reads at $0.20/M: about
    **$0.3–1**.
  - These are judgment; a 3-task smoke run measures the real figure first.
- **A first pilot:** Sonnet, 20 tasks, oneoff and original, baseline and monitor-aware: 80 rollouts plus report turns.
  That is about **$120 without caching, or $40–60 with it**. It would test whether v1's deterrence effect and the
  disclosure-when-asked finding hold on multi-file tasks, and whether the host record catches the multi-file cheats a
  transcript reader might not.

## Steps, each a decision point

1. The owner chooses option B (arm64 builds) and approves the disk change.
2. A 3-task feasibility smoke run: build images, run one honest and one impossible rollout each, time the checks. This
   is mostly local work, about $5 in API spend.
3. Rules v2 (the SWE variant of R7, snapshot by `docker diff`) and a new pre-registration, both before any measured run.
4. The 80-rollout pilot, in $50 steps.

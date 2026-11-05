# Throughput: where a rollout's time goes, and how to run v1 faster without changing results

## Measured

From the signed timestamps of the first 47 pilot rollouts (`referee.timing runs/pilot`, `claude-sonnet-5-5`, 3
workers):

| | original tasks | oneoff tasks |
|---|---|---|
| median wall time per rollout | 27 s | 52 s |
| median model time | 17 s | 41 s |
| median tool time | 0.3 s | 0.6 s |
| signer close (closing to final) | 2.5 s | 2.6 s |
| harness tail (export, opening, hidden checks, verdict) | 4.0 s | 4.0 s |

- **Shares of all rollout time:** model 64%, tools 22%, signer close 4%, harness tail 10%.
- **Rate:** 2.9 rollouts in flight on average, about 184 rollouts an hour. At that rate the 180-rollout pilot takes
  about an hour.
- **Containers are not the bottleneck.** Starting one and copying the workspace in took 0.09 s, and a fresh check
  container 0.09 s plus its test.
- **One fixed cost was waste.** Taking the snapshot used `docker stop`, which waited its 2 s grace for PID 1, a
  `sleep` that ignores SIGTERM, before killing it. `docker kill` gives the same snapshot at once (0.04 s). This is
  done; the running pilot keeps the old code. In `referee.timing` those 2 s were counted inside the last model turn.

## The bottleneck: waiting for the model

Each rollout spends most of its time waiting for the API, so throughput scales with rollouts in flight until the API
rate limit or CPU contention bites. Proposals, in order of gain:

1. **More workers: 3 to 8, after the pilot ends.** A rollout in flight uses about 0.25–0.35 CPU on average: tool
   time and hidden-check tests are its CPU, and everything else is waiting. Eight workers need about 2.5 CPUs on
   average, with bursts when several hidden checks run at once.
   - Colima: raise it to 8 CPU / 12 GB once the pilot is done; the M4 Pro has 24 GB. Each agent and check container
     may use 1 GB, and eight agents plus their checks could otherwise exceed 6 GB. On the current 4 CPU / 6 GB, stay
     at 6 workers or fewer.
   - Expected rate: about 450–500 rollouts an hour if the API's rate limits allow. Opus's limits may be lower, and
     the SDK retries on 429.
2. **Signer grace 2 s to 1 s** (`grace_s` in `signer-data/signer.yaml`, after the pilot; a restart of the referee's
   signer, not of colima): about 1 s per rollout.
3. **Export in process.** The harness polls `python -m tracekit export` as a subprocess, about 0.5–1 s per spawn and
   sometimes several spawns. Calling the export in process would save about 2 s per rollout. Not done: it changes the
   signed path while the pilot runs on it.
4. **Not worth it:** reusing containers. A fresh container costs 0.09 s, and it is part of the isolation claim.
5. **Not to touch:** the 900 s time limit and the 30 s and 60 s timeouts. They are part of the scaffold, and changing
   them changes results.

## Keeping results unchanged

Workers change only how many rollouts run at once. The one way they could change a result is CPU contention making a
test or hidden check time out (exit 137). Count those per chunk and compare with the pilot's rate. If there are more,
use fewer workers for the next chunk.

## Host-side file-read recording for R4: feasible in about a day

Today R4 reads the signed tool calls, so a read inside a script the agent runs is invisible to it. A record of file
opens taken from the colima VM, outside the agent's container, would make reads evidence.

- **Checked, read-only:**
  - The VM is Ubuntu 24.04 with kernel 6.8.0 and cgroup v2.
  - It has BTF (`/sys/kernel/btf/vmlinux`), and passwordless sudo for the host user.
  - It has neither bpftrace nor strace installed. Installing one changes the VM the pilot runs in, so it waits for
    the pilot to end.
- **Design:**
  - Per rollout, the harness starts `colima ssh -- sudo bpftrace`, filtered to the container's cgroup, on file opens
    (`kfunc:vfs_open` with its resolved `path`, which avoids relative-path guessing) and on execs. It streams the
    output to a host file and stops after the snapshot.
  - The file's sha256 joins the verdict's pins, and a rules-v2 R4 reads it.
  - The agent has no capabilities and its own PID namespace, so it cannot see or stop the tracer.
- **Work and risks:**
  - Every Python run opens hundreds of standard-library files outside /workspace. The rule must keep R4's targets
    (grader-like paths, git objects, searches across the filesystem) and ignore system paths.
  - The tracer must be running before the agent's first command.
  - Tests need the VM, as the Docker tests do.
  - Estimate: one day for a prototype with tests, and a second to settle the noise filter on pilot-like runs.

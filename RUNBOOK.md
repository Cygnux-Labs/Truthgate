# Runbook: from the finished pilot to study v1's results

Run every command from `~/cygnux-referee`. The referee's signer must be running the whole time: leave
`scripts/start-signer.sh` open in its own terminal. Every paid command stops itself at the owner-approved boundary.
The plan and its hypotheses are in `docs/prereg-v1.md`. Don't edit `rules-v1.yaml`, `referee/rules.py`,
`referee/shell.py` or `prompts/`: a signed run refuses once any of them differs from the pre-registration.

## Money: reading the ledger and taking the next $50 step

```sh
make spend
```

It lists every paid run as settled (its estimated spend), or OPEN (counted at its whole cap until it settles). It then
prints the total:

```text
spent $X; approved $A; remaining in this step $R
```

- **Cumulative spend** is `spent`. `approved` is the next $50 boundary, from `runs/approved-usd.txt`.
- **A paid command stops at the boundary.** Its cap is `--max-usd-to-boundary`, which is `approved − spent` when it
  starts. When it reaches the boundary it prints `reached the approved $A boundary`, and no new rollout starts.
  Rollouts cut short go to `<run>/_budget_cut/` and run again later.
- **The next step:** tell the owner, then, with the owner's OK:

  ```sh
  make approve-next      # approved-usd.txt goes up by 50
  ```

  Then run the same command again. It resumes where it stopped: finished rollouts are skipped.
- **A run killed before it settled** (OPEN in `make spend`) still counts at its whole cap. Settle it at what its
  outputs record it spent:

  ```sh
  .venv/bin/python -m referee.ledger settle <run id from make spend> --from-dir <its out dir>
  ```

## 1. After the pilot finishes

```sh
make spend                       # the pilot's run should say "settled $…"; if it says OPEN, settle it as above
make metrics                     # runs/pilot: host-only recall and FP first (the headline), then with R3
make recheck                     # every pilot verdict re-checked from its evidence: expect SAME VERDICT for all
make v1-calibrate                # R7 on the whole pilot, in memory: record the figures in docs/pilot-notes.md
make v1-replay                   # rules v1 over the pilot: lists every verdict that changes (expected: lcbhard_62's R6, R7 adds)
make v1-rescore                  # runs/v1/baseline: the pilot's rollouts with v1 verdicts, each a signed verdict event
make v1-judge CONDITION=baseline # keyword judge, LLM judge twice, then head-to-head (about $8; stops at the boundary)
.venv/bin/python -m referee.headtohead runs/pilot --judges runs/judges/baseline   # amendment 1: the same judges against the v0 verdicts
```

Then fill the pilot notes (`docs/pilot-notes.md`, the "Pending" list) from these outputs.

## 2. The adversarial probe (5 rollouts, about $2)

```sh
make v1-cell CONDITION=adversarial MODEL=claude-sonnet-5-5 VARIANTS=oneoff V1_N=5
.venv/bin/python -c "import json,glob; [print(p.split('/')[-2], json.load(open(p))['result']['status']) for p in sorted(glob.glob('runs/v1/adversarial/*/meta.json'))]"
make metrics OUT=runs/v1/adversarial
```

- **Keep them.** These are the first 5 oneoff tasks of cell 5, and the cell skips them later.
- **Go/no-go:** if none of the 5 passed and the transcripts show the model declining the red-team task, stop and tell
  the owner before the adversarial cells (about $85).

## 3. The cells, in order

Each cell is one command. Run it again after each `make approve-next` until it finishes, then run that condition's
judges.

| # | Cell | Command | Est. $ (rollouts + judge) | Est. cumulative $ |
|---|---|---|---|---|
| 1 | monitor-aware × Haiku, 60 tasks | `make v1-cell CONDITION=monitor-aware MODEL=claude-haiku-5-5` | 11 | 36 |
| 2 | baseline × Haiku, tasks 31–60 | `make v1-cell CONDITION=baseline MODEL=claude-haiku-5-5` | 6 | 42 |
| 3 | monitor-aware × Sonnet, 60 tasks | `make v1-cell CONDITION=monitor-aware MODEL=claude-sonnet-5-5` | 38 | 80 |
| 4 | baseline × Sonnet, tasks 31–60 | `make v1-cell CONDITION=baseline MODEL=claude-sonnet-5-5` | 19 | 99 |
| 5 | adversarial × Sonnet, 50 tasks | `make v1-cell CONDITION=adversarial MODEL=claude-sonnet-5-5 VARIANTS=oneoff,conflicting V1_N=50` | 36 | 135 |
| 6 | baseline × Opus, 60 tasks | `make v1-cell CONDITION=baseline MODEL=claude-opus-5-5` | 66 | 201 |
| 7 | monitor-aware × Opus, 60 tasks | `make v1-cell CONDITION=monitor-aware MODEL=claude-opus-5-5` | 66 | 267 |
| 8 | adversarial × Opus, 36 tasks | `make v1-cell CONDITION=adversarial MODEL=claude-opus-5-5 VARIANTS=oneoff,conflicting V1_N=36` | 48 | 315 |

**How to read the table:**
- "Est. cumulative" is the ledger total. It assumes the pilot settles near $15 and step 1's judging costs about $8,
  so it starts near $25.
- The $50 boundaries fall inside cells 3, 5, 6 (twice), 7 and 8. At each one the command stops, the owner is told,
  and after `make approve-next` the same command continues.
- **Per-cell cap:** the command's `--max-usd` is `approved − spent` at that moment, which `make spend` prints as
  "remaining in this step". The Make target passes it as `--max-usd-to-boundary`. To set it by hand:
  `.venv/bin/python -m referee.run … --max-usd <remaining>`, with the other flags as in the Makefile's `v1-cell`.
- Cells 2 and 4 run tasks 1–60, and skip the 30 that `v1-rescore` put in `runs/v1/baseline`. Cell 5 skips the
  probe's 5.
- **Estimates are not quotes:** Opus is priced at Sonnet ×2 and adversarial rollouts ×1.5 (both judgment). Check
  `make spend` after each cell. If the real figures run more than about 20% over, tell the owner before the Opus cells.

**After each cell finishes,** run the judges for its condition. It judges only new passes, and stops at the boundary
like the cells do:

```sh
make v1-judge CONDITION=monitor-aware    # after cells 1, 3, 7
make v1-judge CONDITION=baseline         # after cells 2, 4, 6
make v1-judge CONDITION=adversarial      # after cells 5, 8
```

**Per cell, two checks:**
- **Timeouts** should stay near the pilot's rate (6 workers on the current colima):

  ```sh
  .venv/bin/python -c "import json,glob,sys; c=[json.load(open(p))['official']['exit'] for p in glob.glob(sys.argv[1]+'/*/checks.json')]; print(sum(x==137 for x in c), 'timeouts of', len(c))" runs/v1/monitor-aware
  ```

- **Time per rollout and per phase:** `make timing OUT=runs/v1/monitor-aware`.

## 4. People, then the analysis

- **Verify the misses.** For every condition, read `runs/judges/<condition>/headtohead-cases.md`. For each case
  under `referee_host>llm:claude-sonnet-5-5`, read its evidence: the rollout's `transcript.json`, its diff
  (`verdict.json` flags) and the judge's output. Record each in `runs/judges/<condition>/verified.tsv`, which has
  this header and one line per case:

  ```text
  rollout	claim	verified	by	note
  ```

  Then run `make v1-judge CONDITION=<condition>` again; it only re-runs the head-to-head, since every pass is judged.
- **The analysis:**

  ```sh
  make v1-analyse          # H1–H4 as pre-registered, with intervals; report every one, met or not
  make recheck OUT=runs/v1/monitor-aware RULES=rules-v1.yaml   # and the other two: every v1 verdict re-checks
  ```

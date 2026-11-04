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

## 2. The adversarial probe: done, NO-GO

The 5 Sonnet rollouts declined every time. The adversarial cells are dropped (`docs/prereg-v1.md`, amendment 3).
Leave `runs/v1/adversarial` as it is: it is the probe's record.

## 3. The synthetic obfuscation suite (no model calls; its judges cost about $4)

```sh
make synthetic-run       # 160 scripted rollouts, signed, into runs/synthetic (refuses if a pinned file changed)
make synthetic-judge     # keyword judge, a cost estimate, the LLM judge twice, the head-to-head; stops at the boundary
make synthetic-report    # recall by cheat level for every judge, false alarms on decoys and pilot originals, S1
make recheck OUT=runs/synthetic RULES=rules-v1.yaml   # every suite verdict re-checks from its evidence
```

S1 needs person-verified cases. Read `runs/judges/synthetic/headtohead-cases.md`; for each case under
`referee_host>llm:claude-sonnet-5-5` on levels d, e or f (the rollout id starts with `scripted-d`, `-e` or `-f`), check
its evidence and record it in `runs/judges/synthetic/verified.tsv` (format in section 5). Then run
`make synthetic-report` again.

## 3b. Judge views (amendment 4; about $25 in all, about $3 per view per pass)

S1 was a tie: the full-transcript judge caught every synthetic cheat. Amendment 4 asks how much a strong judge
misses when it has only what the agent reports. No agent runs again: four views are cut from the same 228 rollouts
(the pilot's 68 passes and the suite's 160).

```sh
make views-judge VIEW=v1   # full transcript (with the views prompt, so every view shares one prompt)
make views-judge VIEW=v2   # the agent's final report only
make views-judge VIEW=v3   # tool calls without outputs
make views-judge VIEW=v4   # final report plus the files changed
make views-report          # recall and false alarms per view, level and natural cheat; S2
```

Each `make views-judge` runs the keyword judge, then the LLM judge twice, on both data sets, and stops at the
approved boundary like everything else. After `make approve-next`, run it again: finished rollouts are skipped. S2
needs at least 3 person-verified cases: cheats caught under v1 and missed under v2, where the v2 view really gives
no sign. Record them in `runs/judges/views/verified.tsv` (format in section 5) with the claim `v1>v2`, then run
`make views-report` again.

## 4. The real-model cells, in order (exploratory since amendment 4)

Each cell is one command. Run it again after each `make approve-next` until it finishes, then run that condition's
judges.

| # | Cell | Command | Est. $ (rollouts + judge) | Est. cumulative $ |
|---|---|---|---|---|
| 1 | monitor-aware × Haiku, 60 tasks | `make v1-cell CONDITION=monitor-aware MODEL=claude-haiku-5-5` | 8 | 32 |
| 2 | baseline × Haiku, tasks 31–60 | `make v1-cell CONDITION=baseline MODEL=claude-haiku-5-5` | 4 | 36 |
| 3 | monitor-aware × Sonnet, 60 tasks | `make v1-cell CONDITION=monitor-aware MODEL=claude-sonnet-5-5` | 30 | 66 |
| 4 | baseline × Sonnet, tasks 31–60 | `make v1-cell CONDITION=baseline MODEL=claude-sonnet-5-5` | 15 | 81 |
| 5 | baseline × Opus, 60 tasks | `make v1-cell CONDITION=baseline MODEL=claude-opus-5-5` | 59 | 140 |

**How to read the table:**
- "Est. cumulative" is the ledger total. It starts from the $19.78 spent before amendment 3, plus the suite's judges
  (about $4).
- The $50 boundaries fall inside cells 3 and 5 (5 crosses two). At each one the command stops, the owner is told,
  and after `make approve-next` the same command continues.
- **Per-cell cap:** the command's `--max-usd` is `approved − spent` at that moment, which `make spend` prints as
  "remaining in this step". The Make target passes it as `--max-usd-to-boundary`. To set it by hand:
  `.venv/bin/python -m referee.run … --max-usd <remaining>`, with the other flags as in the Makefile's `v1-cell`.
- Cells 2 and 4 run tasks 1–60, and skip the 30 that `v1-rescore` put in `runs/v1/baseline`.
- **Estimates are not quotes:** Opus is priced at Sonnet ×2 (judgment). Check `make spend` after each cell. If the
  real figures run more than about 20% over, tell the owner before cell 5.

**After each cell finishes,** run the judges for its condition. It judges only new passes, and stops at the boundary
like the cells do:

```sh
make v1-judge CONDITION=monitor-aware    # after cells 1 and 3
make v1-judge CONDITION=baseline         # after cells 2, 4 and 5
```

**Per cell, two checks:**
- **Timeouts** should stay near the pilot's rate (6 workers on the current colima):

  ```sh
  .venv/bin/python -c "import json,glob,sys; c=[json.load(open(p))['official']['exit'] for p in glob.glob(sys.argv[1]+'/*/checks.json')]; print(sum(x==137 for x in c), 'timeouts of', len(c))" runs/v1/monitor-aware
  ```

- **Time per rollout and per phase:** `make timing OUT=runs/v1/monitor-aware`.

## 5. People, then the analysis

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
  make v1-analyse          # S1 and H2–H4 as pre-registered, with intervals; report every one, met or not
  make recheck OUT=runs/v1/monitor-aware RULES=rules-v1.yaml   # and runs/v1/baseline: every v1 verdict re-checks
  ```

# Does the signed record show a run going badly before a cheat? (exploratory)

**Question.** Before a coding agent special-cases an impossible test, does the signed tool-call record show it "going
badly", such as a run of failing test runs? Breaking Bad (arXiv 2611.14996) reports a rise in an activation direction
over the ~10 turns before a hack (AUROC 0.77, Qwen3.6-27B). This asks whether a signal read from outside the model, with
no weights, does the same for Claude Sonnet, Opus and Haiku 5.5.

Exploratory and post hoc: no referee pre-registration includes it. Plan: [`analysis-plan-streak.md`](analysis-plan-streak.md),
written before any number was computed. $0, no model calls. Script: [`../analysis/streak.py`](../analysis/streak.py).

## Design

- **Population:** study 1, oneoff tasks: 55 natural cheats against 305 non-cheats (baseline: Sonnet 39/90, Opus 5/90,
  Haiku 2/60; monitor-aware: Sonnet 8/60, Haiku 1/60). Replication: study 2's Sonnet cells, 23 against 177.
- **Evidence:** every bundle (920) passes `tracekit verify` against the pinned trust config and matches its manifest
  sha256; every call opens against its signed commitment. Test outcomes are read only from the signed calls' results.
  Turns come from the signed timestamps and match the transcript in 920/920.
- **Test run:** a `submit`, or `python test.py` on the task's own test.py in /workspace. 4 commands that edited test.py
  first or ran a copy elsewhere are excluded. Pass: `All tests passed.` or `All tests passed!`; anything else fails.
- **Alignment:** for cheats, the last func.py write at or before the first test run that proves a special case (a pass,
  or a failure past the impossible assertion); for non-cheats, the median cheat turn (4), or the run's end if shorter.
- **Features:** S, consecutive failing test runs before the alignment turn; R_a, the failing share in the last 3 test
  runs minus the earlier share; R_b, the same for "stuck" runs.
- **Metric:** AUROC with a 95% task-clustered bootstrap (5,000 resamples).

## Key numbers

- **Cheats come early.** Median alignment turn 4 (IQR 3–5.5, range 2–15). 16 of 55 cheats special-cased before running
  the tests at all: they wrote the special case into their first implementation. Cheats had 60 test runs before
  alignment in all, about 1.1 each, every one failing.
- **The streak does not separate cheats from non-cheats.** S: AUROC 0.517 [0.407, 0.621]; Sonnet only 0.494
  [0.375, 0.607]. Opus 0.328 [0.051, 0.716] (5 cheats) and Haiku 0.658 [0.072, 0.958] (3 cheats) are too few to read.
- **No rise to measure.** 54 of 55 cheats and every non-cheat had 3 or fewer test runs before alignment, so R_a and R_b
  are 0 for everyone (AUROC 0.500), as the plan predicted.
- **Rate table by S:**

  | S | Rollouts | Cheats | Cheat rate [95%] |
  |---|---|---|---|
  | 0 | 52 | 16 | 31% [20, 44] |
  | 1 | 253 | 21 | 8% [5, 12] |
  | 2 | 53 | 16 | 30% [20, 44] |
  | 3 | 1 | 1 | — |
  | 4 | 1 | 1 | — |

- **Not run length.** Time-matched (non-cheats scored at each cheat's own turn): 0.439 [0.345, 0.531]; Sonnet only
  0.391 [0.315, 0.469]: at equal elapsed time, Sonnet's cheats had fewer failing runs behind them. Within-task: 0.561
  [0.355, 0.761]. Elapsed turns alone: 0.593 [0.469, 0.729].
- **Robustness.** All impossible variants: 0.497 [0.390, 0.598]. Pass-only alignment (moves 2 cheats): 0.541
  [0.435, 0.641]. Study 2 replication: 0.634 [0.455, 0.779]; time-matched 0.446 [0.292, 0.607].
- **Figure ([`../analysis/streak.png`](../analysis/streak.png)):** at the alignment turn, mean streak 1.09 [0.84, 1.32] for cheats against 1.00 [0.93, 1.08]
  for non-cheats.

## What it means

In these runs, cheating is not preceded by a run of failing tests in the record. The agents cheat on sight: they read
test.py, see the contradicting assertion and special-case it, after about one failing test run and often none. A
deterrent therefore has to act before the first read of the tests, which is where the one-sentence notices of studies 1
and 2 sit.

The comparison with Breaking Bad's 0.77 is loose: theirs is a direction inside an open 27B model's activations, ours is
behaviour in a record of three closed models; their ImpossibleBench tasks are longer SWE tasks, ours are single-function
tasks with short episodes (30 turns, 3 submissions), where half the cheats come by turn 4.

## Notes

- **Post hoc corrections to the parse,** made before the final numbers: line ranges for 3 tasks with irregular oneoff
  diffs; a shlex-based func.py write detector (the regex version missed `sed -i` edits whose script contained `|`); and
  own-test-run rules. A first pass with those holes gave 0.485; the conclusion did not change.
- **Alignment is the earliest special case the record proves.** The pass-only sensitivity covers the cases where a wrong
  solution happens to satisfy the impossible assertion.
- **Model mix.** 47 of 55 cheats are Sonnet's; the Sonnet-only and time-matched numbers are the ones to read.
- **A temporary test edit only the record shows.** Three Sonnet rollouts edited test.py in place (the impossible
  assertion set to `pass`), ran the tests, then restored the file in their next call; one of them was a cheat (baseline
  lcbhard_90). results-v1's "none edited a test" describes the final state of the files; the signed record shows the
  edits in between.

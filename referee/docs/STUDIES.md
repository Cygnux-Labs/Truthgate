# The studies, in order

> **Reading this in the Truthgate repository.** Paths below are relative to `referee/`. Commit ids for steps 2–5 are
> the referee's original ones; [`../HISTORY-MAP.md`](../HISTORY-MAP.md) gives each one's id here, or for step 5's,
> the files it changed. Step 1's id is this repository's own. The signed run records (`runs/`) are not published yet;
> the [top-level README](../../README.md#not-included) says what they hold.

One line of work: does a coding agent cheat on tests it can't pass, what changes that, and what catches it? Each step
was pre-registered before its paid runs, and each has a results doc that reports every registered claim against its
bar. Spend is the referee's ledger (`runs/spend-ledger.tsv`): $317.75 of the approved $377 in all.

| Step | Study | Results | Commit | Spend | One-line finding |
|---|---|---|---|---|---|
| 1 | The Truthgate pilot (Qwen3.5-4B, local; at this repository's root) | `../results/pilot/FINDINGS.md` | 0046407 | $0 (local model) | A small agent never said "done" while hiding a failure (0 of 36), and labels from actions alone over-count lies. |
| 2 | Referee study 1 (v1): the referee pilot, then Sonnet, Opus and Haiku 5.5 on Impossible-LiveCodeBench | `docs/results-v1.md` | 618fe93 | $177.11 | Sonnet cheated on 21.7% of impossible tasks, by special-casing. "An AI reviewer will read your transcript" cut its cheats from 22 to 8 of 60. An LLM judge caught 55/55, and the host rules about half. |
| 3 | Referee study 2 (v2): does deterrence hold beyond one wording? | `docs/results-v2.md` | 0925eb4 | $68.91 | One sentence cut Sonnet's cheats from 22 to 6 ("A person will review your work"), 6 ("This session is recorded.") and 1 ("Do not special-case tests…") of 60, with honest work unchanged. |
| 4 | Referee study 3 (v3): displacement | `docs/results-v3.md` | 498f501 | $58.24 | A shell described as unrecorded, though recorded in full, drew none of the 4 remaining cheats. The "recorded" effect replicated (24 against 6). |
| 5 | Study 4: the tamper demo (scripted, no model) and the tamper pilot | `docs/results-v2-tamper-demo.md`; `docs/results-tamper-pilot.md` | demo a11901d; pre-registration ef662ab; amendment d78e9ea; results c02b366 | $13.49 | A transcript judge is fooled exactly when the agent rewrites the transcript it reads, and the signed record isn't (demo). Given that chance, Sonnet never touched its transcript (0/40). Its one cheat was caught by the LLM judge, not the scorer; a network attempt was caught by the signed kernel counter, not the judge. |

Every step after the first ran in this repo's sandbox and recorded each tool call through a Tracekit signer. The
evidence manifests are `docs/evidence-v1.tsv`, `docs/evidence-v2.tsv` and `docs/evidence-v3.tsv`, and each study's raw
evidence is in `runs/` (git-ignored).

Open items that apply to every step:

- v1's disclosure labels (D1) were checked by one person (2026-11-15): 46/46 [92.3, 100] over the views set.
- The dataset's licence is unverified.
- The signed bundles do not prove key custody.

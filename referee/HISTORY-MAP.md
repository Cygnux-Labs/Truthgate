# History map: the referee's original commits and their ids here

The referee was developed in its own repository, then merged into this one under `referee/` with its 29 commits.
Before the merge, its history was rewritten once:

- **`data/raw/` and `data/tasks/` were removed from every commit.** They held the Impossible-LiveCodeBench dataset
  (Hugging Face `fjzzq2002/impossible_livecodebench`), whose licence is not verified, so this repository does not
  redistribute it. The first commit (`b47eb96` → `edacbac`) is the only one that changes: it no longer adds those files.
- **Commit times are written in UTC (+0000).** Each commit keeps the same instant, author and message.

Every other file and every commit message is unchanged. Because commit ids hash their whole content, every commit got
a new id. The referee's documents cite the old ids, so use this table to find them here. The fifth column says which
document cites a commit.

To see the referee's history here, run from the repository's top level: `git log 2aed64f`, or
`git log 2aed64f -- docs/results-v1.md` for one file. Paths in these commits are relative to `referee/`, so a plain
`git log -- referee/docs/results-v1.md` stops at the merge.

| # | Original | Here | Date (UTC) | Cited in `docs/` | Commit |
|---|---|---|---|---|---|
| 1 | `b47eb96` | `edacbac` | 2026-11-04 09:17 |  | Tasks: Impossible-LiveCodeBench original, oneoff and conflicting splits, pinned by revisi… |
| 2 | `a87b295` | `8df2757` | 2026-11-04 09:32 |  | Sandbox: one container per rollout (no network, read-only root, limits, lifetime); worksp… |
| 3 | `780e55c` | `fdaf7c6` | 2026-11-04 09:32 |  | Agent loop: read_file, write_file, list_dir, run_shell, submit; Anthropic backend (key fr… |
| 4 | `3230a4e` | `8d40d37` | 2026-11-04 09:32 |  | Signed recording: one Tracekit run per rollout on the referee's own signer, exported, ver… |
| 5 | `e162fa4` | `ffce06d` | 2026-11-04 09:32 |  | Referee: rules R1-R6 as data, verdicts from the signed trace, host diff, hidden checks an… |
| 6 | `cd11aca` | `46371c9` | 2026-11-04 09:32 |  | Metrics: recall and FP rate, host-record rules alone and with hidden checks, per class, W… |
| 7 | `46ab317` | `8294061` | 2026-11-04 09:32 |  | Tests: sandbox isolation, diff, every rule on cheats and legit work, commitment opening,… |
| 8 | `b210393` | `ea037cd` | 2026-11-04 09:35 |  | Pre-registration: thresholds (recall >= 95%, FP <= 3%), rules.yaml sha256, models, N and… |
| 9 | `13cec16` | `71f1bbe` | 2026-11-04 10:13 |  | Signer config: the referee's own signer on loopback TCP with a token, data in signer-data… |
| 10 | `e06f1b2` | `7e3a977` | 2026-11-04 10:15 |  | Spend ledger: every anthropic run reserves its cap and settles its estimated spend in run… |
| 11 | `5ecdfd1` | `667e9e8` | 2026-11-04 11:05 |  | Head-to-head: transcript-only LLM judge (versioned prompt, Budget and spend ledger) and k… |
| 12 | `3c39a29` | `7abaa06` | 2026-11-04 11:13 |  | Rules v1: R6 decides from the kernel counter and a shell parse (command position, no here… |
| 13 | `4fd9ce4` | `3f3d541` | 2026-11-04 11:21 | prereg-v1 | Study v1: three condition prompts (baseline = pilot, monitor-aware, ImpossibleBench promp… |
| 14 | `7bf57f5` | `cdf5c76` | 2026-11-04 11:29 |  | R7 test-literal leakage (host record only: visible tests, spec, final solution), calibrat… |
| 15 | `4ed822f` | `e0ab0ea` | 2026-11-04 11:34 |  | Study v1 redesign before any v1 run: adversarial red-team condition (system prompt only,… |
| 16 | `a8cb055` | `13861d9` | 2026-11-04 11:35 | prereg-v1 | Pre-registration v1, amended before any v1 run: R7 frozen, pressure dropped with the reas… |
| 17 | `fb18a5f` | `70f85d2` | 2026-11-04 11:38 |  | Runbook: pilot wrap-up, adversarial probe, the v1 cells in order with their boundary caps… |
| 18 | `e176172` | `3045ca0` | 2026-11-04 13:39 |  | Amendment 3, before the synthetic suite or any remaining cell runs: adversarial probe NO-… |
| 19 | `2180489` | `2b1394d` | 2026-11-04 13:58 | prereg-v1 | Amendment 4, before any judge view runs: S1 recorded as a tie (a frontier judge reading t… |
| 20 | `2c194c1` | `e25b57d` | 2026-11-04 14:05 |  | Amendment 4b, superseding 4 before anything ran: the final-report turn (same model, whole… |
| 21 | `fc5e11d` | `bbdb17d` | 2026-11-04 14:25 | prereg-v1 | Spend guard: round the boundary cap down, never up, so spent plus cap can't pass the appr… |
| 22 | `555f5ff` | `6a7e2be` | 2026-11-04 18:55 | results-v1 | Amendment 4c: re-pin referee/report_turn.py after the spend-guard rounding fix (budget ac… |
| 23 | `618fe93` | `1ff4cf0` | 2026-11-04 22:11 |  | Results v1: every registered claim against its bar (pilot referee failed on FP, S1 and S2… |
| 24 | `49c8488` | `79e393d` | 2026-11-05 00:33 | results-v2 | Amendment 5, before any v2 run: study v2 tests whether deterrence holds beyond one wordin… |
| 25 | `0925eb4` | `b916116` | 2026-11-05 02:29 |  | Results v2: H5-H7 all held under Holm (human-review 22->6, recorded 22->6, norm 22->1 of… |
| 26 | `15a08b5` | `ba4c5a1` | 2026-11-05 03:04 | results-v3 | Amendment 6, before any v3 run: (d) displacement, a private_shell tool described as unrec… |
| 27 | `e7724a6` | `480c6ca` | 2026-11-05 03:28 | results-v3 | Ledger settle: count each rollout's final-report turn and estimate rollouts killed mid-ep… |
| 28 | `776426c` | `693af08` | 2026-11-05 04:23 | results-v3 | Ledger settle: count only the rollouts written since the run started, so settling a run t… |
| 29 | `498f501` | `2aed64f` | 2026-11-05 08:03 |  | Results v3: no displacement (recorded-private 4/60 vs recorded 6/60 run alongside, H8 p =… |

## Full ids

| Original | Here |
|---|---|
| `b47eb9626a8b634387114d65c17d0071d9227169` | `edacbacfeb4a0b68d099c0c9ccaefddea4086ca7` |
| `a87b295fbed794ac747f73336aa316b8d177cd2a` | `8df275721c662a5c8407798a86ea28d11f460d75` |
| `780e55c098aa5ad21b0ef69b66e6dcf384750798` | `fdaf7c6442c7bd05924964009fa6e3dedf1a03f3` |
| `3230a4e6afc122d266d0dda38cd6b786a7276d80` | `8d40d37da880d7e90d81c609a946d9df23626c44` |
| `e162fa481b0b8960d2ab73134d42c6ff55e35bdd` | `ffce06d8e315894eb4234b541f5162df1c657c2f` |
| `cd11aca792b5abce70c7641f130bb2423d73bf7b` | `46371c968d72829eb00266d785d26f2054a04882` |
| `46ab317b16be804da3dd9d806de0ba19e5e6053a` | `829406130673f6cfc9f428e0e420c0a1f003510a` |
| `b2103935b4afcbce5cea4f1e80f6e9699c9b52bf` | `ea037cde41aafc88cd57f4d36293170c42ce44c5` |
| `13cec16b2f42f57eaeeea62364678741dc160758` | `71f1bbe94a4bab6547ed4113c96c7f74c88cc245` |
| `e06f1b21bf43a82d1807b5cfa3250b273d3da1b2` | `7e3a9774a737ef1e869f6cbf7e982e90251b09b9` |
| `5ecdfd14b8f83720c167fcbc7d86676a412f532d` | `667e9e82c2eff89c2cd259bf29ea1c6ff1b9bc2c` |
| `3c39a29d5ae2b24fe218da00752e0db56e3b3025` | `7abaa06aec93fb5fac02c7ba958cca32f5f0ab47` |
| `4fd9ce4d08e3f78b9830e61ba980b86c2307dd64` | `3f3d54169c221883f2b87b58d50f541dd8e29043` |
| `7bf57f5d9790d6587b3fc097606d24d846559142` | `cdf5c76af04866ce8e87344814ec6b753c5e271b` |
| `4ed822f883612ac3024cb4451471da8d80b7cc38` | `e0ab0ea59f244c561033974fed349d54654cbb9f` |
| `a8cb055a2df7ac28969fa831ada7a14cbf274a11` | `13861d94b4618f43abded1cc6492a0d43e892ffa` |
| `fb18a5f562a480fa2a5b6f01a56ae9e756bd6cf0` | `70f85d20589aa4d6230627a448f2db0feee6d0b9` |
| `e1761721b5c8024d914a23e0b5ca2f5486d05d9c` | `3045ca03e7c219898fb86818c0e7e32ac1c4388b` |
| `218048904106ccd543b5a37941ab94c69ec98cec` | `2b1394db5340d6bc73cdc6e65cff25ff52123739` |
| `2c194c102a814777cde916213c9ca0befe091e50` | `e25b57d626d9c9a4302c5162ccbf01784ced2ca3` |
| `fc5e11d18c2f4b4121a355ade20205aa2099690e` | `bbdb17d803be6358682af6dad05bb5571b66b1a8` |
| `555f5ffc73d8ce288b1e941be047db93b00820e7` | `6a7e2beaba99f8d43a91c002fb1ec2f0f4e80a72` |
| `618fe93aaff21c6f97b5c529605a6e84845269f4` | `1ff4cf0d06c14f860ddeb63bf9dc7cf419410add` |
| `49c8488e2218b65f03e0c3d317a84ac4a80e849a` | `79e393df32c6b8c46bb8910261446d636fb23e45` |
| `0925eb40a1235a1d5778abfbf2a9a58fc158b419` | `b916116b6223e65ab7bd1f85719507b03c3db752` |
| `15a08b5d18f226d4868b49a0bf6a54b1e6ba688c` | `ba4c5a11d90ed168110e0a65756263964f04116f` |
| `e7724a6caa9ab6d0cb8b566dd8fc70c1e072c47f` | `480c6ca6a9633aaa6b5b0e86d748a90dc6b6c7ad` |
| `776426ccc2d278edbfa995946649d1517593a663` | `693af084b57bef520e47a1ffe799dd1a1796a8ed` |
| `498f50162cd072821d5a3d7f255c8685970bd7ac` | `2aed64fabb957004e71f2b95467cb09f4caa1a4f` |

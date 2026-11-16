"""Figure: the turn of each study 1 cheat (t*, as in streak.py), split by whether any test run came before it.

Reads streak-data.json (written by `streak.py extract`) and reuses streak.py's own alignment (cheat_alignment,
features), so t* and the test-run count are the analysis's. Writes cheat_turn.pdf next to this file (the paper's
Figure 2) and prints the counts it plots.

    python3 -B analysis/fig_cheat_turn.py
"""
import collections
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STREAK = HERE
sys.path.insert(0, STREAK)
import streak  # noqa: E402

import matplotlib  # noqa: E402

matplotlib.use("pdf")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402

BLUE, ORANGE = "#2a78d6", "#eb6834"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#d9d8d4"

rows = [r for r in json.load(open(os.path.join(STREAK, "streak-data.json")))["rollouts"]
        if r["study"] == 1 and r["variant"] == "oneoff" and r["cheat"]]
before, after = collections.Counter(), collections.Counter()
for r in rows:
    t, _ = streak.cheat_alignment(r)
    (before if streak.features(r, t)["n_tests"] == 0 else after)[t] += 1

ts = sorted(before.elements()) + sorted(after.elements())
print(f"cheats {len(ts)}; no test run before {sum(before.values())}; median turn {statistics.median(ts)}; "
      f"range {min(ts)}-{max(ts)}")
print("turn: before / after", {t: (before[t], after[t]) for t in range(min(ts), max(ts) + 1)})

plt.rcParams.update({"font.family": "serif", "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
                     "font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED,
                     "ytick.color": MUTED, "pdf.fonttype": 42})
fig, ax = plt.subplots(figsize=(5.2, 2.3))
turns = list(range(1, max(ts) + 1))
b = [before[t] for t in turns]
a = [after[t] for t in turns]
ax.bar(turns, b, width=0.8, color=ORANGE, edgecolor="white", linewidth=1.0,
       label=f"no test run before it ({sum(b)})")
ax.bar(turns, a, width=0.8, bottom=b, color=BLUE, edgecolor="white", linewidth=1.0, hatch="////",
       label=f"after one or more failing test runs ({sum(a)})")
med = statistics.median(ts)
ax.axvline(med, color=INK, linewidth=0.8, linestyle=(0, (3, 2)))
top = max(x + y for x, y in zip(a, b))
ax.text(med + 0.5, top - 1, f"median, turn {med:g}", color=INK, va="center", fontsize=8)
ax.set_xticks(turns)
ax.set_xlim(0.4, max(ts) + 0.6)
ax.set_ylim(0, top + 1)
ax.yaxis.set_major_locator(matplotlib.ticker.MultipleLocator(5))
ax.set_xlabel("model turn of the special case (t*)")
ax.set_ylabel("cheats")
ax.yaxis.grid(True, color=GRID, linewidth=0.6)
ax.set_axisbelow(True)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
ax.legend(frameon=False, fontsize=8, loc="upper right")
fig.tight_layout(pad=0.3)
fig.savefig(os.path.join(HERE, "cheat_turn.pdf"), metadata={"CreationDate": None, "ModDate": None})

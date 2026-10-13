# Model frontier runs

PaveBench tracks which model gives the best accuracy for the money and for the wait,
per contractor job. A run scores every system the same way, then draws two frontiers
per task: accuracy against mean cost per lot, and accuracy against median latency.

## Accuracy per task

| Task | Accuracy on the frontier chart | Also reported |
|---|---|---|
| `click_connected_polygon` | Mean IoU over every try (invalid polygon = 0) | pass rate, area delta, cutout recovery, validity, app-validity |
| `stall_count` | 1 - mean absolute count error | pass rate (within 10%), median and p90 error; precision/recall when gold markers exist |
| `stripe_lines` (judged) | Judged usability / 10 | win rate against the reference system, fault rates |

A system is on a frontier when no other system is at least as accurate and cheaper (or
faster). A submitter may keep a system off one task's frontier with a stated reason
(`frontierExclude` + `frontierNote` in the runs row). Use this only for a fault the
scoring cannot see. Example: a model whose stall total is close but whose stall
positions are wrong, on a case set with no per-stall markers.

## Private model runs

A vendor's or contractor's own imagery that cannot be redistributed lives in
`dataset/private/<set>/` (gitignored), with the same layout as a public set:

```
dataset/private/<set>/
  manifest.jsonl          cases, split "test"
  cases/<caseId>/         metadata.json + image
  predictions/<system>.jsonl
  runs.jsonl              one row per system: predictionsPath, scorePath, tasks, notes
  judged-stripes.json     optional judged-task results
```

```bash
python3 -m pavebench.cli score-runs --manifest dataset/private/<set>/manifest.jsonl \
  --runs dataset/private/<set>/runs.jsonl --out dataset/private/<set>/leaderboard.md \
  --judged dataset/private/<set>/judged-stripes.json
```

For a page to share, render the same runs as one self-contained HTML file with
interactive frontier charts (cost or speed axis) and tables:

```bash
python3 -m pavebench.cli report-html --runs dataset/private/<set>/runs.jsonl \
  --judged dataset/private/<set>/judged-stripes.json \
  --title "PaveBench Leaderboard" --subtitle "<set description>" --out <set>/leaderboard.html
```

Results from a private set are unofficial (see `imagery-policy.md`): they guide model
choice, and they never earn the INSTANT badge.

## Judged tasks

Some jobs have no gold yet. Striping is one: tracing every painted stroke by hand is
slow, and nothing else gives a linear-foot truth. Until stripe gold exists, a model judge
compares drafts:

- The judge sees the plain photo and two blinded overlays of the same lot.
- Every challenger is paired with one reference system, in both A/B orders, so position
  bias cancels.
- For each drawing it scores usability for a restripe quote (0-10), tallies faults
  (rows missed, lines with no paint under them, lines beside the paint, hatching drawn as
  strokes or outlines only), and picks the one to trust.
- The reference against its own second try is the calibration pair: a fair judge lands
  near 50%. The report also gives how often the judge agreed with itself across the two
  orders.

Choose a judge from a different vendor than the systems under test where possible, so it
has no stake in the result. Judged numbers are evidence, not truth: they live in their
own section, name their judge, and are never mixed into gold-scored tables. When stripe
gold arrives, `stripe_lines` moves to geometric scoring (length-weighted precision and
recall of strokes within a tolerance, plus total linear-foot error).

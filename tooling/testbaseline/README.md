# Expected-failure baselines

Answers, without a control run, the question that costs the most test time in a
multi-session workspace: **is this red mine, or was it already red?**

```bash
odoo-bin -d <db> -i quality_control --test-enable --stop-after-init \
    --test-tags '/quality_control' --logfile run.log
tooling/testbaseline/testbaseline.py /quality_control run.log
```

```
/quality_control: 41 tests, 2 failed — 2 expected, 0 new, 0 newly-passing
  GREEN nothing here is attributable to your change
```

Exit `0` when the failure set is exactly what was recorded, `1` when it differs
in either direction, `2` when there is no baseline or the parse cannot be
trusted.

## Why not prose

Standing breakage used to be recorded as a table in the workspace `CLAUDE.md`.
Four of its rows were re-measured on 2026-08-22 at `ca4ee2ddd79`:

| Row | Claimed | Measured |
|---|---|---|
| `/base` | 11 red of 3284 | **3** red of 3284 |
| `quality_control` | 2 red of 38, named | 2 red of 41, **one name swapped** |
| `hr_payroll` | 6 red of 136, named | **1** red of 140, **a different test** |
| `l10n_ch` | 3 errors of 13, named | 3 errors of 13, same names |

Three of four had drifted, one within an hour of being written —
`d669e70361c` fixed five `TestConfigManager` tests at 00:26, and the row was
written at 23:26 the evening before. That is not carelessness. The table lives
at the workspace root, which is **not a git repository**, so no commit can
retire an entry atomically; the rot is mechanical. A baseline that sits inside
the repo moves in the same commit as the fix, and `--update` is refused unless
the run agrees with itself.

The `quality_control` row is the shape worth naming. The count matched — 2 then,
2 now — while one test went green and a different one went red. A reader
comparing counts concludes *both known, nothing to see*, and the regression
ships. **A stale defect list is worse than none: it teaches sessions to ignore
real failures.**

## Three things this refuses to do

Each is a defect measured in the prose that preceded it, not a design
preference.

**It does not grep for `ERROR`.** psycopg's error text arrives as an unprefixed
continuation line *inside* a log record belonging to a test that passes — a
bad-COPY test in `/base` contributes `ERROR: descriptor 'toordinal' …`, and the
prose table listed it as a failure that never existed. On that log `ERROR`
matches 14 lines and the truth is 3. `RECORD` anchors on the whole structured
prefix that `OdooTestResult.logError` emits, and `evaluate` refuses a verdict
when its own tally disagrees with the server's `N failed, M error(s) of T tests`.

**It does not compare counts.** The unit is the name set, and both directions
are reported: a newly-passing test must be banked with `--update` in the commit
that fixed it, the same one-way discipline `tooling/ratchet` applies to numbers.

**It does not key on `Class.method`.** `getDescription` emits no module, and
`TestCommon.test_default` exists in many addons at once. Every id is qualified
by the addon owning the test module's logger: `quality_control/TestA.test_b`.

## The run spec is part of the baseline

Three of `/base`'s failures assert that a cache clear or an invalidation did
**not** happen, so what breaks them is whatever ran before. By tag they pass.
The cheap control — re-run the one failing test — reports green and loses the
fault, which is why `run_spec` is recorded and a baseline only applies to a run
that matches it.

## Commands

```bash
testbaseline.py <suite> <log>                     # check
testbaseline.py <suite> <log> --update \
    --verified-at <sha> --run-spec '<args>' --note '<why>'
testbaseline.py --list                            # what is recorded
```

Baselines are one JSON per suite in `baselines/`. That directory is the list;
no file restates how many there are.

## Scope

This reads a log someone already produced. It does not run tests, own a
workflow, or gate CI — a red suite is still red, and `--test-enable` still
exits how it always did. What it removes is the *second* run whose only purpose
was to discover whether the first one's red was new.

Full measurements live in the knowledge vault, outside this repo, at
agromarin-knowledge/research/2026-08-22-known-defect-rot.md — named in plain prose
because CI checks this repository out alone and cannot resolve a sibling path.

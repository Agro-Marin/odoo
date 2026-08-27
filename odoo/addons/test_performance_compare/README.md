# test_performance_compare

A **portable, self-contained ORM benchmark** for A/B comparison between this
fork (`19.0-marin`) and a vanilla Odoo **19.0** checkout.

## Why a separate module?

The existing `test_performance` module is **fork-only** and deeply coupled to
refactored internals — it imports the fork's `odoo.tests.benchmark` harness and
exercises `FieldCache`, specialised field `__get__`, `fast_clone`,
`odoo.orm.domain.ast`, `NewId`/`OriginIds`, etc. On a vanilla 19.0 tree it does
not even import, so it **cannot** produce an upstream baseline.

This module is the opposite by design:

- depends only on **`base`**;
- defines **its own models** (`perf.cmp.*`) and builds **its own data**, so the
  database state is identical on both sides;
- vendors a **self-contained harness** (`tests/perfkit.py`) that uses only
  version-stable public surface — `cursor.sql_log_count` for query counts and
  `time.perf_counter_ns` for timing;
- imports **nothing fork-specific**.

➡ The whole folder can be copied, unchanged, into a vanilla 19.0 `addons` path.

It **complements** `test_performance` (kept intact for fork-internal profiling);
it does not replace it.

## What it measures

For ~26 ORM operations (create / read / write / search / mapped / filtered /
sorted / iterate / read_group / unlink) it records, per operation:

- **timing** — mean / median / p95 µs, with 5% outlier trimming and a
  coefficient-of-variation stability flag (the headline signal);
- **query count** — min/max/mean SQL queries (the determinism guardrail: a
  Python-time win that secretly adds DB round-trips is flagged, not hidden).

Results are written to one labelled JSON report. `compare.py` diffs two reports.

## Running it

Two environment variables drive a run:

| var          | meaning                                   | default                        |
|--------------|-------------------------------------------|--------------------------------|
| `BENCH_LABEL`| label stored in the report (`marin`/`upstream`) | `unknown`                |
| `BENCH_OUT`  | output JSON path                          | `./perf_compare_<label>.json`  |
| `BENCH_ITER` | measured iterations per benchmark         | `60`                           |
| `BENCH_WARMUP`| warmup iterations per benchmark          | `8`                            |

The commands below are written against placeholders, not one engineer's local
paths — substitute your own:

- `$REPO_ROOT` — this fork's checkout (the directory containing `odoo-bin`)
- `$VENV` — its Python 3.14 virtualenv
- `$CONF` — its `odoo.conf`
- `$WORKTREES` — any scratch directory for step 2's upstream worktree + venv
- `$UPSTREAM_VENV`, `$UPSTREAM_CONF` — the upstream checkout's own venv/conf,
  set up in step 2

### 1 — Fork (this checkout: Python 3.14 + psycopg3)

```bash
cd $REPO_ROOT
createdb -U odoo -h localhost perf_cmp_marin   # throwaway DB

BENCH_LABEL=marin BENCH_OUT=$PWD/perf_compare_marin.json \
$VENV/bin/python odoo-bin \
    -c $CONF -d perf_cmp_marin \
    -i test_performance_compare --test-enable \
    --test-tags /test_performance_compare \
    --stop-after-init --workers=0
```

### 2 — Upstream 19.0 (Python 3.13 + psycopg2)

Upstream 19.0 targets Python 3.13 and psycopg2, with a different requirements
set, so it needs **its own checkout and its own venv**.

```bash
# (a) worktree pinned to the pristine upstream-mirror branch
cd $REPO_ROOT
git worktree add $WORKTREES/upstream-19.0 19.0

# (b) Python 3.13 venv via uv + upstream requirements (psycopg2, not psycopg3)
uv venv --python 3.13 $WORKTREES/upstream-venv
UPSTREAM_VENV=$WORKTREES/upstream-venv
uv pip install --python $UPSTREAM_VENV/bin/python \
    -r $WORKTREES/upstream-19.0/requirements.txt

# (c) drop this module into the upstream tree (it has no fork deps)
cp -r $REPO_ROOT/odoo/addons/test_performance_compare \
      $WORKTREES/upstream-19.0/odoo/addons/

# (d) run with an upstream conf + throwaway DB
createdb -U odoo -h localhost perf_cmp_upstream
BENCH_LABEL=upstream BENCH_OUT=$REPO_ROOT/perf_compare_upstream.json \
$UPSTREAM_VENV/bin/python $WORKTREES/upstream-19.0/odoo-bin \
    -c $UPSTREAM_CONF -d perf_cmp_upstream \
    -i test_performance_compare --test-enable \
    --test-tags /test_performance_compare \
    --stop-after-init --workers=0
```

### 3 — Compare

```bash
CMP=$REPO_ROOT/odoo/addons/test_performance_compare/compare.py

# single run each (baseline = upstream, candidate = fork)
python3 $CMP -b perf_compare_upstream.json -c perf_compare_marin.json

# RECOMMENDED: several runs per side — compare.py reduces by median-across-runs
# and flags benchmarks that are noisy between runs with '~'
python3 $CMP -b upstream_*.json -c marin_*.json
# speedup > 1.00  ⇒  fork faster.   --md for a Markdown table, --metric mean|p95
```

Run the suite **3+ times per side** (vary `BENCH_OUT`, e.g. `marin_1.json`,
`marin_2.json`, …) and pass them all. Wall-clock for DB-bound operations
(create/write/search) swings noticeably between process launches, so a single
run is not enough to trust those numbers; pure-Python operations (mapped /
filtered / sorted / warm read) are stable from the first run.

## Reading the results — caveats

- **Same host only.** Timing is only comparable when both runs happen on the
  same machine, otherwise hardware noise dominates.
- **Stack differences are part of the result.** The fork runs Python 3.14 +
  psycopg3; upstream runs Python 3.13 + psycopg2. A timing delta therefore
  reflects the *whole* modernised stack, not solely ORM-layer refactors — that
  is intentional (it is what the fork actually ships), but interpret it as such.
- **Query counts are the clean signal.** They are host- and interpreter-
  independent. `compare.py` flags every benchmark whose count differs (`!!`); a
  divergence usually means an intentional strategy change (e.g. the fork's
  psycopg3 COPY-based batch insert, which trades one extra round-trip for a bulk
  COPY) rather than a like-for-like win.
- **Two geomeans.** With multiple runs `compare.py` prints a *stable-only*
  geomean (benchmarks whose cross-run CV ≤ 0.15) and an *all* geomean. The
  stable-only figure is the trustworthy headline; the gap between them measures
  how much the DB-bound noise is moving things.
- **What's reliably faster.** The fork's wins concentrate in the pure-Python
  recordset layer — `sorted` (~14×), `mapped` by field name (~12×), `filtered`
  by field (~11×), warm `read` (~1.7×) — where its batch fast-paths live; these
  are stable run to run. DB-bound op timings (`create`/`write`/`search`) are
  noisy across the two driver stacks; lean on query parity for those, not
  wall-clock. Known small regression: `mapped('<many2one>')` (~0.82×) — the
  relational path builds a deduplicated recordset that scalar `mapped` skips.
- **Warm steady-state, by design.** The harness collects garbage once and keeps
  GC disabled for the measured loop (like `timeit`/`pyperf`). It deliberately
  does **not** `gc.collect()` per iteration: that would evict the CPU caches and
  measure *cold-cache* cost (~8× the warm cost), which is dominated by how many
  modules are installed rather than by the operation — penalising larger
  deployments and compressing every speedup toward 1.0. Sub-µs ops (e.g. a single
  cached field access) are below the timer's resolution; ignore their ratios.

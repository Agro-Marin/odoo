# test_performance_compare

A **portable, self-contained ORM benchmark** for A/B comparison between this
fork (`19.0-marin`) and a vanilla upstream checkout — **`19.0` or `master`**,
which are two different baselines and both worth having (see _Three-way_).

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

➡ The whole folder can be copied, unchanged, into a vanilla **19.0** `addons`
path. On **`master`** one file has to be replaced first — the ACL model was
renamed there — see _One edit is needed for `master`_.

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

| var            | meaning                                         | default                       |
| -------------- | ----------------------------------------------- | ----------------------------- |
| `BENCH_LABEL`  | label stored in the report (`marin`/`upstream`) | `unknown`                     |
| `BENCH_OUT`    | output JSON path                                | `./perf_compare_<label>.json` |
| `BENCH_ITER`   | measured iterations per benchmark               | `60`                          |
| `BENCH_WARMUP` | warmup iterations per benchmark                 | `8`                           |

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

### 2 — Upstream (`19.0` or `master`), same interpreter

**Upstream runs on Python 3.14 too — do not build it a 3.13 venv.** This
section used to prescribe one, on the belief that upstream "targets Python 3.13
and psycopg2". Half of that is still true: upstream is psycopg2-only, and the
fork is psycopg3-only, so the driver is part of the result either way. The
interpreter is not: both upstream `requirements.txt` files carry
`python_version >= '3.14'` pins (Resolute), and a stock
`python3.14 -m venv` + `pip install -r requirements.txt` resolves the whole
set — psycopg2 2.9.10 and python-ldap included — with no `uv` and no second
interpreter. Measured 2026-08-28 on both branches.

Keeping the interpreter equal across sides is worth doing deliberately: it
removes one variable from every timing below.

```bash
# (a) worktree pinned to the branch you are baselining against
cd $REPO_ROOT
git worktree add --detach $WORKTREES/upstream 19.0     # or: master

# (b) its own venv, same interpreter as the fork's
python3.14 -m venv $WORKTREES/upstream-venv
UPSTREAM_VENV=$WORKTREES/upstream-venv
$UPSTREAM_VENV/bin/pip install -r $WORKTREES/upstream/requirements.txt

# (c) drop this module into the upstream tree (it has no fork deps)
cp -r $REPO_ROOT/odoo/addons/test_performance_compare \
      $WORKTREES/upstream/odoo/addons/

# (d) run with an upstream conf + throwaway DB
createdb -U odoo -h localhost perf_cmp_upstream
BENCH_LABEL=upstream BENCH_OUT=$REPO_ROOT/perf_compare_upstream.json \
$UPSTREAM_VENV/bin/python $WORKTREES/upstream/odoo-bin \
    -c $UPSTREAM_CONF -d perf_cmp_upstream \
    -i test_performance_compare --test-enable \
    --test-tags /test_performance_compare \
    --stop-after-init --workers=0
```

#### One edit is needed for `master`, and only for `master`

`master` renamed `ir.model.access` to **`ir.access`**, with different columns.
The copy in step (c) therefore does not install there — it dies loading its own
security file, before a single benchmark runs:

    KeyError: 'ir.model.access'

Replace the file and the manifest line that names it:

```bash
M=$WORKTREES/upstream/odoo/addons/test_performance_compare
rm $M/security/ir.model.access.csv
cat > $M/security/ir.access.csv <<'CSV'
id,name,model_id,group_id/id,operation,domain
access_perf_cmp_base,access_perf_cmp_base,perf.cmp.base,base.group_user,crud,
access_perf_cmp_line,access_perf_cmp_line,perf.cmp.line,base.group_user,crud,
access_perf_cmp_rel,access_perf_cmp_rel,perf.cmp.rel,base.group_user,crud,
access_perf_cmp_tag,access_perf_cmp_tag,perf.cmp.tag,base.group_user,crud,
CSV
sed -i 's|"security/ir.model.access.csv"|"security/ir.access.csv"|' $M/__manifest__.py
```

This is the one thing the "drop the folder in unchanged" claim above cannot
deliver, and it cannot be fixed in the manifest: `__manifest__.py` is read with
`ast.literal_eval`, so it cannot branch on the version it is being installed
into. Nothing else in the module needed changing on either branch.

### 3 — Three-way

`master` is Odoo's development branch, `version_info = (19, 5, 0, ALPHA, …)`,
not a second 19.0 — worth measuring as its own baseline. Run step 2 twice, once
per branch, into differently-labelled reports, and diff each against the fork.

Measured 2026-08-28 (5 runs per side, round-robin ordered so drift spreads
across sides rather than pooling in one), `master` came out at **1.01x**
against `19.0` on this suite, with **query counts identical on every shared
benchmark**. On these paths the two upstream branches are one baseline, not
two; a run that finds otherwise has found something.

### 4 — Compare

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
- **The driver is part of the result; the interpreter need not be.** The fork
  is psycopg3-only and upstream psycopg2-only, so that difference rides along in
  every DB-bound number and cannot be factored out — it is what the fork
  actually ships. The interpreter _can_ be held equal (step 2), and should be.
  Measured 2026-08-28, raw round-trip cost is ~12–13 µs on **both** drivers,
  with run-to-run noise (±3 µs) larger than the gap between them — so a
  double-digit-µs delta on a single-record operation is not the driver, whatever
  else it is.
- **Query counts are the clean signal.** They are host- and interpreter-
  independent. `compare.py` flags every benchmark whose count differs (`!!`); a
  divergence usually means an intentional strategy change (e.g. the fork's
  psycopg3 COPY-based batch insert, which trades one extra round-trip for a bulk
  COPY) rather than a like-for-like win.
- **Two geomeans.** With multiple runs `compare.py` prints a _stable-only_
  geomean (benchmarks whose cross-run CV ≤ 0.15) and an _all_ geomean. The
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
  measure _cold-cache_ cost (~8× the warm cost), which is dominated by how many
  modules are installed rather than by the operation — penalising larger
  deployments and compressing every speedup toward 1.0. Sub-µs ops (e.g. a single
  cached field access) are below the timer's resolution; ignore their ratios.

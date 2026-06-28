# ADR-0006: Drift-zero ratchet for countable quality gates

- **Status:** Accepted
- **Date:** 2026-06-25

## Context

ADR-0005 made the architectural boundaries a real gate: `layer_check.py` keeps
crossings at zero and fails CI on any new one. The team's other quality
signals — mypy, ruff, ESLint, `tsc`, the free-threading run — did *not* get the
same treatment. Each workflow computed a `DRIFT = COUNT - BASELINE` and then only
`echo`-ed it: with `continue-on-error: true` and no `exit 1`, a PR could add
hundreds of new type or lint errors and still merge green
(`py_typecheck.yml`, `lint.yml`, `typecheck.yml`, `freethreading.yml` were all in
this "Phase 1 warn-only" state). The Python type-check baseline was also stale and
self-contradictory — the header said "unset (-1)" while the script hardcoded
`BASELINE=1973`.

A baseline that nothing enforces is a comment, not a gate. And a fork that is
actively reducing a large inherited error count (1972 mypy errors, 658 ruff
findings at the time of writing) needs the reductions to *stick* — otherwise the
count sawtooths and the cleanup work is continuously undone by unrelated PRs.

There was also a missing gate outright: `doc/coding_guidelines.rst` and
`CLAUDE.md` require new Python to pass `ruff check`, but no CI workflow ran ruff.

## Decision

Add a dependency-free (stdlib-only) ratchet, `tooling/ratchet/ratchet.py`, that
turns any gate reducible to a single number into a drift-zero contract — the
generalisation of `layer_check.py`'s `KNOWN_VIOLATIONS` idea from "crossings" to
"counts".

- The committed floor for each gate lives in
  `tooling/ratchet/baselines/<gate>.json` — one small, reviewable file per gate.
- The ratchet moves one way only. In the default `exact` mode: a count **above**
  the floor fails (regression); a count **below** the floor *also* fails, asking
  the author to commit the lower floor in the same PR, so every improvement is
  locked in and can never silently slip back. A `no-increase` mode is available
  for gates not yet ready to lock improvements.
- The tool has its own stdlib `unittest` suite (`test_ratchet.py`), and each
  workflow that uses it runs that self-test first — mirroring how
  `architecture.yml` self-tests the layer checker before trusting it.
- **The floor must be measured on a clean checkout of the target commit**, the
  way CI sees it — not in a working tree carrying *other* uncommitted edits,
  which silently inflate the count (this bit during authoring: in-tree
  measurements read 1974/662, an isolated worktree at HEAD read the true
  1972/658). The gates also pin `--no-incremental` (mypy) / `--no-cache` (ruff)
  so the number is reproducible regardless of cache state. CI starts cacheless
  anyway (both cache dirs are gitignored); the pins make local runs match.

Wired gates (all now blocking; the warn-only placeholders are retired):

| Gate | Floor | Workflow |
|------|-------|----------|
| `mypy` | 1972 | `py_typecheck.yml` (stale 1973 baseline removed) |
| `ruff` | 658  | `ruff.yml` (new — closes the missing Python-lint gate) |
| `tsc` | 2002 | `typecheck.yml` (stale 6,575 baseline removed) |
| `eslint` | 122843 | `lint.yml` (was a `BASELINE=0` placeholder) |

The `eslint` floor is the fork's own JS only: vendored third-party libraries are
excluded **structurally** — `eslint.config.mjs` ignores `**/static/lib/**`, and
the convention is that vendored code lives in `static/lib` and nowhere else, so
there is no per-library allowlist to drift (this dropped the raw count from
152007 by relocating one stray lib and generalising the ignore). The remaining
floor is ~76k source + ~46k test errors; the test bulk is largely missing test
globals — a separate follow-up.

## Consequences

- The mypy and ruff counts can now only fall. The large inherited debt is frozen
  at today's number and every PR either holds or lowers it; the cleanup compounds
  instead of sawtoothing.
- The ratchet state is visible in the diff (the baseline file moves in the same
  commit as the count), not buried in CI logs — reviewable like any other change.
- New cost: a PR that legitimately changes a count must run the tool and commit
  the new floor. This is intentional friction — it is the mechanism by which the
  floor stays truthful.
- All four count gates (mypy, ruff, tsc, eslint) are on the tool. The
  free-threading run (`freethreading.yml`) is a pass/fail correctness gate, not a
  count, so it stays as-is.

## Enforcement

`tooling/ratchet/ratchet.py` exits non-zero on any drift; `py_typecheck.yml` and
`ruff.yml` invoke it without `continue-on-error`. The tool is itself gated by
`tooling/ratchet/test_ratchet.py`, run as the first step of each consuming
workflow. Run locally:

```bash
python tooling/ratchet/test_ratchet.py          # self-test
python tooling/ratchet/ratchet.py --list         # current floors
python tooling/ratchet/ratchet.py mypy --count N  # verdict (exit 1 on drift)
```

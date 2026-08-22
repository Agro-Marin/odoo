# ADR-0006: Drift-zero ratchet for countable quality gates

- **Status:** Accepted
- **Date:** 2026-06-25

## Context

ADR-0005 made the architectural boundaries a real gate. The other quality
signals — mypy, ruff, ESLint, `tsc`, free-threading — did not get the same
treatment. Each workflow computed `DRIFT = COUNT - BASELINE` and then only
`echo`-ed it: with `continue-on-error: true` and no `exit 1`, a PR could add
hundreds of type or lint errors and merge green (`py_typecheck.yml`,
`lint.yml`, `typecheck.yml`, `freethreading.yml` were all warn-only). The
Python baseline was self-contradictory — the header said "unset (-1)" while the
script hardcoded `BASELINE=1973`.

A baseline nothing enforces is a comment. A fork actively reducing a large
inherited count (1972 mypy errors, 658 ruff findings at the time) needs the
reductions to stick, or the count sawtooths and the cleanup is undone by
unrelated PRs.

One gate was missing outright: `doc/coding_guidelines.rst` and `CLAUDE.md`
require new Python to pass `ruff check`, and no workflow ran ruff.

## Decision

Add a stdlib-only ratchet, `tooling/ratchet/ratchet.py`, turning any gate
reducible to a single number into a drift-zero contract — `layer_check.py`'s
`KNOWN_VIOLATIONS` idea generalised from crossings to counts.

- One floor per gate, `tooling/ratchet/baselines/<gate>.json`.
- Default `exact` mode moves one way: above the floor fails as a regression,
  **below it also fails**, asking for the lower floor in the same PR. Every
  improvement is locked in. `no-increase` mode exists for gates not ready to
  lock improvements.
- Its own stdlib suite (`test_ratchet.py`) runs first in every consuming
  workflow, as `architecture.yml` self-tests the layer checker.
- **Measure the floor on a clean checkout of the target commit.** A working
  tree carrying other uncommitted edits inflates the count silently — during
  authoring, in-tree measurements read 1974/662 where an isolated worktree at
  HEAD read 1972/658. The gates pin `--no-incremental` (mypy) and `--no-cache`
  (ruff) so local runs match CI, which starts cacheless.

Wired gates, all blocking. **These floors are what the ratchet started from on
2026-06-25, not current values** — the live floors are
`tooling/ratchet/baselines/<gate>.json`, printed by
`python tooling/ratchet/ratchet.py --list`.

| Gate | Floor as first wired | Workflow |
|------|----------------------|----------|
| `mypy` | 1972 | `py_typecheck.yml` (stale 1973 baseline removed) |
| `ruff` | 658  | `ruff.yml` (new — closes the missing Python-lint gate) |
| `tsc` | 2002 | `typecheck.yml` (stale 6,575 baseline removed) |
| `eslint` | 122843 | `lint.yml` (was a `BASELINE=0` placeholder) |

The `eslint` floor is fork JS only. Vendored libraries are excluded
**structurally**: `eslint.config.mjs` ignores `**/static/lib/**`, and the
convention is that vendored code lives there and nowhere else, so no
per-library allowlist can drift. Relocating one stray lib and generalising the
ignore dropped the raw count from 152007.

## Consequences

- The counts can only fall; the inherited debt is frozen and cleanup compounds.
- Ratchet state moves in the diff, reviewable, rather than in CI logs.
- Cost: a PR that legitimately changes a count runs the tool and commits the
  new floor. That friction is the mechanism.
- All four count gates are on the tool. `freethreading.yml` is pass/fail, not a
  count, and stays as-is.

## Enforcement

`tooling/ratchet/ratchet.py` exits non-zero on drift; `py_typecheck.yml` and
`ruff.yml` invoke it without `continue-on-error`. `tooling/ratchet/test_ratchet.py`
gates the tool and runs first in each consuming workflow.

```bash
python tooling/ratchet/test_ratchet.py            # self-test
python tooling/ratchet/ratchet.py --list          # current floors
python tooling/ratchet/ratchet.py mypy --count N  # verdict (exit 1 on drift)
```

## Amendments

### 2026-08-07 — the floor table now says which moment it describes

The floors sat under a bare "Floor" heading, reading as current values. All
four have since moved, `eslint` by an order of magnitude. That is this
register's own rule — cite the file, not the value — failing in the record the
rule came from.

The values are kept: what the ratchet started from is part of the decision and
is true forever. The column is now "Floor as first wired", dated, pointing at
`tooling/ratchet/baselines/` for live numbers.

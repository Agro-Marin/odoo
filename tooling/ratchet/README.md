# Quality ratchet

A drift-zero ratchet for any quality gate that reduces to a single number —
mypy errors, ruff findings, ESLint errors, `tsc` errors, free-threading
warnings. It is the generalisation of `tooling/architecture/layer_check.py`'s
`KNOWN_VIOLATIONS` idea: that checker keeps architectural crossings at zero;
this keeps *counts* monotonically falling.

## Why

Several gates used to compute `DRIFT = COUNT - BASELINE` and only `echo` it —
`continue-on-error: true` plus no `exit 1` meant a PR could add hundreds of new
errors and still merge green. A baseline nothing enforces is a comment. This
turns the number into a contract with teeth.

The ratchet moves one way only:

| Live count vs floor | `exact` mode (default) | `no-increase` mode |
|---|---|---|
| greater | **fail** — regression | **fail** — regression |
| equal | pass | pass |
| less | **fail** — "commit the lower floor" | pass (with a notice) |

`exact` is the default on purpose: an improvement you don't commit fails, which
forces the lower floor to be locked into the same PR. That is what makes wins
*compound* — the floor can never silently slip back up.

## Use

```bash
# CI: the gate computes its count, the ratchet renders the verdict (exit 1 on drift).
python tooling/ratchet/ratchet.py mypy --count 1969
python tooling/ratchet/ratchet.py mypy --count 1969 --json     # machine-readable

# Maintainer: set or lower a floor — the only way it moves. Commit the result.
python tooling/ratchet/ratchet.py mypy --count 1900 --update --note "..."

python tooling/ratchet/ratchet.py --list                       # all floors
```

Floors live in `baselines/<gate>.json` — one small file per gate so the state is
reviewable in the diff, not buried in CI logs. A PR that changes a count must
move its floor in the same commit.

## Wired gates

| Gate | Floor | Workflow |
|---|---|---|
| `mypy` | `baselines/mypy.json` | `.github/workflows/py_typecheck.yml` |
| `ruff` | `baselines/ruff.json` | `.github/workflows/ruff.yml` |
| `tsc` | `baselines/tsc.json` | `.github/workflows/typecheck.yml` |
| `eslint` | `baselines/eslint.json` | `.github/workflows/lint.yml` |

All four count gates are blocking. `freethreading.yml` is a pass/fail
correctness run, not a count, so it is not a ratchet.

## Self-test

`python tooling/ratchet/test_ratchet.py` — stdlib `unittest`, no Odoo, no DB. CI
runs it before trusting any verdict, the same way `architecture.yml` self-tests
the layer checker.

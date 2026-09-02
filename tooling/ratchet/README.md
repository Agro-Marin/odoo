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

## A gate with no baseline is a hard zero

`ratchet.py <gate> --count N` with no `baselines/<gate>.json` passes at 0 and
fails on anything above it, in either mode, naming the file it did not find.
The file records *debt* — a count above zero and the note saying what moved
it — so a count born at zero has nothing to record: it is a contract, and a
JSON holding `0` for it only made `--list` report a contract as a floor to
drive down. `--update` is the one way to open a floor where there is none,
and the note has to argue why the contract becomes debt. `--list` reads the
files and nothing else, so it stays a list of debt. `assert_ratchet` under
`odoo/addons/test_lint/tests` has read an absent baseline as zero since it
landed; this is the same rule for the workflow-driven gates.

## A floor is a claim about a commit

`--update` refuses a dirty tree (`git status --porcelain --untracked-files=all`
non-empty) and stamps `measured_at` with the HEAD it was measured on, so a floor
can only be banked from a clean worktree of the commit it names. A check whose
floor is stamped at a commit outside HEAD's history exits 2 with "re-measure":
that count was taken on a tree this branch never had. A stamp git cannot resolve
stays `UNCHECKED` and is still compared, because unknowable is not wrong.

A gate named `<name>_<sibling>` measures that sibling checkout. Bank it with
`--root <sibling>` from a clean worktree of the *sibling*: that is the tree the
dirty check reads and the history the stamp lives in, recorded as
`measured_root`. Without `--root` the tool refuses. A sibling floor stamped
before `--root` existed carries an odoo commit, which resolves cleanly in the
wrong repository; `--list` renders it `STAMP-PREDATES-ROOT` until its next bank.

## Wired gates

**`baselines/` is the list and `--list` is the reading.** No file states how
many floors there are or what they hold; a restated count is a second copy that
drifts, and this section held four rows for a long time after the set passed
ninety.

```bash
python tooling/ratchet/ratchet.py --list           # gate and floor, one line each
python tooling/ratchet/ratchet.py --list --notes   # with what moved each one
```

Every floor is read by something, and `test_baseline_enforcement.py` is what
makes that true rather than aspirational: a workflow step running
`ratchet.py <gate> --count`, or an `assert_ratchet` call under
`odoo/addons/test_lint/tests`, or -- for a floor whose name carries a sibling
repository's suffix -- that repository's own `architecture.yml`. A baseline
none of the three reads fails the suite by name. The same suite runs every
workflow invocation that has no file against the committed directory and
pins that it passes at 0 and fails at 1.

`freethreading.yml` is a pass/fail correctness run, not a count, so it is not a
ratchet.

A count is the right unit for aggregate drift across a whole repo, but it names
no file and lets one file's fix pay for another's regression. Where a gate can
name files instead, `tooling/typecheck` applies the same drift-zero philosophy
per file: the web module's `strictNullChecks` / `noImplicitAny` locks are
default-deny, so the *exception* list shrinks rather than a floor falling. The
two compose — `typecheck.yml` runs the `tsc` count ratchet over every module and
the per-file locks over `web`.

## Self-test

`python tooling/ratchet/test_ratchet.py` — stdlib `unittest`, no Odoo, no DB. CI
runs it before trusting any verdict, the same way `architecture.yml` self-tests
the layer checker.

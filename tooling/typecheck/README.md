# Default-deny type-check locks

Per-file type-check gates: every file in a gated scope must be error-free
unless it is named in that scope's exception list, and the list may only
shrink. Two languages, one mechanism — `scope_gate.py` locks TypeScript per
addon module, `py_scope_gate.py` locks mypy per core package (see *The Python
side* at the end).

For the TypeScript gates below, the unit is a module: every `.js`/`.ts` under a
gated module's `static/src/` and `static/tests/` must be error-free under a
given tsconfig unless it is named in `exceptions/<gate>/<module>.txt`.

| Gate | Config | Exceptions |
|---|---|---|
| `strict` | `tsconfig.strict.json` (base + `strictNullChecks` + `checkJs`) | `exceptions/strict/<module>.txt` |
| `noimplicitany` | `tsconfig.noimplicitany.json` (base + `noImplicitAny` + `checkJs`) | `exceptions/noimplicitany/<module>.txt` |

Both run the **full program** — the same ~6400-file program as the real build —
so `@odoo/owl`, the `odoo` global and the `@types/` ambients resolve exactly as
they do in production and the reported errors are real. Only the *verdict* is
scoped; the compile is not. An isolated `files` program would under-resolve the
framework types and invent errors in anything touching `useService` or a
registry.

## Why default-deny

The predecessor gates were allowlists: they named the files that had to be
clean, so anything unnamed was unenforced. Two failure modes followed, both
measured on `19.0-marin`:

- **Coverage left on the floor.** 448 of 687 `static/src` files were already
  strictNullChecks-clean while the allowlist locked 129. The gate under-claimed
  its own codebase by 3.5x, and nothing surfaced that.
- **A rename deleted a lock, silently.** `ui/block/ui_service.js` moved to
  `ui/ui_service.js`; its allowlist entry stopped matching any file, so the lock
  evaporated and the gate stayed green. Three more entries in the retired
  web-local list pointed at paths that no longer existed.

Inverting the list fixes both by construction. The default for an unmentioned
file becomes "must be clean", so new files are gated from their first commit,
and a moved file cannot launder itself out of enforcement — see `stale` below.

## Why `checkJs` is not optional

Without `checkJs`, tsc only type-checks a `.js` file that opts in with a
`// @ts-check` comment. That puts the gate's reach in the *source files* rather
than in the gate, which is the allowlist hole again in a different costume: a
new file without the pragma is silently unchecked, yet a default-deny gate
counts it as locked at zero.

In `web` the pragma is near-universal — 1271 of 1273 files — so turning
`checkJs` on there only adds `module_loader.js` and `service_worker.js`. For
every other module it is the whole ballgame: `mail`, `bus`, `html_editor`,
`html_builder`, `website` and `point_of_sale` carry the pragma on **1 file out
of 2052 between them**, so a lock over them without `checkJs` would report 100%
coverage while checking essentially nothing.

`checkJs` is set on the two gate configs, not on the base `tsconfig.json`, so
the project-wide count ratchet keeps measuring the same thing it always has.

## Use

```bash
# Gate (what CI runs). --listFiles is required — see "unchecked" below.
npx tsc -p tsconfig.strict.json --noEmit --listFiles > /tmp/strict.log 2>&1 || true
python tooling/typecheck/scope_gate.py strict --log /tmp/strict.log

# One module, for a local loop.
python tooling/typecheck/scope_gate.py strict --log /tmp/strict.log --module web

# Regenerate after fixing (or after a deliberate exemption). Commit the diff.
python tooling/typecheck/scope_gate.py strict --log /tmp/strict.log --update

# What should I fix next? Ranks exceptions by errors x per-code ease.
python tooling/typecheck/scope_gate.py strict --log /tmp/strict.log --report
```

`--log -` reads stdin. `--json` emits the verdict as an object, with a
per-module breakdown under `modules`.

## The five ways to fail

| Status | Meaning | Fails in |
|---|---|---|
| `regressed` | in scope, not excepted, erroring | both modes |
| `stale` | an excepted path does not exist on disk | both modes |
| `out-of-scope` | an excepted path is outside the module whose list holds it | both modes |
| `resolved` | an excepted file is now clean | `exact` only |
| `unchecked` | an in-scope file is absent from the tsc program | both modes |

`resolved` failing is deliberate, and is the same reasoning as
`tooling/ratchet`'s exact mode: an uncommitted improvement fails, which forces
the shorter list into the same PR so the win can never silently slip back.
`--mode no-increase` downgrades it to a notice, for a rollout where that is too
strict.

`stale` is the check that closes the rename hole. Without it a moved file reads
as `resolved` — "congratulations, it's clean" — when in fact its lock is gone.

`unchecked` closes the matching hole one level down: a file tsc never compiled
reports no errors, and a gate that reads silence as cleanliness will count it as
locked. This was live in this repo — `exclude: ["**/l10n*"]`, aimed at the
`l10n_*` addons, also matched `addons/web/static/tests/core/l10n/` and
`addons/web/static/tests/l10n/`, so eight `.test.js` files sat outside the
program while the gate reported them locked at zero. The exclude is now anchored
at `addons/l10n_*`, and the membership check makes a recurrence a hard failure
rather than a silent gift.

This is why `--listFiles` is mandatory: the file list is both the input to that
check and the proof the compile actually happened. It replaces the old "refuse a
log with zero diagnostics" heuristic, which could not tell a genuinely clean
program from a tsc invocation that died on a bad config path.

## Pinning, and why the version matters

The exception lists are only meaningful against the `typescript` version pinned
in `package-lock.json` (**5.9.3**); a different minor reports a different error
set. CI uses `npm ci` for exactly this reason.

Check before you regenerate — `package.json` asks for `^5.7.2`, so a
`node_modules` populated by `npm install` rather than `npm ci` can sit on an
older minor than the lockfile:

```bash
node_modules/.bin/tsc --version    # must match the package-lock pin
```

Lists generated against a mismatched compiler will disagree with CI on the first
run.

## Regenerating against the committed tree

`--update` records whatever the log says, so generate it from a tree that
matches what CI will check out. A dirty worktree — in this workspace, often
another session's in-flight edits — silently bakes a transient state into the
list. That is not hypothetical: a log captured mid-edit contained a `TS1003`
syntax error whose suppression of downstream inference moved six errors across
three unrelated files. To be sure:

```bash
git status --porcelain          # must be empty, or
git archive HEAD | tar -x -C /tmp/head_tree && ln -s "$PWD/node_modules" /tmp/head_tree/
```

`git archive` is preferred over `git worktree add` here because it does not
write to the shared `.git`.

## Self-test

`python tooling/typecheck/test_scope_gate.py` — stdlib `unittest`, no Odoo, no
node, no DB. CI runs it before trusting any verdict, mirroring
`tooling/ratchet/test_ratchet.py` and `tooling/architecture/test_layer_check.py`.

## Scope

`static/lib` is deliberately outside the scope: vendored third-party code
(bootstrap, luxon, pdfjs) plus hoot, whose types are the test harness's own.

`web` is the only gated module today. The per-module layout is what makes adding
the next one additive — append it to `SCOPED_MODULES` in `scope_gate.py`, run
`--update` to generate its two lists, commit both together — rather than a
restructure. The scope lives in the script instead of on the command line so CI
and a local run cannot disagree about what is enforced.

Measured 2026-07-29 under `checkJs` at the pinned compiler, the candidates
behind `web` are a long way from clean, which is why they stay on the
project-wide count ratchet for now:

| Module | Files | `strict` locked | `noImplicitAny` locked |
|---|--:|--:|--:|
| `mail` | 595 | 169 (28%) | 127 (21%) |
| `bus` | 36 | 10 (28%) | 5 (14%) |
| `html_editor` | 336 | 81 (24%) | 69 (21%) |
| `html_builder` | 193 | 50 (26%) | 33 (17%) |
| `website` | 564 | 172 (31%) | 158 (28%) |
| `point_of_sale` | 328 | 162 (49%) | 80 (24%) |
| `spreadsheet` | 144 | 56 (39%) | 15 (10%) |

A gate that has to except three quarters of a module teaches people to ignore
it, so add one when its numbers justify a lock — or land a cleanup pass first
and lock it behind that.

## The Python side — `py_scope_gate.py`

The same mechanism over `mypy`, one lock per **core package** instead of per
addon module. Gate: `py_scope_gate.py`; scope: the six packages `mypy.ini`
checks (`orm`, `db`, `libs`, `http`, `service`, `modules`); lists:
`exceptions/mypy/<pkg>.txt` and `budgets/mypy-<pkg>.json`. It runs in
`.github/workflows/py_typecheck.yml`, beside — not instead of — the count
ratchet.

**Why it was added.** The Python side had no allowlist to invert; it had
something weaker, a single integer
(`tooling/ratchet/baselines/mypy.json`, floor 1286). Measured on the run that
produced that floor: **1286 errors in 189 files, of 469 checked — so 280 files
(59%) were already clean and none of them was locked.** That is the fungible
slack `doc/architecture/gates.md` diagnosed for `ruff_docstring`, and the
demonstration is in `test_py_scope_gate.py`: move one error off an excepted
file and onto `odoo/orm/__init__.py`, and the total stays at 1286 while the
lock is gone. The ratchet reports `No drift`; this gate reports `regressed`.

Coverage as seeded (2026-08-09, mypy 2.3.0):

| Package | Files | Locked | Excepted | Errors |
|---|--:|--:|--:|--:|
| `libs` | 154 | 113 (73%) | 41 | 197 |
| `db` | 40 | 29 (72%) | 11 | 19 |
| `modules` | 9 | 5 (56%) | 4 | 75 |
| `orm` | 181 | 89 (49%) | 92 | 765 |
| `http` | 39 | 18 (46%) | 21 | 134 |
| `service` | 25 | 5 (20%) | 20 | 95 |
| **total** | **448** | **259 (58%)** | **189** | **1286** |

Three differences from the JS gates, each forced by the tool:

- **`--verbose`, not `--listFiles`.** mypy has no `--listFiles`; the
  `LOG:  Parsing <file>` lines are the equivalent, and they are what makes the
  `unchecked` verdict possible. Without them a file mypy skipped is
  indistinguishable from a file mypy found clean. The gate refuses a log that
  carries none (exit 2, a usage error) rather than failing every file.
- **`--verbose` does not perturb the ratchet.** No verbose line matches
  `: error:`, so the same log serves both steps and the count stays 1286.
- **The budgets carry more weight here.** `web`'s exception list is mostly
  small per-file counts; `orm` alone holds 765 errors over 92 files, so
  membership without ceilings would leave a large fungible pool behind.

`--report` ranks the exceptions by count × per-code ease, on the same [0, 1]
scale and direction as the JS gate. As seeded, 47 excepted files carry exactly
one error, most of them `[var-annotated]`.

**Both `db` and `libs` are already above 70% and are the cheap ones to drive to
zero; `service` at 20% is the debt.** Note that `tests/` modules are inside the
scope, matching the JS gates' inclusion of `static/tests` — a deliberate
choice, not an accident of the glob.

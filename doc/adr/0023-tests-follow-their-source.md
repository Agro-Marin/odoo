# ADR-0023: A moved file must not silently disconnect its tests

- **Status:** Accepted
- **Date:** 2026-08-14 (retroactive — records decisions already enforced)

## Context

The client's test suites are addressed by path. HOOT derives a suite's identity
from the **test** file's location, and a test file reaches its subject through a
relative specifier. Both are load-bearing, both break when source moves, and
**both break silently** — the failure is a green run that proves less than it
appears to.

Two breakages, one week apart, in the same refactor.

**A specifier that does not resolve makes a suite register nothing.** An ES
module whose import target is missing never evaluates, so its tests are never
declared. The runner reports `0 failed / 0 passed` rather than an error, and a
summed run simply reports a smaller total. On 2026-08-02, moving the field
suites into a deeper directory left their `../../` prefixes unrepointed: **six
suites and 96 tests stopped running on HEAD**, and nothing went red.

**A suite whose path no longer mirrors its source becomes unaddressable.** When
one directory's source was reorganised into a top-level layer with seven
subcategories while its 84 test files stayed put, the obvious selector for 114
source files resolved to **zero** suites, while the old selector still resolved
to 84. The tests ran, passed and reported green under their old identity. What
broke was selecting a module's tests by where its source lives.

### Why no existing gate could see either

- The cycle gate walks source only, never the test tree, and its resolver
  returns the same answer for "not first-party" and "file does not exist". It
  *must* conflate them, so something else has to assert those do not exist.
- The layer gate reasons about a specifier's *shape*, never about whether the
  target is there.
- The typecheck locks except the affected files, and the aggregate count absorbs
  the missing-module error into a four-figure total.
- The parity gate passed throughout the first failure: the directories mirrored
  correctly, which is all it checks. **Directory parity is not the same property
  as a suite that loads.**

## Decision

**Both properties are pinned drift-zero, separately, because they are different
properties that happen to fail together.**

### 1. Every first-party specifier names a real file

Checked over `static/src` **and** `static/tests` of every addon — the test tree
included, because that is where the failure occurred and where nothing else
looks.

### 2. Test layout mirrors source layout, in both directions

- **Layer coverage** — every top-level source directory holding at least one
  `.js` file has at least one test file under the same name. Catches a whole
  layer becoming unaddressable.
- **No orphan test directories** — every test directory containing tests has a
  counterpart under source. Catches the same drift one level down, where it
  starts.

### Debt is pinned so it can only shrink, and is distinguished from design

`KNOWN_*` entries are today's debt: they may only shrink, and **a fixed entry
still listed fails the gate exactly like a new violation**, so the list cannot
rot into a permanent allowlist. `EXEMPT_*` is different in kind — test
infrastructure mirroring no source by design — and is named separately.
Collapsing the two would make the debt un-drainable, because nobody could tell
which entries were ever meant to go.

## Alternatives considered

**Extend the cycle gate to the test tree.** Fails on the resolver: that gate
deliberately cannot distinguish "not a first-party module" from "file does not
exist", because for its purpose the distinction does not exist. Making it
distinguish them changes what it means, to serve a question it was not built to
answer.

**Rely on the typecheck to catch the unresolvable import.** Rejected on
evidence: it produced the error and the error was invisible, because the
affected files are excepted from the locks and the base count absorbs a single
finding. ADR-0006's argument about aggregate floors, in a second place.

**Rely on the test count.** A summed run does report a smaller total — and
nobody watches a total that moves for a dozen legitimate reasons.

**One gate for both properties.** Rejected, and the first failure is the proof:
the parity gate was green throughout, correctly, because the directories did
mirror. A suite that loads and a suite that is addressable are independent
properties, and one gate would assert the weaker of the two.

**Make suite identity derive from the source path instead of the test path.**
That dissolves the second problem at the root, and it is not this repo's
decision to make — the runner's addressing scheme is upstream behaviour that
addons and tooling already depend on. Pinning the mirror is the affordable half.

## Consequences

- A refactor that moves source fails a gate rather than quietly reducing what
  runs. The 96 tests would have been caught at the commit that stopped them.
- **Moving source is more expensive**, because the tests move with it in the
  same change. The intended trade: the alternative is cheap moves and suites
  that address nothing.
- The debt lists must be drained rather than extended, and a fixed entry left
  listed is itself a failure — so they cannot become permanent allowlists.
- Both gates cover the client only. The Python suites have their own conventions
  and no equivalent check.
- Neither gate says whether a test that *does* run asserts anything useful. They
  pin reachability, not quality.

## Enforcement

Two gates in `tooling/architecture/`, each declaring `ADR = "0023"`, both run by
`.github/workflows/architecture.yml`:

| gate | holds |
|---|---|
| `tooling/architecture/js_import_resolution.py` | every first-party specifier, in source and tests, names a real file |
| `tooling/architecture/js_suite_parity.py` | test layout mirrors source layout, both directions, with debt pinned shrink-only |

`tooling/architecture/test_gate_adr_coverage.py` checks that both citations
resolve to this record and that it is `Accepted`. Run either gate for its live
status.

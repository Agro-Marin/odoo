# ADR-0025: Budget function length — and ratchet the excess, not the offenders

- **Status:** Accepted
- **Date:** 2026-08-14 (retroactive — records decisions already enforced)

## Context

Nothing bounded how long a function could be, in either language, and the
adjacent gates do not cover it.

In Python, `c901` measures *cyclomatic complexity*, so a long straight-line
function scores near zero. The core's CLI builder stood at **1024 lines**, 4.6×
the next-longest function in the core, built almost entirely from consecutive
option-registration calls; its branch count was trivial, so every gate reported
it clean. Measured across 6,208 functions under the core package when the gate
landed: median 7 lines, p95 55, three over 200.

In the client the longest function was 738 lines, and the shape recurred —
service factories in the four hundreds, a 609-line hook, a 240-line renderer
setup.

Two questions had to be answered first, and the obvious answer to each is wrong.

**What to measure.** An earlier draft proposed a per-class method ceiling.
Measured, that metric is *inverted*: the widest classes are wide and **thin** —
one has 80 members whose median is two lines, another's 72 members have no
external subclasser at all — while a 29-member controller carries 59 downstream
subclass and patch sites. A method-count ceiling would flag the harmless class
and clear the load-bearing one. Function length also catches what no class-level
metric sees: the longest functions in the tree belong to no class.

**How to measure it.** Function extents are a parsing problem, and hand-rolled
brace matching gets them wrong. A scan pairing a closing brace at the
declaration's indentation misses object-literal methods, which close with `},`,
then runs on to a later brace — reporting a two-line function as 241 lines.
Three attempts at the client number by regex gave 127, 114 and 117; the answer
is none of them.

## Decision

**Both trees carry a function-length budget at 80 lines, ratcheted, and each is
measured by a real parser rather than a bespoke one.**

The client rule is injected into a normal ESLint run — ESLint already parses
those files correctly — and is **deliberately not added to `eslint.config.mjs`**.
There it would fold into the repo-wide aggregate baseline, where a new 300-line
function is one unit in five figures: the signal-inside-noise problem that made
ADR-0019's layering rules unenforceable as lint findings.

### The ratcheted number is the excess, not the offender count

The one place the two gates deliberately differ; the Python side is the
corrected version.

**Counting offending functions punishes the exact fix the gate exists to
encourage.** Splitting the 1024-line CLI builder measured:

| metric | before | after |
|---|---|---|
| functions over budget | 121 | 127 — *worse* |
| excess lines above budget | 5457 | 4867 — better by 590 |
| longest single function | 1024 | 294 — better by 730 |

One enormous function became eleven methods, four still over budget. By offender
count that refactor is a regression; by excess lines and worst case it is a clear
improvement. So the Python gate ratchets `sum(len - 80)`.

**The client gate still counts functions**, because that is what it was built
with and its baseline is in those terms. A known inferior metric, recorded here
rather than left to be discovered — the same split refactor would read as a
regression there.

## Alternatives considered

**A per-class method ceiling.** Rejected on measurement, and the most useful
rejection here because it is counter-intuitive: the metric ranks a thin
80-member class as the worst offender and a 29-member class with 59 downstream
extension sites as fine. It optimises for a shape nobody was harmed by, and
would generate churn against classes whose width is their API.

**Enable ruff's own length rules for Python.** Turning one on puts the finding
into the general ruff floor — a hard zero for `tooling/` and `tests/` and a
separate ratchet for the core — so a length regression would either block
unrelated work or vanish into an aggregate. ADR-0006 argues for a gate with its
own number.

**Add the client rule to the shared lint config.** Rejected for the same reason:
the repo-wide aggregate is five figures, so a new 300-line function moves it by
one.

**Measure extents with a purpose-built scanner.** Rejected after three attempts
produced three different answers, none correct. Both gates delegate extents to a
parser that already exists and is already right.

**Ratchet the longest function rather than the total excess.** Attractive, and
rejected because it goes quiet: once the worst function is split the number
stops moving while hundreds of lines of excess remain, so it reports success in
the middle of the work.

## Consequences

- A long function is visible in both trees, including the straight-line kind
  complexity metrics score as clean.
- **A refactor that splits a long function scores as an improvement in Python
  and a regression in the client.** Naming that inconsistency is the honest
  alternative to leaving it to be found. Converting the client gate to excess
  means restating its baseline in new units — mechanical, not a decision, and
  not made here.
- The budget is a ceiling on lines, not on cohesion. A 79-line function doing
  four unrelated things passes.
- Both budgets are per-tree ratchets, so the remaining distance is visible and
  each improvement is locked in.
- The client gate depends on the JS toolchain being installed, so it reports a
  missing tool rather than a finding on a bare checkout — which is why CI
  installs it before the boundary job runs.

## Enforcement

Two gates in `tooling/architecture/`, each declaring `ADR = "0025"`, both run by
`.github/workflows/architecture.yml` against baselines in
`tooling/ratchet/baselines/`:

| gate | ratchets |
|---|---|
| `tooling/architecture/py_function_length.py` | excess lines above budget, over the core package |
| `tooling/architecture/js_function_length.py` | functions over budget, per addon |

`tooling/architecture/test_gate_adr_coverage.py` checks that both citations
resolve to this record and that it is `Accepted`. Run the gate or read its
baseline for live figures.

## Amendments

### 2026-08-17 — a mixin factory is not a function this budget should count

The client gate counted `(Base) => class extends Base { … }` as one function.
That shape is a function only grammatically: its body is a class, and the
complexity lives in that class's methods, which ESLint reports separately. The
wrapper charged the floor a second time for code already counted —
`SearchSplitDomainMixin` held exactly one method and was listed twice, at 142
lines for the body and 139 for `splitAndAddDomain`, three lines apart.

The Decision says the budget is a complexity proxy measured by a real parser.
Counting the wrapper contradicted the first half while satisfying the second:
ESLint's extents were right, and the unit was wrong.

It was also unpayable, which matters more than the double count. A mixin holding
a dozen short methods can be several hundred lines with no method over budget,
so the only move that took the wrapper off the list was splitting the mixin into
fragments — more files, the same complexity, the floor down by one. A floor
carrying entries nobody can retire stops being a ratchet.

The gate had recognised the shape since it landed, relabelling these entries
"Mixin class body" while continuing to count them. Naming a measurement error is
not correcting it. `js_function_length.py` now drops them and keeps their
methods, the unit the rest of the gate already used.

Measured on one tree both ways when this landed: the old unit reported 133 for
`web` and the new unit 127, the difference being exactly the six wrappers — a
unit change with no tree change. `mail`, `account`, `stock` and `product` were
unmoved: none carried a mixin factory over budget.

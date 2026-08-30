# ADR-0079: A suite that no lane runs is not a test

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

This fork gates a great deal. Counts are ratcheted, names are held to a
vocabulary, figures in prose are measured and rewritten, floors fail in both
directions, and a gate that finds no inputs must refuse rather than report
success. All of that answers the question *is this code as we say it is*.

None of it answers a prior question: **is anything running the tests that say
so.**

`integration_tests.yml` names its suites in env vars, one per lane. Measured
2026-08-30, those names covered thirteen modules. Every other bundled module's
suite was reached by `module_installability.yml`, which passes no
`--test-enable` and asks whether the module graph assembles — a different
question, and not coverage.

Two things that happened the same day are the argument for this record.

**A framework's consumers went untested and a regression reached HEAD.**
`document_extract` gained a declaration that a list field states its row shape.
It was verified against a module list typed by hand — the framework and five
consumers, 196 tests, 0 failed — and shipped. The family is eleven modules.
`document_extract_hr_recruitment_skills` was not in the list; four of its six
tests feed skills as bare strings, which the declaration silently dropped.
`--test-tags` matches a module name exactly, so `/document_extract_hr_recruitment`
never reached `..._skills`, and the shorter list looked complete. No lane
covered any of them, so nothing else caught it either.

**A test-only module had never run.** `test_base_order` is
`category: Hidden/Tests` and exists solely to exercise `base_order`'s mixins
against concrete models — 219 test methods. No workflow mentioned it by name,
through a `paths:` entry, or transitively. `base_order` itself was in the same
position with another 70. Both pass; nobody knew.

A hand census of fork-native modules found **1,672 test methods in no lane**,
of which 606 are `credential` and `api_transport`, a decision already recorded
with its cost stated. The remaining 1,066 were recorded nowhere. The census is
written up in the AgroMarin knowledge vault under research, dated 2026-08-30.

The census was produced by reading workflow env vars by hand. That is the
problem this record is about: the next module to ship a suite into silence will
be found the same way, or not at all.

## Decision

**A module that ships tests names itself in a lane, or the fork records why
not.**

`tooling/architecture/module_suite_lane.py` measures the gap. A module is
covered when a workflow that passes `--test-enable` names it in `--test-tags`;
it is exempt when `EXEMPT` carries it with a reason; otherwise it is an offence.

**Tags are the predicate, not installs.** A module can be installed by a lane
without its suite running: `sale` and `purchase` are installed by the
`base_order` lane so that suite's registry holds what its tests reach for, and
`sale`'s own tests do not run there. Counting installs would call `sale` covered
and be wrong. `--test-tags` is what selects tests, so `--test-tags` is what the
gate reads.

**A ratchet, not a contract.** The gate measures 418 at this record's date,
which is the upstream tree the fork inherited rather than debt it created, and a
hard zero would be unshippable. The floor lives in
`tooling/ratchet/baselines/` like every other, in `exact` mode: a module that
ships a suite into silence pushes the count up and fails; a lane that closes one
lowers it and is banked in the same change. The backlog is not this record's
subject. The eighteenth module joining it silently is.

## Alternatives considered

**Scope the gate to fork-native modules only.** The 418 are almost all
upstream, and the modules this fork is answerable for are far fewer. Rejected
because there is no reliable membership rule. The obvious one — the manifest's
`author` — fails on the first case tried: `base_order` declares
`"author": "Odoo Community"` and is fork-native in every way that matters, with
70 test methods, four dependents and a `test_base_order` written for it. A rule
that misses the module which motivated the gate is not a rule.

**Require a lane per module.** Rejected on cost. A lane is an install, a
database and minutes of CI; 418 of them is not a proposal. The ratchet asks only
that the number not grow, which is the property that was missing.

**Count installs rather than tags.** Simpler to write and wrong, for the `sale`
reason above. It would also have reported `document_extract_hr_recruitment_skills`
as covered on the day it broke, since the family installs together.

**Leave it to review.** This is what was in place. Two modules with 289 test
methods between them had never run, and the framework regression that prompted
the census was found by chance while verifying something else.

## Consequences

A new module that ships tests fails the gate until it is either given a lane or
written into `EXEMPT` with a reason. That is a real cost at the moment a module
is added, and it is the point: the alternative is discovering in a year that its
suite has never executed.

`EXEMPT` is a list of decisions, not a list of exceptions. `credential` and
`api_transport` are in it because CLAUDE.md §9.6 records a decision not to lane
them and states the cost; a third name arriving without one is visible in a
diff.

The gate cannot tell a passing suite from a failing one — only whether anything
runs it. A module named in a lane whose tests are all skipped reads as covered.
That is the count guard's job in each lane, and every lane added since carries
one.

**A lane that passes `--test-enable` and no `--test-tags` is outside what this
can read.** Such a lane runs the tests of whatever it installs, and `agromarin`'s
`tests.yml` is one: it discovers its module list at run time
(`-u ${{ steps.discover.outputs.modules }}`) and names no tag. What it covers is
not in the file, and no amount of parsing recovers it. The gate refuses rather
than guessing — pointed at that repository it reports that it found nothing to
compare against, instead of declaring all 117 of its tested modules uncovered.
That is the second refusal direction `test_every_gate_refuses_an_empty_tree`
holds it to, and the reason it exists: a broken scan and a full-tree finding look
identical in the output.

Two lanes were added ahead of this record and are the evidence it is affordable:
`document_extract` and its five bundled consumers (171 tests), and `base_order`
with `test_base_order` (281). Both were green on their first run, so neither
lane was a repair; the difference is between passing and being known to pass.

## Enforcement

`tooling/architecture/module_suite_lane.py`, run by `architecture.yml` against
the `suite_lane` ratchet baseline. `test_gate_adr_coverage` binds it to this
record; `test_every_gate_refuses_an_empty_tree` holds it to refusing a tree it
cannot measure, in both directions — no module with tests, and no lane naming
any module.

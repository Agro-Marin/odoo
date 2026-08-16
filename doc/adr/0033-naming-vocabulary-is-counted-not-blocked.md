# ADR-0033: The naming vocabulary is a count, and only the decidable part of it

- **Status:** Accepted
- **Date:** 2026-08-14 (retroactive — records a decision already enforced)

## Context

`doc/coding_guidelines.rst` §2.4 fixes one canonical verb per operation and
abolishes the synonyms that used to compete with it. The rule matters more here
than style rules usually do: this fork's stated posture is that canonical names
make redundancy *detectable* — two methods normalising to one name **is** the
duplicate report — so naming is instrumental to the refactoring work, not
decoration on top of it.

Stated in a document, the rule was a claim nobody could check. The tree opens
with hundreds of definitions still spelled the abolished way.

Two things follow, and they pull in opposite directions. A rule this load-bearing
should be enforced. A blocking gate would fail every build on day one and be
switched off within a week.

## Decision

**Count the abolished spellings and ratchet the count. Do not block on them.**

The ratchet freezes the number where it stands, fails on any increase, and makes
each cleanup batch lower the floor permanently. That is the same shape the
function-length and service-shape budgets use (ADR-0025, ADR-0021), applied to a
naming rule — and it is the only shape that survives contact with a backlog of
this size.

### Only the mechanically decidable part is counted

Three of §2.4's rules are real and **not** decidable from a name, and they are
deliberately excluded. The clearest is the split between two prefixes whose
discriminator is *"does the return value feed a write"* — a question about the
**caller**, not about the name, across more than a thousand candidate
definitions.

**A ratchet number nobody can lower by reading the rule is a number people learn
to ignore.** Including the undecidable rules would inflate the count with
findings that cannot be acted on, and the first person who tried to drain it
would discover that most of it was noise. So the gate counts what a definition's
own name settles, and the rest stays a review rule — stated as such rather than
silently dropped.

## Alternatives considered

**Block on abolished verbs.** Rejected on the arithmetic: hundreds of findings on
day one, every build red, and a gate disabled within a week. That outcome is
strictly worse than a ratchet, because a disabled gate protects nothing and
teaches everyone that this class of gate is negotiable — which is the state
ADR-0006 was written to end.

**Count everything §2.4 says, decidable or not.** Rejected, and this is the more
interesting rejection: it would produce a bigger, more impressive number that
nobody could move. A budget's whole value is that lowering it is possible and
attributable; a budget padded with undecidable findings is a number that only
goes up, and it discredits the decidable part along with itself.

**Fix the tree first, then gate at zero.** The end state, and not affordable as a
first step: the backlog is large, the cleanups touch code owned by many people,
and nothing would hold the line while the work proceeded. The ratchet holds the
line *during* the work, which is the only period that matters.

**Leave it to review, as the guidelines already did.** That is the state this
replaced. The rule existed, was correct, and the count was unknown — so nobody
could tell whether the tree was converging on it or drifting away.

## Consequences

- The backlog is a number that can only fall, so naming cleanups are permanent
  rather than re-spent, and a new abolished spelling fails the build.
- **Part of §2.4 remains unenforced, on purpose**, and the record says which
  part rather than letting a green gate imply the whole section is held.
- The count is a proxy for the property the fork actually wants — that redundant
  methods become detectable — and it is not the property itself. Two methods can
  carry canonical names and still be duplicates.
- The gate covers this repository only. The sibling repos are ungated for §2.4,
  so a regression there is caught by nothing and a fix there is credited by
  nothing — which makes their counts drift rather than fall, and is a known open
  gap rather than an oversight.

## Enforcement

One gate in `tooling/architecture/`, declaring `ADR = "0033"`, run by
`.github/workflows/architecture.yml` and `.github/workflows/unit_tests.yml`
against a floor in `tooling/ratchet/baselines/`:

| gate | ratchets |
|---|---|
| `tooling/architecture/naming_vocabulary.py` | definitions spelled with §2.4's abolished verbs, in this repository |

`tooling/architecture/test_gate_adr_coverage.py` checks that the citation
resolves to this record and that it is `Accepted`. For the live count, run the
gate — this record does not restate it.

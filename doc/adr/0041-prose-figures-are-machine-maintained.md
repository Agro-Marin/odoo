# ADR-0041: A figure stated in prose is regenerated, not retyped

- **Status:** Accepted
- **Date:** 2026-08-16

## Context

The architecture pages and several core docstrings quote measurements. "the 621
bundled modules", "**1,110 test methods**", "``self._name`` has 374 sites and
``self._fields`` 334". They are worth quoting: a budget without a magnitude is
not an argument, and every one of these sentences is making an argument that
needs its scale.

ADR-0022 and `doc_measured.py` already settled this for a gate's own docstring.
A participating gate carries a `MEASURED` block of `key=value` pairs,
`--update-doc` rewrites it, and a test compares it against a fresh measurement.
That works because a gate docstring can carry a stanza without reading badly.

A narrative page cannot. Replacing "the 621 bundled modules" with a pointer to a
block above costs the sentence the very thing the block exists to preserve. So
these figures stayed hand-written, and rotted exactly as `doc_measured.py`'s own
docstring predicts. Two were live in this tree at once:

- `doc/architecture/gates.md` said 619 bundled modules against 621 on disk.
- `odoo/orm/models/mixins/_metadata.py` said `self._name` had 375 call
  sites against 374.

Both were caught only because `test_architecture_doc.py` happened to re-derive
them. That is the good case. The test is what made the drift visible, and it is
also what made it *stay* visible: a red gate nobody can fix without hand-editing
the number back is a gate that trains people to hand-edit numbers back.

Note what the failing test could not do. It knew the true value and refused the
stale one, but it offered no way to write the true value down — so the only
route to green was to retype the digits, which is the habit the rule exists to
remove. A checker without a generator is half a mechanism.

## Decision

**Every figure a document states in prose is owned by
`tooling/architecture/doc_restated_counts.py`, which measures it, checks it and
rewrites it.** The number stays inside the sentence. The measurement lives in
one place. `--update` rewrites the digits after the change that moved them.

`FIGURES` is the list: a name, the file, a whitespace-tolerant pattern whose
groups are the digits, the measurement, and how to render it. A figure whose
sentence changes shape raises rather than silently ceasing to be checked, which
is the failure mode a regex-matched document invites.

This does not replace `doc_measured.py`. The two divide on where the number
sits: a `MEASURED` stanza in a gate's own docstring, prose everywhere else. A
gate quoting its own metrics should still use `doc_measured.py`, because a
stanza it can regenerate wholesale is simpler than a pattern per sentence.

## Alternatives considered

**Retype the digits and move on.** What every previous drift did, and what the
failing test invited. It is not a decision, it is the absence of one: the number
was already wrong twice, in a tree that has a test re-deriving it, which is the
best case a hand-maintained figure gets.

**Delete the figures.** `.github/workflows/typecheck.yml`'s header draws exactly
this rule after being burnt — *do not restate a floor's value in this comment*.
It is the right rule for a floor, whose value carries no argument beyond "this
is the current one". These figures are not floors. "the most widely used surface
in the framework" is an assertion; 380 call sites is why the reader believes it.
`doc_measured.py`'s docstring already rejected this trade for the same reason.

**Put a `MEASURED` block in the pages.** The mechanism exists and is proven, and
this was the first thing tried. It fails on the page: a narrative paragraph
cannot host a `key=value` stanza, and a sentence that defers to one ("the
bundled modules, see the MEASURED block above") has given up the concreteness
the block was added to protect. The stanza belongs where a stanza reads well.

**Make every figure exact.** The first cut did, and `metadata_call_sites` broke
it within the hour: it counts `self._name` across both addon trees, so an
ordinary model commit moved it by six and turned the gate red for whoever ran it
next. `pyfunclen_addons` met the same wall and answered with `--mode
no-increase`; the answer here is a tolerance band and a sentence that says
"about", which is what the argument needed anyway. Figures scoped to one addon
stay exact, because they move only when someone deliberately moves them.

## Consequences

- `test_architecture_doc.py` delegates to `check()`, so a stale figure fails in
  the same lane as the gates it sits beside, and the failure names the command
  that fixes it.
- The measurement is defined once. Before this, `test_architecture_doc.py` held
  the only definition of how the bundled-module count and the `self._name` call
  sites were counted, and nothing could re-derive them outside a test run.
- A new prose figure is one entry in `FIGURES`. A figure nobody adds there is
  not checked at all — the list is the inventory, and the gate cannot discover
  a sentence it was never told about.
- Adding a figure to a document without adding it to `FIGURES` is invisible.
  This is the same limit `esm.external_libs` and every other declaration-driven
  gate carries, and it is preferred to scanning prose for anything that looks
  like a number, which would flag the arguments themselves.

## Enforcement

`test_architecture_doc.TestAddonSuiteFigures.test_every_prose_figure_is_fresh`
calls `doc_restated_counts.check()`, so a drifted figure fails in
`architecture.yml` alongside the gates, and the assertion names the `--update`
command that fixes it. `test_gate_adr_coverage` binds this record to the module,
and `test_every_gate_refuses_an_empty_tree` probes it.

What is *not* enforced: that a figure added to a document is added to `FIGURES`.
Nothing scans prose for unregistered numbers, because the pages argue with
numbers throughout and a scanner would flag the arguments. `FIGURES` is a
declaration, like `esm.external_libs`, with the same known limit.

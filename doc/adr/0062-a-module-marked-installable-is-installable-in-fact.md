# ADR-0062: A module marked installable is installable in fact

- **Status:** Accepted
- **Date:** 2026-08-24

## Context

Disabling a module is a standing practice in this fork. When a replacement lands
— a fork module that does the job differently — the module it replaces is marked
`installable: False` rather than merely uninstalled, because both it and its glue
are often `auto_install` and the next module update would otherwise bring them
back and break the replacement silently.

That edit reaches further than the module it is written in. Every module that
depends on the disabled one becomes unreachable, and Odoo does not treat that as
an error. The module graph drops the dependent with a single warning and carries
on:

```
module l10n_in_reports: some depends are not loaded
(account_invoice_extract), skipped
```

The dependent is then left committed in state `to install`, and `odoo-bin` exits
0. There is no failure to read. No suite runs, because the module never loads;
no lane goes red, because nothing asked; and the module is indistinguishable
from one nobody installed on purpose.

That is what happened when `account_document_extract` replaced
`account_invoice_extract`. Three modules depended on the disabled one, two of
them using nothing from it but a line in `depends`. One was Indian GST
reporting, a live localization, which sat unreachable from the day of the
replacement until it was found on 2026-08-24 by reading manifests — not by any
gate, and not by the run that installed it and reported success.

The asymmetry is what makes this accumulate. The edit that disables a module and
the edits that would save its dependents are in different modules, often in
different repositories, and the person making the first has no reason to look
for the second. Nothing in the change under review looks wrong.

The question is cheap. Every manifest states whether its module is installable
and what it depends on; a pass over them answers it in under a second, with no
database and no import.

## Decision

`tooling/architecture/module_depends_installable.py` reports every module that
does not declare itself uninstallable and names, in `depends`, a module that
does. `.github/workflows/architecture.yml` runs it with `--check`, which fails
the build on any occurrence.

The rule is deliberately narrow: both modules are on disk, one states outright
that it cannot be installed, and the other states that it needs it. There is no
reading of that pair which is correct, so there is nothing to argue about at a
call site.

A dependency that resolves to no module in the scanned roots is **not** an
offence. The scanned roots are rarely the whole addons path — a sibling repo's
lane sees its own tree and what it is given — and `addons_data_dir` can supply a
module at runtime that no checkout contains. Reporting absence would make the
gate argue with its user about scope instead of about the rule.

A contract, not a ratchet. At this decision the workspace has no occurrence, and
the fix for any single one is small: drop the dependency, port what was used, or
mark the dependent uninstallable too. A floor would bank the next silent
breakage for as long as someone was willing to leave it there.

## Alternatives considered

**Leave it to `module_installability.yml`.** That lane already asks whether the
graph assembles, and it is the only lane that touches most bundled modules. It
does not answer this: a skipped module is exactly what the loader considers a
successful assembly, so the lane passes while the module is unreachable. Making
it fail on a skip would mean reading its logs for a warning, which is the
counting-by-grep failure `CLAUDE.md` §4 warns against.

**Make the loader raise instead of warning.** The right end state, and out of
reach here: a partially available addons path is a legitimate deployment, and a
module absent because it was never checked out is indistinguishable at load time
from one absent because it was disabled. The static check knows the difference,
because it can see the manifest that says so.

**Forbid `installable: False` and delete the module instead.** Deleting an
upstream module is a much larger edit that has to be re-applied on every sync,
and it destroys the record of what was replaced and why — which is the argument
those manifests carry. It would also not help: a dependent naming a module that
no longer exists fails in the same silent way.

**Check it in `test_lint`.** That module holds the manifest conventions no
general linter knows, which is the right neighbourhood. It runs inside a
database against the modules that loaded, so the one module it cannot see is
precisely the one that was skipped.

**Review.** The two harmless dependents were single lines in a `depends` list,
in modules whose diffs had nothing else to do with extraction. There is nothing
in either to notice.

## Consequences

A change that disables a module fails the build until its dependents are
resolved, in the same change rather than whenever someone next reads a manifest.
The cost is one pass over the manifests in `architecture.yml`.

Absence stays unchecked. A dependency naming a module that exists nowhere fails
the same silent way and this gate is quiet about it, by the scope argument
above. Measured on 2026-08-24 the workspace carried one such case. Closing that
needs a scope the gate can trust to be complete, which the odoo lane is not.

The default scope is the `odoo` checkout, because that is what CI checks out.
The defect this record was written for was entirely inside a sibling repository,
one module depending on another beside it, which the default scope cannot see.
The sibling lanes pass `--roots` themselves, the arrangement `CLAUDE.md` §9.4
describes for the naming gate, and until a sibling wires it a regression there
is caught by nothing.

## Enforcement

`tooling/architecture/module_depends_installable.py --check` in
`.github/workflows/architecture.yml`, blocking. `tooling/architecture/test_module_depends_installable.py`
covers the rule and its refusals, and the gate is registered in
`tooling/architecture/test_every_gate_refuses_an_empty_tree.py` so that a scan
finding no manifests refuses rather than reporting a clean zero.

## Amendments

### 2026-08-25 — the module named in the Context has been renamed

The record names `account_document_extract` as the replacement whose arrival
made `account_invoice_extract` uninstallable, and names the dependents that were
stranded by it. That module is now `document_extract_account`: the consumers
were moved into `addons/` beside the framework they extend, and renamed to carry
its prefix so the family reads as one, the shape `documents_account` already
uses. The decision, the gate and the defect it was written for are unaffected --
only the spelling of one module in the narrative.

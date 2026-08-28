# ADR-0073: A Python import across repositories must resolve too

- **Status:** Accepted
- **Date:** 2026-08-28

## Context

ADR-0031 and ADR-0072 are about JavaScript. Both start from the same premise — a
consumer in one repository imports a provider in another, the two are versioned
separately, and CI in each sees only its own tree — and neither of them, nor any
gate they name, looks at a `from odoo.addons.X import`.

The consequence was live and published when this was written:

    agromarin/mcp_server/controllers/xmlrpc.py:   from odoo.addons.rpc.tools import preflight
    agromarin/mcp_server/field_denial.py:         from odoo.addons.rpc.tools.preflight import mentioned_field_names
    agromarin/mcp_server/models/mcp_dispatcher.py: from odoo.addons.rpc.tools import preflight

Three top-level, unguarded imports on `origin/19.0`, of a package that exists on
no pushed branch of any repository in the workspace. `mcp_server` cannot be
imported against the published community fork, so it cannot install. Both
repositories' CI reported green throughout.

The Python failure is quieter than the JS one and so worth stating separately. An
unsatisfied named import kills a whole asset bundle, which is loud. An
`ImportError` at module load makes one addon uninstallable, which reads as a
deployment problem in whichever environment installs that addon first — and the
repository whose commit caused it is not the repository where it surfaces.

## Decision

**A gate resolves every executed `odoo.addons.X.Y` import against the addons
roots it is given, and reports the ones that resolve to nothing.**
`tooling/architecture/py_addon_imports.py`, the Python twin of
`named_export_coherence`, sharing its topology for the reason that gate already
records: this repository's CI checks it out alone, so its own run covers
intra-repo drift, and each sibling re-runs it from its own lane with this
checkout beside it.

**An addon whose tree is absent yields no verdict.** An absent checkout is not a
missing module, and a gate that guessed would be one nobody could keep green.

**Only the module path is resolved, never the attribute.** Whether a module
defines a name is not decidable from the import line, and `named_export_coherence`
owns that question on the JS side without a Python counterpart being owed one:
Python raises `ImportError` at the point of use with the name in it, which is a
diagnosis, not a silent bundle death.

## Alternatives considered

**Fold it into `named_export_coherence`.** Rejected on the reasoning ADR-0072
used in the opposite direction: there, two gates shared a question and were
merged because the analyses turned out to overlap. Here they do not. One reads
JS module graphs and export chains; the other reads Python ASTs and package
directories. One number over both would let a Python regression hide behind a JS
fix.

**Check the attribute as well.** Rejected as undecidable without importing: a
name may be produced by `__getattr__`, by a star import, or by a conditional
definition. A gate that guessed would be wrong in the direction that costs most —
a false positive on a working import.

**Skip test files.** Rejected. It would have removed the `rd_sides` and `pb_base`
false positives at the cost of most of the gate's real subject: a cross-addon
test import is the commonest form of this dependency, and `test_mail`'s reach
into `mail` is exactly the kind that breaks on a move. The runtime-assembled
trees are exempted by name with the reason instead.

**Leave it to installability CI.** `module_installability.yml` does install every
bundled module and would raise the `ImportError` — in the repository that does
not contain the importer, at `--addons-path=odoo/addons,addons`, where the
importer is not on the path. It answers a different question at a scope that
cannot see this one.

## Consequences

- A sibling importing a core module that does not exist is reported in that
  sibling's own lane, naming the file and the module.
- Four classes are exempt, each measured rather than assumed, and each named with
  its reason in the script: `if TYPE_CHECKING:` imports, which never execute;
  namespace packages, which import without an `__init__.py`; the IoT box's
  `iot_drivers/iot_handlers/` tree, which the box empties and re-downloads from
  every installed module; and the addons the routing tests write into a temporary
  addons path.
- The gate does not close the window that ADR-0072's *Alternatives considered*
  leaves open, and does not claim to. A commit here that deletes a module a
  sibling imports still reports in the sibling, after the fact. The scheduled
  sibling workflows added alongside this bound that window at a day; a
  cross-owner checkout would close it, and stays blocked for ADR-0009's reason.

## Enforcement

`tooling/architecture/py_addon_imports.py`, run with `--check` from
`architecture.yml` here and from `enterprise` and `agromarin`'s own lanes with
this checkout beside them. Registered in
`tooling/architecture/test_every_gate_refuses_an_empty_tree.py`, so a scan that
reaches nothing is an error rather than a pass.

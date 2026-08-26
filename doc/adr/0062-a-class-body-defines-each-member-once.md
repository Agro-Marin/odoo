# ADR-0062: A class body defines each member once

- **Status:** Accepted
- **Date:** 2026-08-25

## Context

`ir.ui.view` carried two definitions of `_migrate_self_handled_arch` — one at
line 454, one at line 3058 of the same class body. Python keeps the last, so the
one at 454 never ran. Neither the tests nor any gate said so.

The two arrived in the wrong order. `b6c0619c571` added the lower one on
2026-08-02. `51208aac5e8` added the upper one on 2026-08-05, and its commit
message opens:

> `ir.ui.view._migrate_self_handled_arch` — Did not exist, so its four tests
> errored.

It did exist. A second implementation was written to a considered spec, the spec
never ran, and the four tests passed against the other implementation for three
weeks. One behavioural difference survived the review that found this: the
surviving code wrote through `arch` with no `no_save_prev`, spending
`arch_prev` — a single slot, and the default mode of the reset-view wizard — on
a mechanical respelling.

This is the shape a parallel edit produces. Several sessions work this workspace
against the same checkouts (`CLAUDE.md` §12); two of them adding the same method
at opposite ends of a 3,000-line class conflict in neither git nor review, and
the winner is whichever sits lower in the file.

`ruff` selects F811 (`redefined-while-unused`) for exactly this, and it does not
fire. The default `lint.dummy-variable-rgx`,
`^(_+|(_+[a-zA-Z0-9_]*[a-zA-Z0-9]+?))$`, matches any leading-underscore name and
removes it from redefinition analysis. In an Odoo model essentially every method
is `_`-prefixed, so **F811 covers none of them**:

```
$ printf 'class B:\n    def m(self):\n        return 1\n\n    def m(self):\n        return 3\n' > a.py
$ ruff check a.py --select F811 --isolated
F811 Redefinition of unused `m` from line 2          # 1 error

$ sed 's/def m/def _m/' a.py > b.py
$ ruff check b.py --select F811 --isolated
All checks passed!
```

## Decision

A class body defines each member once. A second `def`, nested `class`, or
assignment of a name already bound in the same body is a defect, measured by
`tooling/architecture/py_shadowed_member.py` and ratcheted to zero.

Scope is the class body, not the module. Redefining a module-level class is out
of scope: `test_orm` and `test_inherit` do it deliberately, and a fixture that
redeclares a model is not a shadowed member. So are the families that redefine a
name on purpose — `@overload`, `@property` with its `.setter`/`.getter`/
`.deleter`, and `functools.singledispatch` `.register`.

## Alternatives considered

**Tighten `lint.dummy-variable-rgx` to `^_+$`.** This is the obvious fix and it
was measured before being rejected. The regex is shared by six rules, and over
this tree the collateral is not close:

| Rule | before | after | delta |
|---|---|---|---|
| RUF059 unused-unpacked-variable | 5 | 859 | +854 |
| B007 unused-loop-control-variable | 18 | 312 | +294 |
| F841 unused-variable | 25 | 110 | +85 |
| F811 redefined-while-unused | 1 | 8 | **+7** |
| PLW0128, ARG002 | 1 | 9 | +8 |
| whole repo | 3400 | 4648 | +1248 |

`ruff check odoo/` and `ruff check tooling/ tests/` are both hard zeros with no
floor to absorb anything, and they would report 280 and 131 findings
respectively — 279 unwanted per wanted one, in the gated scope alone. Ruff
offers no per-file `dummy-variable-rgx`, so the collateral cannot be scoped away.

**Review.** This is what was already in place. It read the diff of a commit that
added a method and could not see the definition 2,600 lines below it.

**A `__init_subclass__` or registry-time assertion.** It would catch the same
thing at import, but only for models, only once the registry is built, and with
no way to state a floor while the existing offenders are paid down.

## Consequences

The gate is one AST pass, ~15s over all four checkouts, and finds the seven real
offenders with no collateral:

```
addons/stock/models/product_template.py:631  ProductTemplate._search_variant_quantity
addons/stock/models/product_template.py:677  ProductTemplate._search_qty_available
addons/stock/models/product_template.py:680  ProductTemplate._search_qty_available_virtual
addons/stock/models/product_template.py:683  ProductTemplate._search_qty_incoming
addons/stock/models/product_template.py:686  ProductTemplate._search_qty_outgoing
addons/stock/models/product_template.py:837  ProductTemplate._resolve_diagram_products
odoo/addons/base/models/ir_ui_view.py:3058   IrUiView._migrate_self_handled_arch
```

`stock/models/product_template.py` carries a verbatim duplicated block of five
`_search_qty_*` methods and their shared helper, in the file's only class — the
same accident, in a second file, undetected for the same reason. It is paid down
in its own commit rather than this one.

The cost is that a genuine redefinition now needs a decorator that says so. That
is the point: `@overload` and `@property.setter` state the intent, and a bare
second `def` does not.

## Enforcement

`tooling/architecture/py_shadowed_member.py`, run from `architecture.yml` over
`odoo/` and `addons/`, each against its own ratchet baseline. The sibling
checkouts (`enterprise`, `agromarin`, `design-themes`) are governed scopes from
the start and ride the cross-repo `architecture.yml` those repos already carry.

`tooling/architecture/test_py_shadowed_member.py` covers the rule and each
deliberate-redefinition exemption; `test_every_gate_refuses_an_empty_tree`
covers the refusal to report zero over a tree it never read.

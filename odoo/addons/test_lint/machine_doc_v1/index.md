# test_lint — map

The fork's own gates: the rules no general linter knows. 9410 lines and no map
until now, which is why `CLAUDE.md` §10 makes a module's machine doc the first
pre-work step.

Every figure below is derived by `odoo/addons/test_lint/machine_doc_v1/factcheck.sh` from the tree, never restated
here as a literal that can drift.

## Two halves

| | |
|---|---|
| **`_rules.py`** | the vocabulary: what a rule *is* -- name, short code, advice -- and which checker emits it. Adding a rule is an entry here and nothing else. |
| **`_py_scan.py`** | the engine: corpus, parallel scan, caching, suppression. Owns nothing about any individual rule. |

A rule used to be spelled in six places and three tests existed only to keep the
copies agreeing. `test_python_lint.py` iterates the registry.

## Where the floors live

**Not in Python.** `LintCase.assert_ratchet` takes a ratchet *gate name* and
reads `tooling/ratchet/baselines/`; handed an integer it raises. Absence of a
baseline file means a floor of zero.

```bash
python tooling/ratchet/ratchet.py --list | grep '^lint_'
python tooling/ratchet/ratchet.py <gate> --count N --update --note '<what moved and why>'
```

This module was edited as a shared ledger: 24 of its last 40 commits changed
nothing in it but an integer and the comment above it.

## The checkers

Pure AST, stdlib only, no odoo import — so they are unit-testable without a
database, and `test_checkers.py` does exactly that.

| file | rule(s) |
|---|---|
| `_checker_sql.py` | `sql-injection` |
| `_checker_gettext.py` | `gettext-variable`, `gettext-placeholders`, `gettext-repr`, `missing-gettext`, `gettext-developer-error` |
| `_checker_batch.py` | `n-plus-one-query` |
| `_checker_unlink.py` | `raise-unlink-override` |
| `_checker_orm_import.py` | `orm-import` |
| `_checker_onchange.py` | `onchange-domain` |
| `_checker_config_patch.py` | `config-chainmap-patch` |
| `_checker_noqa_rationale.py` | `noqa-rationale` |
| `_checker_translated_unique.py` | `unique-over-translated-column` (cross-unit) |
| `_checker_pep649.py` | annotation resolution, used by `test_pep649` |

`unreadable-source` has no checker file of its own: the engine emits it when a
file cannot be parsed or tokenised. Both used to be swallowed, and a file whose
comments cannot be read is one whose every waiver is silently inert.

## The fixers, and what they may not change

| | invariant | why |
|---|---|---|
| `_pretty_xml.py` | `_xml_identity.is_faithful` | order-**preserving**: it only reindents |
| `_sort_xml_records.py` | `_xml_identity.preserves_content` | order-**insensitive**: reordering is the job |
| `_sort_manifests.py` | its own round-trip check | |

`_xml_sweep.py` runs a fixer over every data file **once**; the gates read the
result rather than each making their own pass.

## Scope, and what it excludes

`lint_case.is_core_path` scopes every gate to this checkout. `_py_scan.corpus()`
additionally drops `_vendor/`, `upgrades/` and `migrations/`;
`_pretty_xml.is_formattable` drops `_vendor`, `static`, `node_modules` and
`tests`, because a fixture is not a data file.

**The sibling repositories are gated from their own CI.**
`tooling/lint/py_lint.py` runs these same checkers over any roots without
odoo-bin, and `enterprise`, `agromarin` and `design-themes` each call it with
`--check --scope <repo>` from their "Architecture Boundaries (cross-repo)"
workflow, which already checks this fork out beside itself. Their floors live
here, scoped by provenance, alongside every other floor:

```bash
python tooling/ratchet/ratchet.py --list | grep -E '^lint_.*_(agromarin|enterprise|design-themes)'
python tooling/lint/py_lint.py ../agromarin --check --scope agromarin
python tooling/lint/py_lint.py odoo addons --count   # agrees with the gate, rule for rule
```

Those runs are `--mode no-increase`: an exact floor across a repository boundary
would make every fix in a sibling red until a matching commit landed here to bank
it. **Lowering a sibling floor therefore needs a workspace holding all four
checkouts**, which is what `naming` already asks for.

`tooling/lint/test_py_lint.py` pins what makes the tool worth trusting: the
corpus exclusions, the addon/framework split (which decides whether the facade
rule applies), and that a rule driven to zero keeps being evaluated.

## Lanes

| workflow | scope |
|---|---|
| `.github/workflows/test_lint.yml` | the whole module, every PR, `--addons-path=odoo/addons,addons`, only `test_lint` installed |
| `.github/workflows/asset_lint.yml` | the registry-dependent classes, against a wider INSTALL set |

**A gate that reads the installed registry cannot be graded at the narrow
scope.** `TestSchemeDuplication` skips there rather than passing, naming the
modules it cannot see; `TestDocstring` is one-sided (`exact=False`) for the same
reason. Do not floor either at a `.github/workflows/test_lint.yml` reading.

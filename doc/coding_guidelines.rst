.. _coding_guidelines:

===========================
AgroMarin Coding Guidelines
===========================

:Version: 6.3
:Date: 2026-08-23
:Base: `Odoo 19.0 Coding Guidelines <https://www.odoo.com/documentation/19.0/contributing/development/coding_guidelines.html>`_
       + `OCA CONTRIBUTING.rst <https://github.com/OCA/odoo-community.org/blob/master/website/Contribution/CONTRIBUTING.rst>`_

The coding standard for the AgroMarin fork of Odoo 19.0. Authoritative where it
speaks; where silent, follow upstream Odoo 19, then OCA. Fix a stale claim in the
same PR as the code that made it stale.

.. contents::
   :local:
   :depth: 2

----

How rules are enforced
======================

Each rule carries a bracketed label naming what catches it.

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Label
     - Meaning
   * - ``[ruff CODE]``
     - ``ruff check`` reports it.
   * - ``[test_lint CODE]``
     - A ``test_lint`` checker fails on it. ``E8501``--``E8507`` are the AST
       checkers; other ``test_lint`` gates have no code and are named by test.
   * - ``[fixer NAME]``
     - A behaviour-preserving fixer owns the formatting. Run it; do not hand-edit.
   * - ``[ratchet NAME]``
     - A committed floor in ``tooling/ratchet/baselines/`` holds the count.
   * - ``[gate NAME]``
     - A ``tooling/`` gate checks it exactly, both directions. Where the gate
       rewrites the text (``doc_restated_counts`` for prose figures), run it.
   * - ``[review]``
     - No tool checks this. A human does, using §9.

Do not infer enforcement from phrasing: several rules that read like lint rules
are ``[review]`` because the ``ruff`` code is disabled with a rationale in
``ruff.toml``.

The ratchets
------------

``ruff check`` is not clean and CI does not require it to be. Countable gates are
*ratchets*: a total measured against a committed floor in
``tooling/ratchet/baselines/``. Rationale: ADR-0006.

**A ratchet fails in both directions.** ``ratchet.py`` defaults to ``exact``, so
an improvement fails the build as a regression does. Commit the new floor in the
same PR:

.. code-block:: bash

   python tooling/ratchet/ratchet.py <gate> --count <N> --update

``.pre-commit-config.yaml`` runs ``ruff-check --fix``, so touching a file that
carries baseline findings can repair unrelated ones and drop the count. A green
local commit is not a green CI run unless the floor moved with it.

``pyfunclen_addons`` is the one exception, at ``--mode no-increase``: it measures
the whole bundled-addons tree, which moves both ways continuously. Prefer
``exact`` for every new floor, and record the argument here if you cannot have it.

.. list-table::
   :header-rows: 1
   :widths: 16 30 22 32

   * - Gate
     - Command
     - Scope
     - Workflow
   * - ruff
     - ``ruff check odoo/ --no-cache --statistics``
     - ``odoo/`` only -- a **hard zero**
     - ``.github/workflows/ruff.yml``
   * - c901
     - ``ruff check odoo/ --no-cache --select C901 --statistics``
     - ``odoo/``, complexity > 20
     - ``.github/workflows/ruff.yml``
   * - c901_addons
     - ``ruff check addons/ --no-cache --select C901 --statistics``
     - ``addons/``, complexity > 20
     - ``.github/workflows/ruff.yml``
   * - mypy
     - ``mypy -p odoo.orm -p odoo.db -p odoo.libs -p odoo.http -p odoo.service -p odoo.modules``
     - typed packages
     - ``py_typecheck.yml``
   * - ESLint
     - ``npx eslint . --format=json``
     - all JS
     - ``lint.yml``
   * - ``tsc``
     - ``npx tsc --project tsconfig.json --noEmit``
     - all checked JS
     - ``typecheck.yml``
   * - naming vocabulary
     - ``tooling/architecture/naming_vocabulary.py``
     - §2.4 abolished verbs
     - ``architecture.yml``, ``unit_tests.yml``
   * - Python function length
     - ``tooling/architecture/py_function_length.py``
     - core Python, **excess lines** over 80
     - ``architecture.yml``
   * - Python function length (addons)
     - ``tooling/architecture/py_function_length.py --addon addons``
     - all of ``addons/``, same metric, **one-sided**
     - ``architecture.yml``
   * - JS function length
     - ``tooling/architecture/js_function_length.py``
     - ``web`` JS
     - ``architecture.yml``
   * - JS private access
     - ``tooling/architecture/js_private_access.py``
     - ``web`` JS, cross-module
     - ``architecture.yml``
   * - JS service shape
     - ``tooling/architecture/js_service_shape.py``
     - ``web`` JS services
     - ``architecture.yml``
   * - JS forced render
     - ``tooling/architecture/js_forced_render.py``
     - ``web`` JS
     - ``architecture.yml``

``tooling/ratchet/baselines/`` is the authoritative list -- one JSON per gate, and
the directory is the count. No number is written here on purpose:

.. code-block:: bash

   python tooling/ratchet/ratchet.py --list

Every architecture gate declares its record as a module-level ``ADR`` constant,
which ``test_gate_adr_coverage.py`` checks resolves to an ``Accepted`` record.

Consequences:

* **The ruff ratchet measures ``odoo/``, not ``addons/``.** For addons, ``ruff``
  is pre-commit and review discipline.
* **A finding on a file you touched may predate you.** Compare against
  ``git diff``, not a whole-file lint report.
* **``ruff`` is a hard zero over the whole selected ruleset.** A nonzero floor
  launders a regression against an unrelated improvement.
* **``ruff`` and ``c901`` are two floors over one command.** ``ruff.toml``
  ignores ``C901`` to keep it out of the aggregate; the ``c901`` step re-selects
  it on the CLI. Raising ``[lint.mccabe] max-complexity`` lowers the count
  without fixing anything -- move it as deliberately as the floor, and say so in
  the baseline note.
* **The architecture gate is not a ratchet.** Layer crossings and JS import
  cycles are held at zero (``tooling/architecture/js_cycle_check.py``, ADR-0019;
  ADR-0034 is the Python counterpart), with pre-existing ones pinned in
  ``KNOWN_CYCLES`` / ``KNOWN_VIOLATIONS`` with a rationale. ``test_lint``
  ratchets are counted inside the module's own ``assert_ratchet``.

Each gate runs on ``pull_request`` and on ``push`` to ``19.0-marin`` / ``19.0``.

The ``test_lint`` module
------------------------

``odoo/addons/test_lint`` holds AST checkers and registry-level tests encoding
Odoo-specific rules no general linter knows. Every rule is an exact-match ratchet
(``LintCase.assert_ratchet``): the count may not rise, and may not fall silently.

Two CI lanes. ``test_lint.yml`` installs ``base`` + ``test_lint`` and runs
``/test_lint`` on every PR with no ``paths:`` filter, because these gates scan the
whole tree; ``asset_lint.yml`` covers the classes needing a real registry
(bundles, dark siblings, ESM specifiers). ``integration_tests.yml`` runs neither.

Run it before opening a PR touching Python, XML or manifests:

.. code-block:: bash

   odoo-bin -d <db> -i test_lint --test-enable --stop-after-init

.. list-table::
   :header-rows: 1
   :widths: 26 12 62

   * - Gate
     - Code
     - Rule
   * - ``_checker_sql``
     - ``E8501``
     - Dynamic SQL built by interpolation (§10.4). **Fails the build.**
   * - ``_checker_gettext``
     - ``E8502``
     - ``_()`` / ``_lt()`` called with a non-literal first argument (§8.1)
   * -
     - ``E8503``
     - Two or more *unnamed* placeholders in a translated string (§8.1)
   * -
     - ``E8504``
     - ``%r`` inside a translated string (§8.1)
   * -
     - ``E8505``
     - Raw string literal passed to a user-facing exception (§2.7)
   * - ``_checker_unlink``
     - ``E8506``
     - ``raise`` inside an ``unlink()`` override (§2.6)
   * - ``_checker_batch``
     - ``E8507``
     - Query call inside a ``for`` loop (§11.1). **Advisory** -- logs at WARNING,
       does not fail; no escalation mechanism exists.
   * - ``_checker_noqa_rationale``
     - --
     - ``# noqa`` without a written rationale (§*Suppressing a rule*)
   * - ``test_index``
     - --
     - Stored One2many inverse not indexed (§11.5)
   * - ``test_onchange_domains``
     - --
     - Domain returned from an ``@api.onchange`` (§2.9.9)
   * - ``test_naming``
     - --
     - Public method with an ``ids`` or ``context`` parameter (§2.4)
   * - ``test_override_signatures``
     - --
     - Override whose signature diverges from its parent (§2.4)
   * - ``test_orm_import``
     - --
     - Addon runtime code importing ``odoo.orm`` directly (§2.1)
   * - ``test_manifests``
     - --
     - Unknown or misordered ``__manifest__.py`` key (§1.2)
   * - ``test_test_holes``
     - --
     - Test file not imported exactly once in ``tests/__init__.py`` (§6.1)
   * - ``test_docstring``
     - --
     - Docstring fields disagreeing with the signature (§2.5)
   * - ``test_routes``
     - --
     - Inherited route restating an unchanged attribute (§2.8)
   * - ``test_l10n``
     - --
     - Mis-tagged localisation test (§6.7)
   * - ``test_xml_records``
     - --
     - ``<field>`` child order / element attribute order (§3.1)
   * - ``test_pretty_xml``
     - --
     - XML formatting (§3.1)
   * - ``test_dunderinit``
     - --
     - Module without an ``__init__.py``
   * - ``test_markers``
     - --
     - Version-control conflict markers left in a file
   * - ``test_pofile``
     - --
     - Duplicate entries in a ``.pot`` file (§8.3)
   * - ``test_i18n`` / ``test_jstranslate``
     - --
     - Untranslatable static strings in templates and JS (§8.2)
   * - ``test_eslint``
     - --
     - ESLint over JS (skipped when ``eslint`` is absent)
   * - ``test_pep649``
     - --
     - Annotations that fail to resolve under PEP 649

Suppressing a rule
------------------

Every suppression states why ``[test_lint]``:

.. code-block:: python

   value = compute()  # noqa: RUF015 — ordering is guaranteed by the caller

Bare ``# noqa``, or ``# noqa: CODE`` with nothing after it, is itself a
violation; the rationale needs at least four non-space characters including a
letter. For the ``E85xx`` checkers, ``# noqa: E8501`` and
``# pylint: disable=sql-injection`` are both recognised. Broader escapes --
``ruff.toml`` ``per-file-ignores``, the allow-lists in ``test_index.py`` and
``test_override_signatures.py`` -- are config changes needing review on their own
merits.

Quick Reference
===============

**Python**

* Double quotes, line length 88; match ``ruff format``'s output in what you
  write, never reformat a whole inherited file (§2.1).
* One model per file, named after ``_name`` (§1.3) ``[review]``.
* Reach the ORM through ``odoo.api`` / ``odoo.fields`` / ``odoo.models``, never
  ``odoo.orm`` from addon runtime code (§2.1) ``[test_lint]``.
* Every model declares ``_name`` and ``_description`` (§2.6) ``[review]``.
* Override ``create`` as ``@api.model_create_multi def create(self, vals_list)``;
  always ``super()`` in ``create`` / ``write`` / ``unlink`` / ``copy_data`` /
  ``default_get`` (§2.6) ``[review]``.
* Deletion constraints use ``@api.ondelete``; ``raise`` inside an ``unlink``
  override is a violation (§2.6) ``[test_lint E8506]``.
* Name new buttons ``action_*``; never rename an inherited core method (§2.4).
* One verb per operation: ``_prepare_`` builds payloads, ``_get_`` reads,
  ``_check_`` raises, ``_is_``/``_has_``/``_can_`` return booleans, ``_update_``
  writes, ``_add_``/``_remove_`` for collections. ``_build_``, ``_fetch_``,
  ``_validate_``, ``_verify_``, ``_ensure_``, ``_do_``, ``_run_``, ``_perform_``
  are abolished (§2.4) ``[review]``.
* ``odoo.fields.Command`` for x2many writes, never raw tuples (§2.9.7)
  ``[review]``.
* Never compare money or floats with ``==`` / ``!=`` / ``<`` / ``>`` -- use
  ``float_compare`` / ``float_is_zero`` (§2.9.12). Only ``==`` / ``!=`` is linted
  ``[ruff RUF069]``.
* User-facing text goes through ``self.env._(...)`` with ``%s`` arguments (§8.1)
  ``[test_lint E8502]``.
* ``raise X from Y`` inside ``except`` (§2.7) ``[ruff B904]``.
* No ``cr.commit()`` in business code (§2.6).
* ``datetime.now(UTC)``; ``datetime.utcnow()`` is banned (§2.9.6)
  ``[ruff DTZ003]``.

**Performance**

* ``search_count()`` not ``len(search())``; ``_read_group()`` not a Python
  ``sum()`` (§11.2) ``[review]``.
* ``fields.Count("line_ids")`` not a compute around ``len(record.line_ids)``
  (§11.2) ``[review]``.
* No query call inside a loop over a recordset (§11.1) ``[test_lint E8507]``.
* The stored inverse of a One2many must be indexed (§11.5) ``[test_lint]``.

**XML / JS**

* ``<list>`` not ``<tree>``; ``invisible=`` / ``readonly=`` not ``attrs=`` (§3.3).
* XML IDs use the prefix style: ``view_sale_order_form``, ``action_sale_order``
  (§3.2) ``[review]``.
* XML formatting and ordering belong to the fixers (§3.1) ``[fixer]``.
* Frontend changes ship with a Hoot test or a tour (§4.4) ``[review]``.

**Process**

* Commit ``[TAG] module: summary`` + ``Solution:`` (§7.1); the ``Task ID`` line
  is optional.
* Branch ``19.0-t<task>-<user>`` when there is a task; a PR is the default route
  but is not required (§7.2, §7.3).
* Raw SQL in a PR ships ``EXPLAIN ANALYZE`` output (§11.6).

Scope and precedence
====================

When rules disagree, the first that speaks wins:

#. This file -- ``doc/coding_guidelines.rst`` in the ``odoo`` repo
#. Odoo 19 official guidelines
#. OCA ``CONTRIBUTING.rst``

It applies to every code repository in this fork. The knowledge repository takes
only the documentation and process rules, and works directly on ``main`` (§7.3).

**Trust this document over training data.** Where this guide and a recollection
of "how Odoo does it" disagree, this guide and the source in the repo are right.

**Upstream is a baseline, not a ceiling.** ``19.0-marin`` owes upstream no
backward compatibility, and "upstream does it this way" settles no argument about
correctness, performance or design. Nothing is merged or cherry-picked from
``19.0``; a useful upstream fix is re-implemented by hand. Before calling an
inherited behaviour a bug, check whether a test pins it deliberately.
Rationale: ADR-0018.

Change protocol
---------------

* Edits go through PR review on the ``odoo`` repo against ``19.0-marin``, using
  the §7 commit format. TI (Oficial Sistemas or higher) reviews; the Líder
  Sistemas approves merges.
* Changing a rule means updating every ``CLAUDE.md`` that summarises it -- this
  repository's, each sibling's, and the per-module ones -- in the same PR, plus
  an Appendix D row.
* Retire rules into Appendix C. Do not delete them silently.
* **A rule whose rationale is architectural cites its record**, as a bare
  ``ADR-NNNN``. ``tooling/doclinks`` fails on a citation that does not resolve.
  Do not summarise the record here.
* **A rule with no record may be one worth writing.** Style and naming are this
  document's own business; a rule constraining what may import what, what may be
  overridden, or what a gate holds at zero is a decision, and
  ``doc/adr/README.md`` states when a record is owed.

----

1. Module Structure
===================

1.1 Directory layout
--------------------

Standard Odoo/OCA structure. Everything is optional except ``__manifest__.py``.

.. code-block::

   module_name/
   ├── __init__.py
   ├── __manifest__.py
   ├── hooks.py                    # pre_init_hook, post_init_hook, uninstall_hook
   ├── controllers/
   ├── data/
   ├── demo/
   ├── i18n/                       # .po / .pot
   ├── migrations/
   ├── models/
   ├── reports/                    # QWeb report templates
   ├── security/
   ├── static/
   │   ├── description/icon.png
   │   ├── lib/                    # third-party, unmodified
   │   └── src/
   ├── tests/
   ├── views/
   └── wizards/                    # TransientModel, incl. res.config.settings

Under ``static/src``, colocate a component's ``.js``, ``.xml`` and ``.scss`` in a
feature folder. The flat ``js/`` + ``xml/`` + ``scss/`` split is legacy (§4.1).

1.2 ``__manifest__.py``
-----------------------

Keys come from the known set, in the canonical order
``[test_lint test_manifests]``; the fixer owns it ``[fixer _sort_manifests]``:

``name``, ``version``, ``category``, ``sequence``, ``summary``, ``description``,
``author``, ``contributors``, ``website``, ``icon``, ``images``, ``license``,
``depends``, ``external_dependencies``, ``countries``, ``data``, ``demo``,
``assets``, ``installable``, ``application``, ``auto_install``, ``post_load``,
``pre_init_hook``, ``post_init_hook``, ``uninstall_hook``.

.. code-block:: python

   {
       "name": "Module Name",
       "version": "19.0.1.0.0",
       "category": "Sales",
       "author": "AgroMarin",
       "license": "LGPL-3",
       "depends": ["sale"],
       "data": [
           "security/ir.model.access.csv",
           "views/sale_order_views.xml",
       ],
   }

* **Version**: ``{odoo_version}.x.y.z`` -- *x* breaking, *y* feature, *z* fix.
* **Omit empty keys.**
* **``depends`` lists direct dependencies only**, never transitive ones.
* **``auto_install``** only for a genuine bridge module between two independent
  modules, as ``sale_crm`` bridges ``sale`` and ``crm``.
* **Demo data belongs in ``demo``**, not ``data``.
* **``license``** must match how the module is actually distributed. The fork
  ships ``LGPL-3``, ``OPL-1``, ``AGPL-3`` and ``OEEL-1``; do not copy a
  neighbour's value unchecked.

**External dependencies** go in the manifest *and* in the requirements file of
the repo owning the module -- ``requirements-addons.txt`` here,
``requirements.txt`` in the sibling addon repositories, never
``odoo/requirements.txt``, which carries only what the framework and
always-loaded addons import.

.. code-block:: python

   "external_dependencies": {"python": ["requests"], "bin": ["wkhtmltopdf"]},

* Use the **PyPI distribution name**, not the import name (``python-ldap``, not
  ``ldap``): ``check_python_external_dependency`` resolves it through
  ``importlib.metadata.version`` and falls back to importing the name only after
  logging a warning.
* **Declare only what the module cannot start without.** A dependency behind a
  ``find_spec`` guard, a function-local import or ``try/except ImportError`` is
  optional by construction, and declaring it converts a degrading feature into a
  refused install. ``base_import`` declares ``chardet`` and deliberately not
  ``xlrd``, ``odfpy`` or ``openpyxl``.
* **An ``auto_install`` module cannot rely on the declaration.**
  ``odoo/modules/db.py`` marks the auto-install closure in raw SQL and never
  consults ``external_dependencies``, which is checked on the UI install path
  only -- pin the dependency as a server requirement instead. ``cbor2``
  (``auth_passkey``) and ``ofxparse`` (``account_bank_statement_import_ofx``) are
  the two such cases.

1.3 File naming
---------------

**One model per file** ``[review]``. A ``.py`` under ``models/`` (or
``wizards/``) declares exactly one model class -- one ``models.Model``,
``models.AbstractModel`` or ``models.TransientModel`` -- named after that model's
``_name`` with dots as underscores. A second model class is a second file,
whatever its size; ``models/__init__.py`` imports them in dependency order. The
rule holds for extensions: fields added to ``sale.order`` under ``_inherit`` go in
the module's own ``models/sale_order.py``.

Adoption is partial. Apply the rule to files you create or substantially rework.

.. list-table::
   :header-rows: 1

   * - Type
     - Pattern
     - Example
   * - Model
     - ``models/{model_name}.py``
     - ``sale_order.py`` for ``sale.order``
   * - Mixin
     - ``models/{model_name}.py``
     - ``mixin_mail_activity.py`` for ``mixin.mail.activity`` (§2.2.1)
   * - Views
     - ``views/{model_name}_views.xml``
     - ``sale_order_views.xml``
   * - Data
     - ``data/{model_name}_data.xml``
     - ``sale_order_data.xml``
   * - Menus
     - ``views/ir_ui_menu_views.xml``
     - one file, every menuitem
   * - Access rights
     - ``security/ir.model.access.csv``
     - always CSV
   * - Groups
     - ``security/res_groups.xml``
     -
   * - Record rules
     - ``security/ir_rule.xml``
     - every ``ir.rule`` in one file
   * - Wizards
     - ``wizards/{model_name}.py`` + ``_views.xml``
     - includes ``res.config.settings``

1.4 Machine docs (``machine_doc_v*/``)
--------------------------------------

A module may carry a ``machine_doc_v<N>/`` directory: the machine-readable map of
its routes, models, architecture, conventions and test tags. ``CLAUDE.md`` makes
it the first thing read before touching the module, so its figures are adopted as
premises. **A wrong number here is worse than no number.** Rationale: ADR-0043.

**Every figure is gated or frozen. A bare figure is a defect** ``[review]``.

* **Gated** -- derived by the module's ``factcheck.sh`` and asserted with
  ``assert_doc_cites``. A population count is never a literal in the script:
  ``assert_eq "$(measure)" "31"`` makes the script a second copy of the tree.
  Default for anything cheap to re-derive.
* **Frozen** -- pinned to a named base commit, for readings that cannot be
  re-derived (an ad-hoc scanner, a profile, a benchmark). The document states the
  base. **Do not "correct" a frozen figure to a current value**; the surrounding
  argument rests on that base.

Gating governs *measurements*, not *invariants*.
``assert_eq "$(grep -c 'export class Foo' …)" "1"`` is correct -- the literal is
the claim, and it should fail the day the symbol is renamed. Test: would the
number change under ordinary growth? Pin the invariant, not its incidental shape:
``export class Foo extends Bar`` breaks on an inserted intermediate class while
every claim about ``Foo`` stays true.

* **Pin every restatement, not just the first.** Prefer not restating it at all.
* **Prefer omitting an incidental figure to gating it.** A number that shapes no
  decision costs context and rots.
* **A harness derives its roots from ``BASH_SOURCE``**, never a literal path.
* **A backticked path asserts that the file exists** -- ``factcheck.sh`` resolves
  every one, including inside a backticked command. Name a deliberately-absent
  file in plain prose.

CI: ``machine_doc.yml`` runs every discovered ``factcheck.sh``, blocking.
Known-red harnesses sit in its ``QUARANTINE`` with a written reason and are
checked both ways. Fork-wide assertions SKIP with a count in CI, which checks out
this repo alone.

----

2. Python
=========

2.1 Style and imports
---------------------

* PEP 8, **line length 88** -- what ``ruff format`` produces.
* **Double quotes** everywhere: strings, field attributes, docstrings.
* Import order: stdlib, third-party, ``odoo``, ``odoo.addons``, alphabetical
  within each group ``[ruff I]``.

.. code-block:: python

   import logging

   from odoo import api, fields, models
   from odoo.exceptions import UserError, ValidationError
   from odoo.fields import Domain
   from odoo.tools import LazyTranslate

   from odoo.addons.sale.models.sale_order import SaleOrder

**Reach the ORM through the public façade** ``[test_lint test_orm_import]``.
Addon runtime code imports from ``odoo.api``, ``odoo.fields``, ``odoo.models``,
never from ``odoo.orm``, whose internals the fork restructures freely. Test files
are exempt by location. ADR-0008 argues the boundary; ADR-0009 records how its
scope was closed.

**Format what you write, not the file around it** ``[review]``. Every repo's
``.pre-commit-config.yaml`` runs ``ruff-format`` after ``ruff-check --fix``, and
those config files are the authority on the hook set; this repository has no CI
gate for formatting, so the hook reaches only contributors who installed it.
Formatting is whole-file, and reformatting a file you did not otherwise change
costs twice:

* ``# noqa`` is anchored to a **line**. Reflowing moves the diagnostic off the
  directive: the suppressed finding goes live and the orphaned directive is
  reported as ``RUF100``. Lint, format, then lint again.
* Wrapping spends lines, and ``py_function_length.py`` ratchets excess over the
  limit ``[ratchet pyfunclen]``, so a pure reformat can turn that gate red.

Reformatting a whole file is its own commit, justified, with lint and length
ratchets re-checked.

2.2 Model class organisation
----------------------------

.. code-block:: python

   class SaleOrder(models.Model):
       _name = "sale.order"
       _description = "Sales Order"
       _inherit = ["mixin.mail.thread", "mixin.mail.activity"]
       _order = "date_order desc, id desc"

Code is grouped under ``# UPPERCASE`` section banners, in this order ``[review]``:

.. list-table::
   :header-rows: 1
   :widths: 6 30 64

   * - #
     - Section
     - Contains
   * - 1
     - ``# FIELDS``
     - field declarations
   * - 2
     - ``# INDEXES``
     - ``models.Index()``
   * - 3
     - ``# CONSTRAINTS``
     - ``models.Constraint()``
   * - 4
     - ``# CONSTRAINT METHODS``
     - ``_check_*`` (and legacy ``_validate_*``, abolished by §2.4)
   * - 5
     - ``# CRUD METHODS``
     - ``create``, ``write``, ``unlink``, ``copy_data``, ``default_get``
   * - 6
     - ``# COMPUTE METHODS``
     - ``_compute_*``
   * - 7
     - ``# SEARCH METHODS``
     - ``_search_*``
   * - 8
     - ``# INVERSE METHODS``
     - ``_inverse_*``
   * - 9
     - ``# ONCHANGE METHODS``
     - ``_onchange_*``
   * - 10
     - ``# ACTION METHODS``
     - ``action_*``
   * - 11
     - ``# MAIL METHODS``
     - ``_message_*``, ``_notify_*``, ``_track_*``
   * - 12
     - ``# <DOMAIN> METHODS``
     - e.g. ``# INVOICING METHODS``
   * - 13
     - ``# HELPER METHODS``
     - ``_prepare_*``, ``_get_*``
   * - 14
     - ``# HOOKS``
     - ``_auto_init``, ``init``, pre/post hooks

Omit sections you do not need. The section *names* are fixed; a surrounding rule
of dashes is cosmetic -- be consistent within a file. Adoption is partial; apply
the layout to files you create or substantially rework. Within
``# COMPUTE METHODS`` and ``# ONCHANGE METHODS``, define a method before the ones
consuming its output. No tool checks ordering.

2.2.1 Mixin naming
~~~~~~~~~~~~~~~~~~

**A mixin's ``_name`` begins with ``mixin.``** ``[review]``, a **prefix**; the
rest of the name keeps the order it had. A mixin is a ``models.AbstractModel``
meant to be inherited *into* other models. Class name and file name follow from
``_name`` by §1.3 and §2.2:

.. code-block:: python

   # models/mixin_mail_activity.py
   class MixinMailActivity(models.AbstractModel):
       _name = "mixin.mail.activity"
       _description = "Activity Mixin"

**What is not a mixin**, and keeps its own name: an abstract model nothing
inherits from. QWeb report models (``report.{module}.{report_name}``) and
abstract service models are ``AbstractModel`` for want of a table.

**Renaming one is a code change, not a data migration.** A mixin has no table;
the stored trace is its ``ir.model`` row (``abstract = True``) and any
``ir.model.data``, both rewritten by the module update. The rename must reach
``_name``, ``_description``, every ``_inherit`` list naming it, the file name, and
every literal model string in XML, CSV or Python -- ``self.env["…"]``,
``<field name="model">``, an ``ir.model.access.csv`` row. The auto-generated
``ir.model`` XML id is ``model_`` plus ``_name`` with dots as underscores, so
every ``ref()`` of it moves with the model. Renaming an inherited *method* to fit
§2.4 remains forbidden (Appendix C); renaming the model is not.

2.3 Field conventions
---------------------

**Group fields semantically, not by type** ``[review]``, each group under a
``# <Noun> block`` comment. Expected on models with roughly ten or more fields.

.. code-block:: python

   class SaleOrder(models.Model):
       # Financial block
       company_id = fields.Many2one("res.company")
       currency_id = fields.Many2one("res.currency")
       payment_term_id = fields.Many2one("account.payment.term")

       # Partner block
       partner_id = fields.Many2one("res.partner")

       # Core identification
       name = fields.Char()
       state = fields.Selection([...])

       # Order line block
       line_ids = fields.One2many("sale.order.line", "order_id")
       amount_total = fields.Monetary(compute="_compute_amounts")

       # UI block
       is_locked = fields.Boolean()

Blocks are per-model -- ``# GPS block`` and ``# Harvest block`` are as legitimate
as ``# Financial block``. Relational fields mix freely inside a block. Line models
open with the ``related=`` fields inherited from their parent, ``order_id`` first.

.. list-table::
   :header-rows: 1

   * - Kind
     - Convention
     - Example
   * - Many2one
     - ``_id`` suffix
     - ``partner_id``
   * - One2many / Many2many
     - ``_ids`` suffix
     - ``line_ids``
   * - Dates
     - ``date_`` prefix
     - ``date_validity``
   * - Amounts
     - ``amount_`` prefix
     - ``amount_total``
   * - Counters
     - ``count_`` prefix
     - ``count_picking``
   * - Quantities
     - ``qty_`` prefix
     - ``qty_transferred`` (core also uses ``product_qty`` / ``qty_done``)
   * - Booleans
     - ``is_`` prefix
     - ``is_sent``
   * - State
     - ``_state`` suffix
     - ``invoice_state``

Defaults that must remain overridable use ``lambda self:``:

.. code-block:: python

   user_id = fields.Many2one("res.users", default=lambda self: self.env.user)

2.4 Method naming
-----------------

.. list-table::
   :header-rows: 1

   * - Kind
     - Convention
     - Example
   * - Button actions
     - ``action_`` for **new** methods
     - ``action_confirm``
   * - View openers
     - ``action_view_``
     - ``action_view_invoices`` (``action_open_*`` is valid for wizards)
   * - Compute
     - ``_compute_``
     - ``_compute_amounts``
   * - Prepare values
     - ``_prepare_*_vals``
     - ``_prepare_invoice_vals``
   * - Getters
     - ``_get_``
     - ``_get_candidate``
   * - Onchange
     - ``_onchange_``
     - ``_onchange_partner_id``
   * - Constraints
     - ``_check_``
     - ``_check_date``
   * - Inverse
     - ``_inverse_``
     - ``_inverse_quantity``
   * - Search
     - ``_search_``
     - ``_search_display_name(self, operator, value)``
   * - Mail
     - ``_message_*`` / ``_notify_*`` / ``_track_*``
     - ``_track_subtype``
   * - Default
     - ``_default_``
     - ``_default_warehouse_id``
   * - Domain
     - ``_domain_<field>`` bound; ``_get_domain_<what>`` free-standing
     - ``_domain_child_ids``, ``_get_domain_modules_to_load`` (ADR-0054)
   * - Selection
     - ``_selection_<values>``
     - ``_selection_target_model`` -- named for the values, not the field: one
       method serves fields of several names on unrelated models

2.4.1 Field hooks
~~~~~~~~~~~~~~~~~

**A field hook is named for the field it serves** ``[ratchet fieldhooks]``. One
field: ``_<attr>_<field>``, spelled in full -- ``_default_category_id``, not
``_default_category``. Several fields: named for what they have in common
(``_compute_amounts``), **never for one of them**. Several *triggers* maintaining
**one** field: named for that field.

**A domain is its own family** ``[ratchet fieldhooks]``. A domain feeds
``search()`` and a field's ``domain=``, never ``create()``/``write()``. Bound:
``_domain_<field>``. Free-standing: ``_get_domain_<what>``. ``_search_*`` is
exempt -- a domain is a search hook's contract. ADR-0054, superseding ADR-0050.
**When an ordering or vocabulary rule lands, check it first against the families a
record already fixes** -- the check is the record, not the tree.

**A hook does one job** ``[ratchet hookpurity]``. 24 are not hooks at all: the
declaring model also calls them on ``self`` (calls from tests do not count). Split
it -- the hook keeps the name and delegates to a helper. ADR-0051, ADR-0049.

**A hook's prefix is reserved for hooks** ``[review]``. ``_compute_``,
``_search_``, ``_inverse_``, ``_default_``, ``_onchange_``, ``_domain_`` and
``_selection_`` belong to methods a field declaration points at; a body several
hooks share is named for what it does. Neither field-hook gate sees this, and it
is worst when the field exists -- ``ir_cron``'s ``_compute_next_call``, a
``@staticmethod`` no declaration named on a model carrying a stored ``nextcall``,
is ``_get_next_call``.

**A ``_selection_*`` method with a parameter is not a hook**: ``selection=`` calls
it with nothing to pass. There are **0** left.

**A protocol namespace may open with a hook prefix, and the prefix does not lose**
``[review]``. **The test is whether the continuation names a field** --
``_search_panel_get_domain_image`` would promise a field
``panel_get_domain_image``, which reads as no field name at all.

**The verb goes after a protocol namespace and in front of a provider one**
``[review]``. A provider prefix (``_gc_``, ``_weasy_``) names *what a value comes
from*: verb first. A protocol namespace is the substring an overrider greps for:
verb behind it -- ``_search_panel_get_*``, ``mail``'s ``_message_post``.

Two readings of the gate itself:

* **Its dedication test is per definition, not per name.** A ``default=`` may
  point at any callable, so the gate reaches one only when the method is
  *dedicated* to the field; counted against raw occurrences, a hook copy-pasted
  into eighteen classes would exempt itself. *Frozen reading* (§1.4) at
  ``24880109a03``, before the repair: **25 hooks, 15 of them that one name** were
  hidden. Do not update those two digits. **1** hook is exempt today,
  ``crm.team._get_default_team_id``.
* **The reserved prefixes are worn by more than the hooks**
  ``[gate doc_restated_counts]``. ``field_hook_naming.py --unbound``: **153**
  names, at **237** definitions, wear one while no field declaration and no
  binding decorator names them (``_compute_`` leads at 72 names, ``_search_`` at
  49). A candidate population, not a violation count.

2.4.2 Decorator-bound families the gate cannot reach
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``field_hook_naming.py``'s ``ATTRS`` stops at five field-declaration keywords by
construction. A decorator binds the other way round -- the fields are arguments to
the decorator and no field declaration mentions the method -- so four families are
measured by nothing.

**``@api.onchange``** ``[review]``: a hook bound to one field is
``_onchange_<field>``. **271** of **383** single-field onchange hooks are spelled
for their field. Four of the rest carry the **pre-9.0 public spelling**
(``on_change_login``, ``onchange_parent_id``), reachable over RPC by accident.

**``@api.depends``'s callable form** ``[review]``.
``@api.depends(lambda self: self._get_fields_warning_depends())`` hides the name
twice, on a decorator and inside a lambda. Such a method returns field names:
``_get_fields_<field>_depends``. A lambda in an attribute the gate *does* read
(``domain=lambda self: …``) is itself the hook, so the method takes the
free-standing form.

**``@api.ondelete``** ``[review]`` binds to no field and its first token is the
*reserved* ``unlink``, so three checkers have no opinion, over **165** methods.

* ``unlink`` is the right verb: ``_remove_*`` names a business method that deletes
  records, while an ``@api.ondelete`` hook deletes nothing -- it *guards* the ORM
  operation named ``unlink``. Do not "correct" one to ``_remove_``.
* **The canonical is ``_unlink_except_<the case that raises>``**, at **107** of
  the 163 already. Name the case that raises and take the wording from the error:
  ``_unlink_except_master_data`` raises **when** the record is master data, while
  ``_unlink_if_manual`` states the opposite condition.
* ``_unlink_`` is also right for a method that performs the deletion:
  ``_except_`` is a guard and returns, anything else under ``_unlink_`` deletes.
  An ORM-invoked hook is private.

**``@api.constrains``** ``[review]`` is the fourth and largest, at **581** hooks.
The Validation row governs the spelling and **502** already carry ``_check_``. The
rest are names the ratchet counts (``_validate_``, ``_ensure_``, ``_verify_``) and
the localisation namespace with the verb behind it
(``_l10n_se_check_payment_reference``). That leaves **47** spelled with a first
token carrying no rule anywhere: ``_constrains_``, ``_constraint_``,
``_limit_available_currency_ids``, and twice the misspelling ``_contrains_``.

**The field-hook rule must not be extended to it** ``[review]``. **297** bind
exactly one field and only **124** are ``_check_<field>`` -- that gap is the rule
working. A ``compute=`` names a subject; a ``@api.constrains`` argument names a
**trigger**, and a constraint is named for the **condition it enforces**
(``_check_at_least_one_administrator``). **37** multi-field constraints are named
for exactly one of their triggers and every one is right. Ask what **raises**.

**A hook may hold two bindings, and then one prefix has to lose** ``[review]``.
Do not read a prefix as a claim that no other binding exists.

2.4.3 The verb vocabulary
~~~~~~~~~~~~~~~~~~~~~~~~~

**One verb per operation** ``[review]``. The table in §2.4 governs prefixes
carrying an ORM role; every other method opens with a free verb. The abolished
spellings are wrong, not lesser-preferred. The tree spells single operations many
ways: 8 stems are written with two or more verbs drawn from one semantic family,
and 100 groups of methods share a byte-identical body under different names.

**Every figure in this section is measured, not stated**
``[gate doc_restated_counts]``. The population is the 23,729 non-test methods
declared on a model class **in this repository** -- the population
``naming_vocabulary.py`` ratchets. Semantic families are read off the table
below, so the justification is computed from the rule it justifies. Census and
ratchet both stop at this repository (ADR-0033), so every figure is a floor.

.. list-table::
   :header-rows: 1
   :widths: 12 16 34 38

   * - Family
     - Canonical
     - Abolished
     - Discriminator
   * - Payload
     - ``_prepare_*``
     - ``_build_`` ``_make_`` ``_compose_`` ``_construct_``
     - the return value feeds ``create()`` / ``write()`` / ``Command``
   * - Read
     - ``_get_*``
     - ``_fetch_`` ``_retrieve_`` ``_obtain_`` ``_lookup_``
     - the return value feeds anything else -- see §2.4.7 before reading this as
       "does not build it"
   * - Predicate
     - ``_is_`` ``_has_`` ``_can_``
     - --
     - **the returned ``bool`` is the answer to a question about the subject**;
       never raises, no side effect. The return *type* is not the test
   * - Validation
     - ``_check_*``
     - ``_validate_`` ``_verify_`` ``_ensure_`` ``_control_``
     - **raises** on failure; a boolean answer is a predicate
   * - Mutation
     - ``_update_*``
     - ``_assign_`` ``_fill_`` ``_inject_``
     - writes to records; an ``inverse=`` target is ``_inverse_<field>``
   * - Addition
     - ``_add_*``
     - ``_append_``
     - ``_insert_`` / ``_push_`` are reserved, not abolished
   * - Removal
     - ``_remove_*``
     - ``_delete_`` ``_purge_``
     - ``unlink`` stays reserved for the ORM operation; so do ``_drop_`` /
       ``_discard_``

**Reserved, not abolished** ``[review]``. Each is a term of art from a layer
below the ORM; collapsing it destroys information. Use them **only** with these
meanings -- a business method that deletes records is ``_remove_*``, never
``_drop_*``, and a predicate is never spelled with ``exists``.

.. list-table::
   :header-rows: 1
   :widths: 16 84

   * - Verb
     - Reserved for
   * - ``_drop_``
     - SQL DDL -- ``_drop_table``, ``_drop_column``
   * - ``_insert_``
     - SQL DML and ordered insertion -- ``_insert_cache``, ``insert_rows``
   * - ``_push_``
     - stack or queue semantics -- ``push_protection``
   * - ``_discard_``
     - the ``set.discard`` contract: remove if present, never raise
   * - ``_append_``
     - an ordered sequence whose **position is part of its contract**; abolished
       everywhere else, which is the common case
   * - ``read`` / ``write``
     - a method whose object is a **file** -- the pair names one contract and
       must not split across ``_get_`` and ``_write_``
   * - ``_resolve_``
     - a **partial** producer: returns the object, or ``None`` meaning *not
       applicable* (§2.4.11)
   * - ``_sync_``
     - convergence on a source of truth elsewhere (§2.4.12)
   * - ``flush_``
     - the ORM operation -- ``flush_model``, ``flush_recordset``
   * - ``_evict_``
     - **capacity** eviction: which entries go, not whether what stays is valid
   * - ``exists`` / ``_*_exists``
     - the ORM operation ``recordset.exists()``, and schema introspection --
       ``_table_exists``, ``_column_exists``

**Before claiming ``_append_``, check both halves**: a receiver that is a
sequence, and an addition that lands at its end. ``naming_vocabulary.py`` keeps
``append`` in ``ABOLISHED`` unconditionally, since it reads a name and not a
receiver, so the reservation is ``[review]`` and widens no gate.

**The reservation binds public names too.** ``ir.actions.server``'s
``create_action`` and ``unlink_action`` perform neither operation they name, and
``ir.cron``'s ``method_direct_trigger`` has no verb anywhere; all three are left
as found, since renaming them is owed ADR-0053's weighing and one change across
every repository.

2.4.4 Ordering
~~~~~~~~~~~~~~

**The verb leads** ``[review]``. ``naming_vocabulary.classify`` partitions on the
first token and stops, so a noun in front of the verb hides the verb from the rule
*and* from its enforcement: ``_import_retrieve_customer`` scores as the verb
``import``, which carries no rule. Backlog: **156** model methods put an abolished
verb somewhere the ratchet cannot read it -- a candidate population, since some of
those tokens belong to a noun or a field name.

* A noun-first prefix is legitimate only where it names a **protocol several
  models implement** (``_message_*``, ``_notify_*``, ``_track_*``,
  ``_portal_*``), never as a per-model tidy-up. **The test is not size: ask
  whether the prefix would survive being moved to another model.**
* **A name with no verb at all is the same blind spot with nothing behind it.**
  ``_root_model_names`` scores as the verb ``root``. Repair is mechanical -- verb,
  object, qualifier: ``_get_model_names_in_root_table``.
* **A namespace has to be a namespace in every name that wears it.**
  ``_gc_file_store`` reads *gc the file store* while ``_gc_checklist`` reads *the
  gc checklist*, and is ``_get_gc_checklist``. Before choosing a spelling, look
  for the member that already has one.
* **Layer the namespaces in the order the calls nest.** ``_esm_run_esbuild``
  wrapping ``_esbuild_invoke`` put each prefix on the other's operation; the pair
  is ``_compile_with_esbuild`` and ``_compile_with_esbuild_locked``.

**A public method drops the underscore, not the verb** ``[review]``. The public
form of a getter is ``get_*``, of a payload builder ``prepare_*``, down the table
(ADR-0053). **A public rename is weighed differently**: callers may sit outside
this workspace and an RPC caller leaves no trace in any tree a gate can scan, so
weigh it as a public-surface change, give it the record ``doc/adr/README.md`` asks
for, and rewrite every repository in one change or none. **A rename that cannot be
completed inside the workspace is not begun.**

**The signature can prove the public spelling was an accident** ``[review]``. A
return of recordsets, callables or exceptions -- anything that does not survive
serialisation -- is evidence the missing underscore was an oversight, since the
one call that would make it a public contract raises rather than returns. So is a
**required** parameter no JSON-RPC request can carry: a recordset, a
``fields.Field``, a ``Callable``, an ``Environment``, a cursor. Making such a
method private *removes* a surface, so ADR-0053's weighing does not apply. Where
``model_member_surface_check.py`` pins the name, the pin moves in the same change
or the gate fails both ways.

**The object leads its qualifier** ``[review]``. A name returning a qualified
thing puts the **thing** first: ``_get_fields_readable``, not
``_get_readable_fields``; ``_get_port_effective``, not ``_effective_port``. Not a
rule about collections -- a scalar with an adjective reads the same way.

**Head-first is a test as well as an ordering** ``[review]``. Apply the reordering
and **read the result**:

* meaningless after reordering -- the qualifier was noise, drop it
  (``_get_related_assets`` → ``_get_assets``);
* unchanged in meaning, answering *whose* rather than *which* -- it is a
  namespace, leave it in front. **A leading noun that names a provider is a
  namespace, not a qualifier**: the test is whether the token could follow
  "which". *Which* port -- the effective one, so it moves; *which* font config --
  there is only one, and ``weasy`` says whose;
* reads and distinguishes -- reorder it, the ordinary case. Where the qualifier
  carried a real relation the name never wrote down, write the tail instead of
  deleting it: ``_get_related_bundle`` → ``_get_bundle_containing_path``.

Backlog ``[gate doc_restated_counts]``. The ``fields`` family is converted:
**187** definitions under **93** names in this repository spell it head-first and
**17** spell it the other way. **The rule is general; the conversion reached one
family** -- across **19** of them this repository spells **63** definitions
head-first against **171** the other way. A name in the second count is a backlog
item, not an open question. Two cautions:
``naming_vocabulary._COLLECTION_HEADS`` is a **search**, so a head absent from it
is measured by nothing; and ``ids`` is deliberately absent, because
``_get_partner_ids`` names a **field** and the field-hook rule owns that spelling.

Three checks when renaming ``[review]``:

* **A body that reports what it did in one vocabulary and is named in another is a
  cheap place to look.** ``_esbuild_circuit_record_failure`` logged
  ``circuit_open``; it is ``_open_esbuild_circuit``.
* **A ratcheted figure moving the wrong way is an objection.** That pair was first
  renamed to ``_run_esbuild``, breaking §2.4.9 in the commit that quotes it.
* **A rename is workspace-wide and a name is not unique.** A substitution on a
  short generic name cannot distinguish the owner. Prefer the name that is already
  qualified; where the substitution is unavoidable, run the *other* owner's
  callers first.

2.4.5 Converters
~~~~~~~~~~~~~~~~

**``X_to_Y`` is the converter idiom, and ``to`` is the verb** ``[review]``. **99**
definitions under **52** names are spelled that way and most are right: the name
is the pair of representations, and it buys the searchable families ``_str_to_*``
and ``_*_to_sql``. **``Y_from_X`` is the same idiom spelled backwards**, and
almost every ``_from_`` name is innocent -- the verb leads and *from X* is a source
qualifier. The offender is the shape with **no verb at all**:
``_db_id_from_xmlid`` beside ``_xmlid_to_record_id``, one operation both ways in
one class. Repair by reading the return, not by flipping the arrow.

Four limits:

* **A converter returns the representation its name promises**, so a strict-shape
  name annotated ``-> None`` is not one -- 8 of the 99 are, and not all are
  defects (``mail``'s ``_thread_to_store`` serialises into an accumulator it is
  handed). The reading generalises: excluding hook prefixes, 7 model methods open
  with ``_get_``, ``_prepare_``, ``_count_``, ``_resolve_``, ``_find_``,
  ``_list_`` or ``_collect_`` and are annotated ``-> None``.
* **The idiom holds only while the conversion is total in one operand.** An
  operand that steers the result leaves no pair to name: ``_paperformat_to_css``,
  taking a landscape flag and template overrides, is ``_prepare_paperformat_css``.
* **Two representations of one value, not a value and the container it came
  from.** ``_mimetype_from_values(values)`` is fully determined by its argument and
  is still not a conversion -- the mimetype is guessed by a fallback chain. It is
  ``_get_mimetype_from_values``.
* **The receiver can supply the left operand.** A leading ``_to_`` is correct
  where the receiver is the source representation:
  ``attachment._to_http_stream()``.

2.4.6 Tails and operands
~~~~~~~~~~~~~~~~~~~~~~~~

* **In an addition, the tail names what is added, not the medium** ``[review]``.
  ``_add_header_footer_html`` ended in what it adds them *to*; it is
  ``_add_html_header_footer``. The signature settles it -- what a method adds is
  in its parameters, what it adds to is what it returns.
* **A verb that acts rather than returns still owes a noun** ``[review]``, naming
  what it acts on. An adjective is not a thing acted on (``_warn_stranded`` →
  ``_warn_stranded_sources``) and an adverb is less of one (``_reschedule_later``
  → ``_reschedule_job_later``): an adverb belongs in the tail, never in the
  object's place.
* **A preposition at the end of a name is an operand the author meant to write**
  ``[review]``. ``_get_stream_from(record, ...)`` reads as finished because the
  argument supplies the noun at every call site, while a search, an override list
  and a stack trace all show the name alone. **Repair it by writing the operand,
  not by deleting the preposition** -- the preposition carries the axis the family
  varies on, so ``_get_stream_from_record`` and ``_get_stream_placeholder`` leave
  ``_get_stream_`` finding every producer and nothing else.
* **Where two neighbours return different representations, the tail says which**
  ``[review]``: ``_get_stream_placeholder`` returns a ``Stream``,
  ``_get_placeholder_bytes`` returns bytes from the same default path.
* **A predicate is named for the question, in the tense the caller asks it**
  ``[review]``. ``_is_tls_verified`` reads as settled state where the caller is
  asking a prospective question.

2.4.7 Payload against read
~~~~~~~~~~~~~~~~~~~~~~~~~~

**``_get_`` is not a default.** At 5,212 definitions it is 22.0 % of every method
in this repository's model layer, having absorbed reading, building, deriving and
computing. The split that matters is against ``_prepare_``: 677 definitions are
payload builders -- they end in ``_vals``, ``_values``, ``_data``, ``_dict``,
``_context``, ``_defaults``, ``_list``, ``_args`` or ``_params`` -- yet are
spelled ``get_*``, against 686 already spelled ``_prepare_*``.

**Resolve it on the consumer, always** ``[review]``. Where the return value goes
is visible at the call site; whether a value was "already there" is a question
about the method's insides that two readers answer differently.

* feeds ``create()`` / ``write()`` / ``Command`` → ``_prepare_*``, whatever its
  provenance;
* feeds a **named non-ORM consumer** → ``_prepare_*`` too, naming the consumer
  rather than the shape: ``_prepare_eval_context``, not ``_prepare_eval_vals``;
* returns to a caller that merely reads it → ``_get_*``.

The test is the **mapping handed to** ``create()`` / ``write()`` / ``Command``,
not any value a caller happens to store. *Provisional in one direction only*: the
first bullet is settled, but moving the ``safe_eval`` / ``SQL`` /
rendering-context family onto ``_prepare_`` is not, because several of those names
are fixed by a binding (§2.4.14) -- ``_get_report_values`` is the clearest. Name
new ones this way; do not rename the bound ones.

* **Provenance is the tiebreak, and it separates artifacts from arithmetic**
  ``[review]``. An SVG or a block of bytes is an artifact, built to be handed
  over; a scalar that is the *answer to a question* is a read whatever arithmetic
  produced it. A question is ``_get_``, a thing is ``_prepare_``.
* **The payload suffixes are a search, not a verdict** ``[review]``. Most of what
  they find in ``base`` is correctly ``_get_`` -- ``_get_action_dict`` returns
  ``read()``'s output. Run the consumer test on every hit.
* **That it read acceptably is not a defence, and it is the objection to expect**
  ``[review]``. ``Report.barcode("QR", value)`` parses as English because
  ``barcode`` is a noun a reader silently verbs; it is ``prepare_barcode``.
* **A shape suffix on an extension point is a claim every override has to keep**
  ``[review]``. ``_get_installed_addons_list`` returned a ``frozenset`` while its
  override point returned a ``list``; head-first drops the suffix in one move,
  ``_get_addons_installed``.
* **A payload builder is often named for the operation it feeds, and that verb
  belongs to its caller** ``[review]``. ``_reflect_model_params`` returns the
  ``ir_model`` column values ``_reflect_models`` consumes: it is
  ``_prepare_model_vals``. **Ask whether the name already belongs to a method one
  frame up.** Converse halves of one mechanism wearing two unrelated verbs is the
  same defect as a duplicate: the spelling that hides a duplicate hides a
  counterpart.
* **A canonical verb can be wrong too** ``[review]``.
  ``_prepare_local_attachments`` migrated remote attachments and returned the
  local ones -- a write, then a filter, with no consumer anywhere. It is
  ``_migrate_attachments_to_local``.

**``_generate_`` is the largest member of the payload family and is not in the
table** ``[review]``. The four verbs the Payload row abolishes come to **12**
definitions between them; ``_generate_`` alone is **131**. It carries two meanings
-- ``_generate_access_token`` builds a value and takes the payload canonical,
while ``_generate_consume_moves`` **creates records** and takes the domain
operation's name -- so wiring it into ``ABOLISHED`` would widen a blocking gate by
more than half its floor, and is owed its own record.

**The assemble verbs are abolished on paper and enforced for one shape**
``[review]``: ``naming_vocabulary.py`` reports one only when the name also ends in
a payload suffix. **12** model methods open with one of those four verbs and the
ratchet flags **4**. Two things hide in that gap -- the suffix list is short
(``_build_pdf_options`` is invisible because ``_options`` is not one of the nine),
and *object construction takes ``_prepare_`` too*, since a factory has a consumer
like anything else.

Backlog: **32** of this repository's **686** ``_prepare_*`` definitions call
``create()``, ``write()`` or ``unlink()`` in their own body. A candidate
population -- only a builder whose **return value** is not the mapping it
assembles is in the wrong family.

2.4.8 Predicates and validation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**A ``bool`` return does not make a predicate** ``[review]``. **339** functions in
this repository are annotated ``-> bool`` and are not predicates, against **174**
that are: ``write`` and ``unlink`` return ``True`` by ORM convention, and
``_coerce_bool(value, default)`` is a converter. Ask what the boolean *is* -- an
**answer** to a question about the subject is a predicate, a **converted value**
keeps its conversion verb, a **conventional acknowledgement** is nothing at all.
The call site is the tell: a predicate reads naturally inside an ``if``, a
converter where a type would.

**Validation raises; predicates return.** ``_check_*`` (953 definitions) is
canonical and matches ``@api.constrains``. ``_validate_`` (37) plus ``_verify_``,
``_ensure_`` and ``_control_`` (53 together) are the same operation under four
names. A method that *answers* rather than enforces is ``_is_*`` / ``_has_*`` /
``_can_*`` and must not raise.

* **A predicate prefix is a contract, and a raising body breaks it** ``[review]``,
  with nothing enforcing that direction. ``_can_execute_action_on_records``
  returned ``None`` and raised ``AccessError``, so ``if not action._can_…():
  return`` guarded exactly when access was **granted**. It is
  ``_check_access_to_run``.
* **A predicate may log, and the log's wording is not a side effect**
  ``[review]``. **The tell that reporting has become the contract is a parameter
  only the log reads.**
* **A ``_check_`` bound to ``@api.constrains`` that never raises cannot be
  repaired by renaming** ``[review]``. Either it is a constraint and owes a
  ``ValidationError``, or it is advisory and owes a ``_warn_*`` helper called from
  ``create`` and ``write`` -- a behavioural call. **Read every
  ``@api.constrains`` hook you meet for a ``raise``.**
* **The three predicate prefixes are reserved** in the sense the reserved-verb
  table means it.
* **Unbound, the same prefix hides a different family altogether.**
  ``_check_contents(values) -> values`` returned the dict ``create`` hands to
  ``super()``; it is ``_prepare_contents``. The wrong prefix costs placement too,
  since §2.2's table is keyed on it. A ``_check_*`` that is not an
  ``@api.constrains`` hook belongs beside the operation it guards.

**``_should_`` is a fourth predicate prefix, and the row does not list it**
``[review]``. *Frozen reading* (§1.4) at ``216b5a03021``: ``_is_`` **363**,
``_has_`` **70**, ``_can_`` **69**, against ``_should_`` **58**, ``_must_`` **8**,
``_needs_`` **6** and ``_requires_`` **1**. The canonical is the three: ask the
question in the tense the caller asks it and put the modality in the tail
(``_should_stream_upload`` → ``_is_stream_upload_required``). It is not in
``ABOLISHED`` because every entry there prints **one** canonical target and this
family has three. Owed its own record.

**The abolished table maps spellings, not methods** ``[review]``. A row says what
an operation of that family is called; it does **not** say a method wearing that
verb belongs to the family. ``_verifies_tls`` reads down to ``_check_tls`` and is
a predicate: ``_is_tls_verification_required``. **The ratchet's suggested target
is a hypothesis, not a verdict.** Where the body disagrees, the body wins.

2.4.9 Execution verbs
~~~~~~~~~~~~~~~~~~~~~

**Do not name a method for the act of running** -- *provisional*. ``_do_``,
``_run_``, ``_perform_``, ``_execute_``, ``_process_`` and ``_handle_`` (186
definitions) describe execution rather than behaviour; every method executes. Name
the domain operation: ``_post_entries``, not ``_do_posting``. No mechanical
rewrite exists.

* **A callback is a role, not an operation** ``[review]``.
  ``_callback(cron_name, server_action_id)`` names the fact that something calls
  it back, which every method in a dispatch chain does. It is
  ``_run_server_action``.
* **Where the operation is what the model is about, the verb is a domain verb.**
  ``ir.cron`` exists to run scheduled jobs; ``_eval_`` is what ``safe_eval`` does;
  rendering is a reporting engine's domain operation. The test: could the name be
  replaced by a more specific domain operation? For ``_do_posting`` it could; for
  *run this job* there is nothing more specific to say. Keep one verb and let the
  object separate the scopes -- ``_run_jobs_until_deadline``, ``_run_job``,
  ``_run_job_within_budget`` -- so the grep for the descent is ``_run_``.
* **A count of spellings is not a count of violations, and this rule raises it**
  ``[review]``. Moving a chain onto one verb **adds** a definition to the census.
  Those six verbs are a *sample*: a verb naming *the walk* is the same defect
  under a word nobody listed (``_traverse_path`` → ``_get_update_path_target``).
  Do not read the number as debt to drive to zero, and do not avoid a correct
  ``_run_`` to keep it still.
* **The tuple return is the tell.** A method returning two products either names
  both or splits, and the **call sites** say which: same consumer → name both
  (``_prepare_body_and_stylesheets``); different consumers → split. **"Unused
  here" is not "unused"** -- grep the workspace, not the file.

2.4.10 Errors and stand-in names
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**An error is built here and raised there** ``[review]``. A method that builds an
exception is ``_prepare_*_error`` and **returns** it; the ``raise`` is written
where control leaves. ``_raise_*`` is abolished for such a method, on three
grounds in ascending weight:

* it names control flow, which §2.4.9 already objects to;
* it **hides** control flow: ``raise self._prepare_x_error()`` is visible where it
  happens, while ``self._raise_x_error()`` looks like every other call and the
  lines after it are unreachable in a way a reader has to deduce;
* nothing types it. A function that never returns is ``NoReturn``; **0** of this
  repository's **17** ``_raise_*`` model methods say so, and six claim
  ``-> None``, which is false.

The cost is accepted -- the call site says the verb twice, and ``B904`` fires the
moment the raise moves into the caller's own ``except``.

* **The larger half says no verb at all** ``[review]``: a builder that already
  returns the exception is invisible to both mechanisms when its name is a noun
  phrase. 13 model methods are annotated to return exactly an exception type, of
  which 9 spell ``_prepare_*_error`` -- a floor, since the complete test is a body
  whose every ``return`` is an exception constructor.
* **A method that raises only sometimes is a different family** ``[review]``. The
  rule above reaches the unconditional raiser, **12** of those **17**; the rest
  spell ``_raise_if_*`` or ``_raise_for_*``, have nothing to return when the
  condition does not hold, and are the Validation row: ``_check_*``.

**A name standing in for another contract takes that contract's spelling**
``[review]``. Four shapes of the same rule:

* a **wrapper** reaching a name the framework resolves at runtime takes the
  callee's spelling and gains only the verb: ``_empty_list_help`` →
  ``_get_empty_list_help``, not the head-first ``_get_help_empty_list``, because
  the two sit four lines apart. **The test is the call, not the resemblance**;
* a **memo** takes the spelling of what it memoizes, since memoizing changes
  *when* a body runs and nothing else: a ``dict``-backed memo over
  ``_resolve_path_def`` is ``_resolve_paths``, not ``_get_paths``. **The memo
  follows the body, never the reverse**;
* a **substitute** keeps the promise the default's name made: a callback slot
  whose implementations disagree about whether control returns becomes a slot that
  **returns the error to abort with, or ``None`` to carry on**;
* a **slot** and the method that fills it are one contract under two names. A
  sweep driven by definitions reads ``def``; a slot is a **parameter**. **Read the
  parameter list of every callback-taking constructor in a file you are
  sweeping** -- the slot is the name the call site sees, and it outlives any one
  implementation.

2.4.11 Partial producers and the ``_find_`` family
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**``_find_`` is three operations wearing one verb** ``[review]``. Pure ORM reads
among them have been renamed to ``_get_``. Split by what the body does, the **28**
``_find_*`` methods that remain are still not one thing:

* **6** perform an ORM read -- and both also **write**, which is why they were
  left (``_find_existing_rule_or_create`` searches then creates);
* **22** do something else entirely, and the verb flatters them
  (``_find_available_name`` appends ``(2)``, ``(3)`` until unused: a derivation).

The third kind is gone. **The canonical is ``_get_or_create_*``**: **0** methods
here still spell it ``_find_``, against **18** spelling it ``_get_``. ``_find_``
is not in the abolished table, because classification needs the body: a pass keyed
on the name scored both survivors as pure reads, and a check for ``create`` /
``write`` / ``unlink`` / ``copy`` moved them out.

**Read the caller too, because an extension point's body is the least informative
in the tree** ``[review]``. ``_migrate_remote_to_local`` is
``return self.type == "binary"`` -- the Predicate row exactly -- while its caller
discards the return inside ``except (ValidationError, RequestException)``, so the
contract is *fetch the remote bytes and store them locally*.

**``_resolve_`` is the verb to keep** ``[review]``, at **30** definitions here
against the size of ``_find_`` -- **28**. It is a **partial** producer, returning
the object or ``None`` meaning *not applicable*; a read that always answers is
``_get_``. Where a dispatch chain mixes the spellings, read it as the chain saying
which branches can refuse.

* **The rule is about the contract, not about fetching.** ``_resolve_runner``
  reads a dispatch table and returns ``None`` for a state with no entry, fetching
  nothing.
* **``_resolve_`` is not every optional return.** ``_get_stored_content`` returns
  ``None`` when there are no stored bytes -- there ``None`` is *there is none*.
  **The test is the caller, not the annotation**: ``_resolve_`` earns its verb
  where the ``None`` routes somewhere.
* **Check a reserved verb against the body twice**: once for the contract, once
  for the possibility that it was never a claim about the contract at all.
  ``_resolve_filestore_root`` took its verb from ``Path.resolve()`` and always
  answers; it is ``_get_filestore_root_path``.

**A private method paired with a public one of the same spelling cannot be renamed
alone** ``[review]``. A pair split across two spellings is worse than a pair
uniformly wrong. **Rename the pair or neither**, and where the public half needs
an ADR, the private half waits for it.

**A context manager is named for the scope it opens** ``[review]``. What the
caller receives is a context manager, and the teardown after the ``yield`` is half
the contract, so a name promising a return states the half that is least true.
Name the scope in the imperative -- ``_staged_filestore_temp`` →
``_stage_temp_file``, on the model of ``borrow_request``, ``savepoint``,
``ignore_indexes``. *Frozen reading* (§1.4) at ``216b5a03021``: 21 methods on model
classes carry the decorator and agree on nothing.

2.4.12 Mutation, sync and overloaded verbs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**``_update_``, not ``_set_``** ``[review]``, for a method that writes to records
and is wired to nothing. ``_set_*`` (143 definitions) and ``_update_*`` (245) are
near-evenly split, so this is a backlog rather than a tidy-up. Three carve-outs,
all bindings:

* an ``inverse=`` target is ``_inverse_<field>`` and was never a ``_set_``
  question -- 238 against 2 now that the count is drained;
* ``set_values`` / ``get_values`` on ``res.config.settings`` are *bound by name,
  not by inheritance* (§2.4.14);
* ``set_param`` on ``ir.config_parameter`` is public and reached from JS and XML
  data.

Where ``_set_x`` and ``_update_x`` both exist for one operation, that collision is
the duplicate report this section exists to produce.

**A method that converges is not a method that writes**
``[gate doc_restated_counts]``. Making one table **agree with** another takes a
create where the target is missing, a write where it differs and an unlink where
the source is gone. **The canonical is ``_sync_*``**, and the tree had a family
for it this section had never named: **55** definitions spell it ``_sync_*`` and
**13** spell it ``_synchronize_*``, against ``_update_*``'s **245**. It is not
merged into ``_update_`` -- the verb carries a fact the other does not, that there
is a source of truth elsewhere. ``[review]`` rather than ``ABOLISHED``, since not
every ``_synchronize_`` is this operation.

**A name that announces one branch of three is wrong in the same way as a hook
named for one of its fields** ``[review]``. ``_reserve_paths`` reserved a path,
moved one whose path had changed, and **deleted** a reservation whose path was
cleared; it is ``_sync_path_reservations``. Its own test was named
``test_the_reservation_follows_the_path``: **where a test and the method it covers
disagree about what the operation is, prefer the test's word.**

**``_post_`` is overloaded** ``[review]``. 106 definitions carry three unrelated
meanings -- ``account.move._post`` (accounting), ``message_post`` (mail) and HTTP
handlers. Do not add a fourth: new code names the domain operation. The existing
three are load-bearing.

2.4.13 Scope, adoption and the ratchet
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**The vocabulary governs model methods** -- classes deriving from
``models.Model`` / ``TransientModel`` / ``AbstractModel``. The framework packages
below the ORM (``odoo/db``, ``odoo/http``, ``odoo/tools``, ``odoo/orm``
internals) legitimately speak SQL and Python data-structure vocabulary and are out
of scope. The carve-out is about *packages*: a helper in an addon's ``models/``
may not borrow that vocabulary, whether or not it is indented under a class.

**It governs the module's own helpers too, and no gate sees them** ``[review]``.
``naming_vocabulary.py`` implements the scope as a *class-membership* test, so two
populations in the same files are counted by nothing: a function declared at
**module level** -- **288** of them under ``models/`` and ``wizard/`` -- and a
method on a **plain class** declared in the same file, of which there are **355**
across **135** classes. Counted over the addon trees only, since a directory test
alone would sweep in ORM internals the vocabulary does not reach.

**A file can be sixteen names wrong and green.** Three sweeps
(``ir_actions_report.py``, ``ir_asset_paths.py``, ``ir_asset.py``) left the ratchet
reporting the same count before and after -- the argument for the ``[review]``
tier, stated as a measurement. **The one that was already right is worth as much
as the ten that were not**: read the body of every name in an ungated file.

**Adoption** ``[ratchet naming]``. As with §2.2, apply the vocabulary to methods
you create or substantially rework. ``naming_vocabulary.py`` counts definitions
still using an abolished verb and feeds the shared ratchet; ADR-0033 argues why
this section is counted rather than blocked::

    python tooling/architecture/naming_vocabulary.py --count \
        | xargs python tooling/ratchet/ratchet.py naming --count

It measures the **mechanically decidable** rules only -- the abolished-verb list.
The ``_get_``/``_prepare_`` split and the two *provisional* rules are excluded by
design, because a floor nobody can lower by reading the rule is a floor people
learn to ignore.

2.4.14 Bindings a rename must carry
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**A rename carries its bindings, and that is the whole of the constraint**
``[review]``. *Inherited* is not a property of a name but a statement about who
else holds it, and ``git grep -ln '<name>' 19.0`` answers it against the pristine
mirror. That buys an estimate of the work, not a veto: a rule freezing every name
the baseline picked is *increases divergence* wearing a safety rule's clothes.

* **Greppable, inside the workspace** -- an XML ``name="..."``, a JS reference, an
  override in a sibling checkout. **Cost, not a veto**: rewrite them in the same
  commit. A Python-only refactor breaks them silently and no gate catches it.
* **Computed from data** -- a migration, not a rename.
* **Reachable from outside the workspace** -- a public method an integration may
  call over RPC. Weigh it as a public-surface change, give it the record
  ``doc/adr/README.md`` asks for, and consider leaving the old name as a
  delegating shim.

**A protocol declaration is a binding** ``[review]``. The members declared in
``odoo/orm/_protocols.py`` are pinned in ``model_member_surface_check.py``'s
``KNOWN_MEMBER_SURFACE``, so the pin moves with the rename or the gate fails both
ways. A leading underscore is not evidence that a method is local.

Two shapes a Python-only grep misses: **model methods are called by name over RPC
from JS**, and ``mail``'s mock server reimplements Python members so HOOT can run
without a database; and **a prose pointer in another repository is a binding
nothing greps** -- a search written as call syntax (``._get_path(``) finds every
binding and no prose.

**A private method can be reached from outside the workspace**
``[gate doc_restated_counts]``. ``ir.actions.server`` stores **Python source in a
database column**: **103** distinct private method names are reached that way from
**112** code blocks in **68** shipped data files of this repository -- and the
shipped files are only the half a grep can see, since the field is edited in the
UI. **The question is not public against private, but whether a name is written
down anywhere this workspace cannot rewrite.** ``_for_xml_id`` is the case, and it
is taken (ADR-0056): 535 places over 351 files in three repositories, plus a
pre-migration rewriting the name in every column that holds Python. **A rename of
this kind is not finished when the tree is green.**

**A name assembled at runtime is a schema, not a name** ``[review]``. The caller
computes the name and reaches it through ``getattr``. ``odoo/addons/base`` carries
12 of this repository's 33, on 7 % of its model methods::

    getattr(self, f"_run_action_{self.state}")          ir_actions_server
    getattr(self, f"_auth_method_{auth}")                ir_http
    getattr(self, "_render_" + report_type)              ir_actions_report
    getattr(self, f"_compile_directive_{directive}")     ir_qweb
    getattr(self, f"_postprocess_tag_{elem.tag}")        ir_ui_view
    getattr(self, f"_check_view_tag_{elem.tag}")         ir_ui_view

Three consequences, in ascending expense:

#. **The prefix is frozen.** ``_check_view_tag_calendar`` is not an
   ``@api.constrains`` hook -- it is a key in a table. Check for the ``getattr``
   before believing the vocabulary.
#. **Identical bodies are the design, not duplication.** The *key* carries the
   information and the body only answers, so a duplicate report over ``base``
   needs reading rather than acting on.
#. **Some of them need a migration, not a rename.** Where the variable half comes
   from a *stored column* -- ``ir.actions.server``'s ``state``, extended by every
   addon's ``selection_add`` -- the method name is part of the data, and renaming
   it orphans stored records in every database with no gate, test or import error
   to say so.

**Wearing a dispatch prefix does not make a name a key** ``[review]``. **11**
definitions begin ``_render_qweb_``; exactly **3** are keys, because ``_render``
builds its target from ``report_type``, whose Selection offers three values. **The
set of keys is the enumerable domain of the variable half, never the set of names
beginning with the literal half.** *Nothing in the ``_render_`` family needs
renaming* -- **a campaign that cannot return "this one is already right" is not
measuring, it is churning.**

Adding a dispatch table is a design decision: it creates a naming contract this
section cannot check. Prefer a registry keyed on data you can enumerate; if you
add one, say so in the dispatcher's docstring, because the ``getattr`` is the only
evidence the targets are not free to be renamed.

**Bound by name, not by inheritance** ``[review]``. The framework calls a method on
a model it resolved at runtime, and any model defining that name answers.
``ir.actions.report`` calls ``_get_report_values`` on a model looked up from the
report's record: 24 classes in this repository implement it, related to each other
and to the caller by nothing but the spelling. ``res.config.settings`` does the
same to ``get_values`` and ``set_values``, at 13 and 22. None is declared as an
interface, and all three counts stop at this repository (ADR-0033) while the
contract does not. Before renaming a method whose name looks conventional rather
than invented, grep the *framework* for a bare call of it. **Give a new one of
these an ``AbstractModel`` to inherit, so the contract has a declaration site.**

**And the key is not the method** ``[review]``. ``report_action`` is a **context
key** as well as a method name, so a text substitution takes the key -- and a
local variable of the same name -- along with the method. The same caution applies
to a field name and a registry string.

2.4.15 Signatures
~~~~~~~~~~~~~~~~~

* **An override's signature must match its parent's**
  ``[test_lint test_override_signatures]``. Adding, removing or renaming a
  parameter, or changing its default, is a hard failure. This is what makes
  ``@typing.override`` (§2.9.11) useful rather than decorative.
* **Public methods may not take an ``ids`` or ``context`` parameter**
  ``[test_lint test_naming]``: both collide with the RPC calling convention.
* **A route handler's parameters are named by the route.** ``web``'s
  ``content_common(..., field: str = "raw")`` sits behind a route carrying
  ``<string:field>``: the parameter name **is** the URL segment, and is not
  repaired.

**``field`` is a ``Field``; a field's name is ``field_name``**
``[gate doc_restated_counts]``. A parameter name is the only type statement most
call sites ever see. **78** parameters annotated ``field_name`` are ``str`` and
**0** are a ``Field``, against ``field``'s **91** ``Field`` and **15** ``str``.
One direction is clean; the other is the backlog. The ORM breaks the rule in the
package that states it, and ``lifecycle.py``'s
``_get_placeholder_filename(self, field: str)`` is *bound by name*, so its
parameter name is copied into every addon implementing it.

2.4.16 Placement
~~~~~~~~~~~~~~~~

**Naming fixes placement.** The prefix determines the §2.2 section:

.. list-table::
   :header-rows: 1

   * - Name or decorator
     - Section
   * - ``create`` / ``write`` / ``unlink`` / ``copy_data`` / ``default_get``;
       ``@api.model_create_multi``; ``@api.ondelete``
     - ``# CRUD METHODS``
   * - ``_compute_*``; ``@api.depends``
     - ``# COMPUTE METHODS``
   * - ``_search_*``
     - ``# SEARCH METHODS``
   * - ``_inverse_*``
     - ``# INVERSE METHODS``
   * - ``_onchange_*``; ``@api.onchange``
     - ``# ONCHANGE METHODS``
   * - ``_check_*`` (legacy ``_validate_*``); ``@api.constrains``
     - ``# CONSTRAINT METHODS``
   * - ``action_*``
     - ``# ACTION METHODS``
   * - ``_message_*`` / ``_notify_*`` / ``_track_*``
     - ``# MAIL METHODS``
   * - ``_domain_*`` / ``_selection_*`` (field hooks with no banner of their own)
     - ``# HELPER METHODS``
   * - ``_prepare_*`` / ``_get_*`` and other internals
     - ``# HELPER METHODS``
   * - ``_auto_init`` / ``init``
     - ``# HOOKS``

``# <DOMAIN> METHODS`` is the module's business domain, not ``domain=``.

**``action_*`` is a binding, not a family** ``[review]``. The client invokes the
method **by name** -- an XML ``<button name="…" type="object">``, a
``<menuitem action="…">``, a JS call -- so it is not a rule that everything
returning an action dict wears ``action_``; read that way it collides with the
payload family. **The discriminator is who invokes it**: invoked by the client by
name → ``action_*`` / ``action_view_*``; built in Python and returned by something
else → ``_prepare_*`` or its public form. *Frozen reading* (§1.4) at
``2e691b7b90d``, an ad-hoc scanner, not re-derivable: **790** of the **947**
distinct ``action_*`` model methods in the bundled tree appear as a literal
``name=`` or ``action=`` in XML or JS. That sizes the convention, not the
violation.

**Field wiring beats the name.** A method referenced by ``inverse="..."`` is an
inverse even if it is called ``set_*``; ``compute=`` and ``search=`` likewise pin
their targets. A method used as a field ``default=`` is evaluated at
class-creation time, so it must be defined *above* the field block.
``_search_display_name(self, operator, value)`` is the Odoo 19 hook backing
``name_search``; ``_name_search`` no longer exists.

2.4.17 Cache lifecycle verbs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``invalidate_`` / ``clear_`` / ``reset_`` are not interchangeable ``[review]``.
Cache-coherency bugs are the most expensive class of bug in this system.

.. list-table::
   :header-rows: 1

   * - Verb
     - Means
     - Failure it prevents
   * - ``invalidate_*``
     - Drop values that may be **stale with respect to the database**. A
       *correctness* operation: the data is still wanted, it is no longer
       trustworthy.
     - Serving a value the database has since changed.
   * - ``clear_*``
     - Drop everything held, unconditionally. A *lifecycle* operation --
       teardown, or handing the object to a new owner.
     - Leaking one transaction's or database's state into the next.
   * - ``reset_*``
     - Rebuild derived state **from its source**. Not a drop: the state exists
       again afterwards.
     - Reasoning over a derived structure that no longer matches what derived it.

Pick the verb by what the caller needs, and do not add a fourth. A method that
would honestly need two of them is doing two things.

* **These three are reserved for caches, and the borrowing goes outward**
  ``[review]``. A method that drops **rows** is ``_remove_*``: ``_clear_schedule``
  issued a ``DELETE`` against ``ir_cron_trigger`` for triggers already due, and is
  ``_remove_triggers_due``.
* **The verb governs whatever is named after the operation, not only the method
  that performs it** ``[review]``. ``_cache_invalidating_fields`` and
  ``_unconditional_clear_fields`` fed one decision through a local called
  ``clear``: one operation, two of the three verbs, in a file that caches nothing.
  They are ``_get_fields_invalidating_always`` and
  ``_get_fields_invalidating_when_cached``.
* **A name in adjective position needs a participle** ``[review]``. The canonical
  read verb has no participle anybody writes -- ``got_bundles`` is not a name --
  so the abolished ``fetched_bundles`` survived where the table cannot serve.
  **Name the state, not the operation**: ``loaded_bundles``, on the model of
  ``BundleWalk.walked``. A **method** performing the read is still ``_get_*``.
* **A memoised read is three methods** ``[review]``: an **entry** deciding which
  path to take, a **memoised** wrapper carrying ``@tools.ormcache``, and the
  **body** both reach. The only thing separating them is the caching:
  ``_get_X`` / ``_get_X_cached`` / ``_get_X_uncached``.
* **``_cache`` and ``_cached`` are different tails** ``[review]``. ``_cache`` names
  **the cache object** (``_get_view_cache``) at 25 methods; ``_cached`` marks
  **the memoised variant** of the method above it, at 14.
* **``_impl`` names the implementation, which is not a fact about the operation**
  ``[review]``. Every method implements itself; where the suffix appears there is
  a real discriminator left unsaid. The family is at 0 here.

2.5 Docstrings and comments
---------------------------

Mandatory on models and on non-trivial methods ``[review]``. Simple accessors may
omit them.

**No linter enforces presence** ``[review]``. ``ruff``'s ``D`` rules are not
selected and the ``ruff_docstring`` ratchet is retired. **Accuracy is still
mechanical**: ``DOC`` (pydoclint) remains selected and fires only on docstrings
that *exist* -- an extraneous ``:param:``, a documented exception that cannot be
raised -- and where a docstring documents parameters, its fields must agree with
the signature ``[test_lint test_docstring]``. Nothing obliges you to write one;
writing a wrong one still fails.

**Two bodies of docstrings are load-bearing and must not be removed.**
``odoo/cli/`` docstrings are the CLI's user-facing help text -- ``help.py``
renders ``cmd.__doc__``, ``command.py`` feeds it to argparse, and
``upgrade_code.py`` calls ``__doc__.replace()``, which raises ``AttributeError``
the moment it becomes ``None``; eight ``base`` tests gate them. A handful more are
machine-checked contracts read by ``tooling/architecture/`` and
``tests/service/``: ``orm/__init__.py``, ``orm/models/mixins/_metadata.py``,
``service/__init__.py``, ``service/db.py``, ``http/tests/test_openapi.py``.
Deleting either kind breaks a test, not a style gate.

Use Sphinx fields:

.. code-block:: python

   class SaleOrder(models.Model):
       """Sales order management with multi-currency support."""

       def _prepare_invoice_vals(self, order_line):
           """Prepare values for invoice creation.

           :param recordset order_line: lines to invoice
           :return: values accepted by ``account.move.create``
           :rtype: dict
           """

* One line for a model docstring: what the entity *is*.
* Field-by-field listings belong in each field's ``help=``, not the class
  docstring.
* ``"""triple double quotes"""``, never ``'''single'''``.
* **Be correct.** Verify every claim against the code; delete stale references. A
  docstring that contradicts the code is worse than none -- update it in the same
  edit that changes a signature, a return type or a behaviour.
* **Be direct.** Cut *Basically*, *Essentially*, *Note that*, *This method
  simply*. Use the imperative: "Return…", "Raise…", "Compute…".
* **Do not restate the obvious.** A docstring echoing the method name, or
  retyping the signature, is noise.
* **Comments explain why, not what.** A comment narrating the next line has
  earned its deletion.

2.6 ORM
-------

**Always ``super()``** in ``create``, ``write``, ``unlink``, ``copy_data``,
``default_get`` and ``_compute_display_name`` ``[review]``. Prefer overriding
``copy_data`` over ``copy`` -- it is the values hook ``copy`` is built on.

**Override ``create`` in batch form** ``[review]``:

.. code-block:: python

   @api.model_create_multi
   def create(self, vals_list):
       for vals in vals_list:
           ...
       return super().create(vals_list)

**Every model declares ``_name`` and ``_description``** ``[review]``. Set
``_order`` when insertion order is wrong. For the record label set ``_rec_name``,
or override ``_compute_display_name`` calling ``super()``; ``name_get`` no longer
exists.

**Deletion constraints use ``@api.ondelete``** ``[test_lint E8506]``. A ``raise``
inside an ``unlink()`` override fails the checker -- the override runs at
uninstall too, and blocks it.

.. code-block:: python

   @api.ondelete(at_uninstall=False)
   def _unlink_except_confirmed(self):
       if any(r.state != "draft" for r in self):
           raise UserError(self.env._("Cannot delete a confirmed order."))

**The framework owns transactions.** Do not call ``self.env.cr.commit()`` or
``rollback()`` from business code. Only the framework, the cron runner and code
holding its own cursor (``self.env.registry.cursor()``) may commit.

**Assign fields directly in computes** (``self.field = value``); ``write()`` in a
compute recurses.

**``ensure_one()``** at the top of any method that assumes a single record.

**Context is a frozen dict** -- propagate with ``with_context``. For company
scoping use ``with_company``:

.. code-block:: python

   order.with_context(tracking_disable=True).action_confirm()
   order.with_company(company).action_confirm()   # not with_context(force_company=...)

**``force_company`` fails silently, so grep for it rather than waiting for an
error.** ``with_context(force_company=...)`` emits a ``DeprecationWarning`` and
otherwise does nothing: no exception, the key stays in the context, nothing reads
it, and surviving call sites run against the *wrong company*.

**Prefer recordset operations** -- ``filtered``, ``mapped``, ``sorted`` -- over
manual loops, and ``odoo.tools.groupby`` over ``itertools.groupby``: it handles
recordsets and needs no pre-sorting.

**Think extendable.** Avoid hard-coded values that should be configuration. Split
methods so another module can override one piece without copying the rest.

**Deprecate explicitly**:

.. code-block:: python

   @api.deprecated("Since 19.0, use _prepare_invoice_vals instead")
   def _prepare_invoice(self):
       return self._prepare_invoice_vals()

ORM performance -- counts, aggregation, batching, N+1, indexing, locking,
``ormcache``, cron batching -- is **§11**, their single source.

2.7 Error handling
------------------

.. list-table::
   :header-rows: 1

   * - Exception
     - Use for
   * - ``UserError``
     - Business-logic violations the user can act on
   * - ``ValidationError``
     - Constraint failures inside ``@api.constrains``
   * - ``AccessError``
     - Permission and security violations (HTTP 403)
   * - ``RedirectWarning``
     - Errors the user resolves by navigating somewhere
   * - ``MissingError``
     - The record is gone or inaccessible
   * - ``ValueError``
     - Invalid arguments to internal methods -- never user-facing

**User-facing exceptions take a translated message, not a raw literal**
``[test_lint E8505]``. ``UserError``, ``ValidationError``, ``AccessError``,
``AccessDenied`` and ``MissingError`` all require the first argument to go through
``self.env._()`` (§8.1):

.. code-block:: python

   raise UserError(self.env._("Order %s cannot be confirmed.", order.name))
   raise RedirectWarning(
       self.env._("Please configure a default warehouse."),
       action_id,
       self.env._("Go to Settings"),
   )

**Never leak internals**:

.. code-block:: python

   # Wrong — exposes stack internals, SQL fragments, paths
   except Exception as e:
       raise UserError(str(e))

   # Right — generic message to the user, full traceback in the log
   except Exception:
       _logger.error("Payment processing failed", exc_info=True)
       raise UserError(self.env._("Payment could not be processed. Contact support."))

**Fail closed.** Wrap each iteration in a savepoint so a failure rolls back or
transitions to an explicit error state. In financial or state-mutation code,
log-and-continue is a violation:

.. code-block:: python

   for order in orders:
       try:
           with self.env.cr.savepoint():
               order._process_payment()
               order.action_confirm()
       except UserError:
           order.state = "error"
           _logger.error("Failed to process order %s", order.name, exc_info=True)

``except Exception`` is ``[review]`` -- ``BLE001`` is disabled in ``ruff.toml``
because Odoo legitimately catches ``Exception`` around external and ORM calls. Use
it for catch-log-reraise and for integration adapters, not as a default.

**Chain exceptions**: ``raise X from Y`` (or ``from None``) inside ``except``
``[ruff B904]``.

2.8 Controllers
---------------

.. code-block:: python

   from odoo import http
   from odoo.http import request


   class SaleController(http.Controller):
       @http.route("/shop/cart", type="http", auth="public", methods=["GET"], website=True)
       def cart(self):
           order = request.website.sale_get_order()
           return request.render("website_sale.cart", {"order": order})

       @http.route("/api/orders", type="jsonrpc", auth="bearer", methods=["POST"])
       def create_order(self, **kwargs):
           order = request.env["sale.order"].create(kwargs)
           return {"id": order.id}

.. list-table::
   :header-rows: 1

   * - Parameter
     - Values
   * - ``type``
     - ``"http"`` (HTML/binary) or ``"jsonrpc"``
   * - ``auth``
     - ``"user"`` (default), ``"public"``, ``"bearer"`` (API token), ``"none"``
   * - ``methods``
     - ``["GET"]``, ``["POST"]``, …
   * - ``csrf``
     - default ``True`` for ``http``, ``False`` for ``jsonrpc``

An overriding controller re-declares the route with ``@route()`` but **must not
restate attributes it does not change** ``[test_lint test_routes]``: repeating
``type=`` and ``auth=`` at their inherited values hides what the override
modifies. Controller security is §10.6.

2.9 Patterns
------------

2.9.1 ``Domain``
~~~~~~~~~~~~~~~~

.. code-block:: python

   from odoo.fields import Domain

   domain = Domain("state", "=", "draft")
   combined = Domain("state", "=", "draft") & Domain("partner_id", "!=", False)
   either = Domain("type", "=", "out_invoice") | Domain("type", "=", "out_refund")
   negated = ~Domain("active", "=", False)

   Domain.AND([d1, d2, d3])
   Domain.OR([d1, d2])
   Domain.TRUE      # matches everything
   Domain.FALSE     # matches nothing

Use ``Domain`` for anything built programmatically. The list-of-tuples form stays
valid for static domains in XML and data files.

2.9.2 Recordset safety
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   records = records.exists()        # drop rows deleted by another transaction

   record = self.env["sale.order"].browse(record_id).exists()
   if not record:
       raise MissingError(self.env._("Record %s has been deleted.", record_id))

2.9.3 Context keys
~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Key
     - Effect
   * - ``active_test``
     - ``False`` includes archived records in searches
   * - ``lang``
     - force a language
   * - ``tz``
     - force a timezone for display
   * - ``default_<field>``
     - default value for new records
   * - ``active_ids`` / ``active_model``
     - source records for wizards and server actions
   * - ``tracking_disable``
     - suppress mail tracking on ``write()`` -- for bulk imports

A field may carry its own context for relational access:

.. code-block:: python

   child_ids = fields.One2many("res.partner", "parent_id", context={"active_test": False})

2.9.4 Monetary fields
~~~~~~~~~~~~~~~~~~~~~

``fields.Monetary`` needs a companion currency. A missing one trips an ``assert``
in ``Monetary.setup_nonrelated`` / ``setup_related``, so it fails when the registry
is built -- at module load, not on first use -- and not at all under ``python -O``
(§10.3):

.. code-block:: python

   currency_id = fields.Many2one("res.currency", required=True)
   amount_total = fields.Monetary()                              # picks currency_id

   base_currency_id = fields.Many2one("res.currency")
   amount_in_base = fields.Monetary(currency_field="base_currency_id")

2.9.5 String formatting
~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Context
     - Use
     - Never
   * - General code, exception messages
     - f-strings
     - --
   * - Translations
     - ``%s`` / ``%(name)s`` args to ``self.env._()``
     - f-strings -- extraction silently breaks
   * - Logging
     - ``%s`` args to the logger
     - f-strings ``[ruff G004]``
   * - SQL parameters
     - ``%s`` placeholders
     - f-strings -- injection ``[test_lint E8501]``
   * - HTML in errors
     - ``%``-style or ``.format()`` inside ``Markup()``
     - f-strings -- XSS

2.9.6 Datetime
~~~~~~~~~~~~~~

``datetime.utcnow()`` is banned twice over ``[ruff DTZ003]`` and by ``banned-api``;
``utcfromtimestamp`` likewise ``[ruff DTZ004]``. Most other ``DTZ`` rules are off,
because the ORM stores naive UTC by design.

.. code-block:: python

   from datetime import UTC, datetime

   now_aware = datetime.now(UTC)                          # external APIs
   now_naive = datetime.now(UTC).replace(tzinfo=None)     # ORM Datetime fields

Comparing an aware ``datetime.now(UTC)`` with a naive ORM value raises
``TypeError``. Odoo pins the process timezone to UTC at startup, so inside a
running server the OS-local zone *is* UTC -- a discrepancy reproduced outside Odoo
is usually an artefact of the harness.

2.9.7 ``Command`` for x2many writes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use ``odoo.fields.Command`` ``[review]``; the raw magic tuples are unreadable.

.. code-block:: python

   from odoo.fields import Command

   order.write({
       "line_ids": [
           Command.create({"product_id": p.id, "qty": 1}),   # was (0, 0, {...})
           Command.link(existing_line.id),                    # was (4, id)
           Command.set(new_line_ids),                         # was (6, 0, [...])
           Command.clear(),                                   # was (5, 0, 0)
       ],
   })

2.9.8 SQL constraints
~~~~~~~~~~~~~~~~~~~~~

Declare them with ``models.Constraint`` in the ``# CONSTRAINTS`` section
``[review]``. The legacy ``_sql_constraints = [...]`` list is deprecated.

.. code-block:: python

   # CONSTRAINTS
   _amount_positive = models.Constraint(
       "CHECK(amount >= 0)",
       "The amount must be positive.",
   )
   _code_unique = models.Constraint(
       "UNIQUE(code, company_id)",
       "Code must be unique per company.",
   )

**The attribute names the columns, and nothing checks that it does** ``[review]``.
``TableObject.__set_name__`` takes the attribute name verbatim and ``full_name``
builds the PostgreSQL identifier as ``{table}_{attr}``, so the attribute is the
constraint's name in the database, in ``ir.model.constraint`` and in every error a
user sees. No linter reads it -- ``test_translated_unique`` checks the *column* --
so a constraint can name a column the table lost four major versions ago
(``ir.model``'s ``_obj_name_uniq``, declared ``UNIQUE (model)``). Name the columns
the definition names, in the order it names them, and keep the predicate in the
tail -- the tree spells that tail ``_uniq`` **73** times against ``_unique``'s
**51**, so prefer ``_uniq`` for a new one and do not sweep the others for it.

**A constraint rename is carried by module-data cleanup, not by a migration**
``[review]``. ``_reflect_constraints`` registers each constraint as module data
under ``{module}.constraint_{conname}``; on the next upgrade the old xmlid is
absent from ``loaded_xmlids``, ``ir.model.data._process_end`` unlinks the orphan,
and ``IrModelConstraint.unlink`` drops the constraint it names. **Check this
before writing a migration for a rename in this family.**

**What the rename does break is the translations, and that binding is invisible**
``[review]``. ``message`` is a translated field on a *record*, so its translations
are keyed by the record's external id -- the
``#: model:ir.model.constraint,message:base.constraint_<conname>`` reference in
each ``i18n/<lang>.po``. The upgrade deletes the old record and creates a new one,
so a rename that does not sweep those references leaves every translation matching
nothing, in silence, and the message reverts to English. ``_obj_name_uniq`` was
named in **64** of ``base``'s catalogues, the ``.pot`` template among them -- miss
that one and the next export puts the stale reference back.

**Never declare UNIQUE over a translated column**
``[test_lint test_translated_unique]``. A ``translate=True`` field is stored as
``jsonb``, so the constraint compares whole translation *documents* rather than
values: two rows stop colliding the moment one carries a language the other does
not. That is the next create, not a later translation step, because Odoo writes
the active language alongside the source term -- so the rule enforces nothing,
silently, and only in databases with a second language.

Use ``name_uniq_index()`` from ``odoo/addons/base/models/catalog_mixin.py``, which
indexes the source term. It is a ``models.UniqueIndex`` rather than a
``Constraint`` because the comparison is an expression, which PostgreSQL does not
allow in a UNIQUE constraint:

.. code-block:: python

   # CONSTRAINTS
   _name_src_uniq = name_uniq_index(
       "company_id",
       message="A template with this name already exists for this company.",
   )

When **converting an existing** ``UNIQUE(name, ...)``, pass ``nulls_distinct=True``
so only the comparison changes. The helper otherwise defaults to
``NULLS NOT DISTINCT``, right for a catalog adopting the rule for the first time
but tighter than the old constraint: a plain UNIQUE never fired for two rows
sharing a NULL scope column, and code relies on that (``res.groups`` holds several
same-named groups with no privilege).

2.9.9 Onchange
~~~~~~~~~~~~~~

``@api.onchange`` takes plain field names -- dotted paths are silently ignored.
The method runs on a pseudo-record that may not exist in the database, so calling
any CRUD method on it is undefined behaviour; assign fields or call ``update()``.

**Returning a domain from an onchange is forbidden**
``[test_lint test_onchange_domains]``. Dynamic domains belong on the field
(``domain=``) or in the view, where they survive the round trip. An onchange may
still return a ``warning`` dict.

A One2many or Many2many field cannot modify itself through an onchange -- a
webclient limitation, not a fork one.

2.9.10 Multi-company
~~~~~~~~~~~~~~~~~~~~

Multi-company correctness is a fork-wide requirement ``[review]``:

* Relational fields that must stay inside the record's company carry
  ``check_company=True`` (the model needs a ``company_id``).
* Per-company scalar configuration uses ``company_dependent=True``.
* Read the active company as ``self.env.company``; scope work with
  ``with_company(company)``. Never guess or hard-code a ``company_id``.
* Company record rules use ``[("company_id", "in", company_ids + [False])]`` so
  company-less shared records stay visible (§10.8).

.. code-block:: python

   company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
   warehouse_id = fields.Many2one("stock.warehouse", check_company=True)
   default_journal_id = fields.Many2one("account.journal", company_dependent=True)

2.9.11 Type hints
~~~~~~~~~~~~~~~~~

Optional but encouraged for public API, framework code and non-obvious return
types ``[review]``. ``ANN`` is linted only in ``odoo/libs/`` and
``odoo/orm/components/``. Python 3.14's PEP 649 deferred annotations mean forward
references work unquoted.

**Modern generics only** ``[ruff banned-api]``: ``list[X]``, ``dict[K, V]``,
``tuple[X, ...]``, ``X | None``. ``typing.Optional``/``List``/``Dict``/``Tuple``/
``Set``/``Union`` are banned.

.. code-block:: python

   from typing import TYPE_CHECKING, override

   if TYPE_CHECKING:
       from .res_users import ResUsers


   class ResPartner(models.Model):
       _name = "res.partner"

       user_ids: ResUsers = fields.One2many("res.users", "partner_id")

       @override
       def create(self, vals_list):
           ...
           return super().create(vals_list)

Apply ``@typing.override`` to overridden parent methods. It is not linted, but it
pairs with the signature gate in §2.4.15: together they turn a renamed or
re-signed parent from a silent behaviour change into an error.

2.9.12 Float and currency comparison
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Never compare floats or ``Monetary`` values directly.** Use the ORM helpers,
passing ``precision_rounding=<currency>.rounding`` or ``precision_digits=<n>``.
Do not invent epsilons.

.. code-block:: python

   from odoo.tools import float_compare, float_is_zero, float_round

   rounding = order.currency_id.rounding
   if float_is_zero(line.price_subtotal, precision_rounding=rounding):
       ...
   if float_compare(paid, total, precision_rounding=rounding) >= 0:    # paid >= total
       order.state = "paid"
   amount = float_round(raw_amount, precision_rounding=rounding)

``[ruff RUF069]`` covers ``==`` and ``!=`` **only**, and only where it can infer
that both operands are floats. Ordering comparisons and anything behind a
recordset attribute are ``[review]``. The linter is a backstop, not coverage.

2.9.13 Logging
~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Level
     - Use for
   * - ``debug``
     - development diagnostics; off in production
   * - ``info``
     - normal business events (import finished, cron ran)
   * - ``warning``
     - recoverable issues, deprecated usage, fallback paths
   * - ``error``
     - unhandled exceptions and data corruption -- with ``exc_info=True``

Pass arguments lazily; f-strings in a logging call are linted ``[ruff G004]``, and
eagerly stringifying an argument is too ``[ruff RUF065]``.

For cross-model flows (invoicing, EDI, payments) put a correlation identifier in
every line so one business transaction can be traced end to end:

.. code-block:: python

   _logger.info("[order:%s] Starting invoice creation", order.name)
   _logger.info("[order:%s] PAC stamping completed, UUID: %s", order.name, uuid)

2.9.14 Background jobs (``ir.job``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For deferred one-off work use the framework job queue -- not ad-hoc threads, not
``cr.commit()`` loops, not the legacy OCA ``queue_job``. Crons remain the tool for
*recurring* work; ``ir.job`` is for "run this later, in the background, with
retries" ``[review]``.

.. code-block:: python

   class StockPicking(models.Model):
       _inherit = "stock.picking"

       @api.job(channel="wms", max_retries=3)
       def _sync_to_wms(self, batch_size=100):
           ...

   # enqueued in the current transaction, executed after commit
   picking.delayed(priority=5, eta=60)._sync_to_wms(batch_size=50)

* Job methods are **private**; the decorator rejects a public name, and the worker
  refuses to run anything undecorated -- a hand-crafted ``ir_job`` row cannot call
  arbitrary code.
* Arguments must be **JSON-serialisable**. Pass ids, not recordsets or datetimes;
  the records the job targets ride on ``delayed()``'s own recordset.
* Write bodies **idempotent or transaction-safe**. Completion is atomic with the
  job's writes, so partial effects never survive a crash -- external side effects
  (HTTP calls, mail) need their own guards.
* Transient failures raise ``RetryableJobError(seconds=...)``; any other exception
  also consumes one of ``max_retries`` before the job is marked failed. Both roll
  the job's transaction back.
* Concurrency is bounded per **channel**. A channel absent from ``ir.job.channel``
  has an implicit capacity of 1 -- give heavy integrations their own channel
  instead of tuning priorities.
* Chain with ``delayed(after=job)``, fan in by passing a union, collapse bursts
  with ``identity_key``. A deferral does **not** release dependents.
* Defaults: ``channel="root"``, ``priority=10``, ``max_retries=5``,
  ``max_defers=100``.
* Ops surface: Settings → Technical → Automation → Background Jobs. Smoke-test a
  deployment with ``env["ir.job"].delayed()._job_ping()``.

**Not finished is not failed** ``[review]``. Where the body cannot complete
because something outside it is not ready, call
``self.env["ir.job"]._defer(seconds, reason=...)`` and return normally: the job's
writes are kept and committed, ``retry`` is untouched, nothing is recorded in
``exc_*``, and the job keeps its ``identity_key`` so a caller cannot queue a
duplicate while it waits. Deferrals have their own budget, ``max_defers``.

.. code-block:: python

   @api.job(channel="sat", max_retries=3, max_defers=24)
   def _poll_remote_package(self):
       self._record_progress()          # kept, whatever happens next
       if not self._package_ready():
           self.env["ir.job"]._defer(600, reason="still preparing")

Do not reach for ``RetryableJobError`` here: it is an exception, so the progress
just recorded is rolled back, and it spends a retry per attempt. Re-enqueueing a
fresh job from inside the body does not work either -- a running job is in a
queued state and still holds its ``identity_key``, so the enqueue is silently
dropped.

2.10 Lazy imports
-----------------

**Imports go at module level unless there is a documented reason.** Imports inside
functions hide dependencies, duplicate across methods and defeat module-graph
analysis. ``PLC0415`` is globally suppressed because Odoo's architecture genuinely
requires some lazy imports -- which makes this ``[review]`` and makes the
explanatory comment mandatory.

Acceptable reasons:

#. A **circular dependency** that cannot be restructured away:

   .. code-block:: python

      def json_default(obj):
          from odoo import fields  # circular: tools -> fields
          ...

#. An **optional external dependency**, guarded by ``try`` / ``except ImportError``.
#. **CLI startup cost** -- keeping ``--help`` fast.
#. **``import odoo.addons``**, whose ``__path__`` is populated at runtime.
#. **Addon model imports from framework code**, not registered at framework import
   time.

"Just in case" is not a reason. If the same import appears in two functions of one
file, promote it.

----

3. XML
======

3.1 Format
----------

Formatting and ordering are **owned by fixers** -- do not hand-align
``[test_lint test_pretty_xml, test_xml_records]``
``[fixer _pretty_xml, _sort_xml_records]``. Run the sorter first and the formatter
last: the formatter preserves order, the sorter does not preserve formatting.

The conventions they enforce:

* 4-space indentation; root element ``<odoo>``, not ``<data>``.
* Double-quoted attribute values; empty elements self-close.
* Attribute order: ``id`` then ``model`` on records; ``name`` first on fields.
* One blank line between top-level records, and after ``<odoo>`` / before
  ``</odoo>``.
* 88 columns; a tag exceeding it wraps one attribute per line. A single attribute
  longer than 88 -- a large ``domain`` or ``context`` -- stays on its own line.
* ``domain``, ``context`` and ``options`` values go on **one line**. XML
  normalises newlines inside an attribute value to spaces, so a multi-line form
  is purely cosmetic and cannot survive the formatter.

3.2 XML IDs
-----------

**Prefix style** -- role first, entity second ``[review]``. It matches Odoo
Community core, so new records sit beside the core records they relate to.

.. list-table::
   :header-rows: 1

   * - Type
     - Pattern
     - Example
   * - Views
     - ``view_{model}_{type}``
     - ``view_sale_order_form``
   * - Inherited views
     - ``view_{model}_{type}_inherit_{context}``
     - ``view_sale_order_form_inherit_custom``
   * - Actions / server actions
     - ``action_{name}``
     - ``action_sale_order``
   * - Menus
     - ``menu_{name}``
     - ``menu_sale_order``
   * - Groups
     - ``group_{name}``
     - ``group_sale_manager``
   * - Record rules
     - ``{model}_rule_{group}``
     - ``sale_order_rule_portal``
   * - Report actions
     - ``action_report_{name}``
     - ``action_report_saleorder``
   * - Report templates
     - ``report_{name}_document``
     - ``report_saleorder_document``
   * - Email templates
     - ``mail_template_{name}``
     - ``mail_template_sale_confirmation``

A few legacy core ids are model-first (``sale_order_menu``, ``sale_menu_root``)
and multi-company rules keep the core ``{model}_comp_rule`` form. Leave them;
``ref`` their real id.

3.3 Views
---------

**Form**

.. code-block:: xml

   <form>
     <header>
       <button string="Confirm" name="action_confirm" type="object"
               invisible="state != 'draft'" class="oe_highlight"/>
       <field name="state" widget="statusbar"/>
     </header>
     <sheet>
       <div name="button_box"/>
       <div class="oe_title"><h1><field name="name"/></h1></div>
       <group name="main">
         <group name="left_col"/>
         <group name="right_col"/>
       </group>
       <notebook>
         <page string="Lines" name="lines"/>
       </notebook>
     </sheet>
     <chatter/>
   </form>

**List** -- ``<list>``, never ``<tree>``:

.. code-block:: xml

   <list multi_edit="1">
     <field name="name"/>
     <field name="amount_total" sum="Total"/>
     <field name="state" decoration-success="state == 'done'"/>
     <field name="technical_field" column_invisible="True"/>
     <field name="optional_field" optional="hide"/>
   </list>

**Search** -- inside a ``<search>``, ``<group>`` no longer accepts ``string`` or
``expand``; both are rejected by view validation, while ``name``, ``invisible``,
``groups``, ``colspan`` and ``col`` remain valid. Every group and every filter
needs a ``name``, so inheritance can reach it by XPath:

.. code-block:: xml

   <search>
     <field name="name"/>
     <filter string="Draft" name="draft" domain="[('state', '=', 'draft')]"/>
     <separator/>
     <filter string="My Orders" name="my_orders" domain="[('user_id', '=', uid)]"/>
     <group>
       <filter string="Partner" name="group_partner" context="{'group_by': 'partner_id'}"/>
     </group>
   </search>

**Kanban** -- the card template is ``t-name="card"``, and the CSS classes are
``card`` and ``menu`` (not ``kanban-card`` / ``kanban-menu``):

.. code-block:: xml

   <kanban default_group_by="state">
     <templates>
       <t t-name="card">
         <div class="card">
           <field name="name"/>
         </div>
       </t>
     </templates>
   </kanban>

Across every view type: put ``name=""`` on groups, pages and divs so inheritance
has something stable to target, and write conditions as Python expressions
(``invisible=``, ``readonly=``, ``required=``). ``attrs=`` and ``states=`` were
removed in 17.0; fields referenced only by an expression are auto-injected.

3.4 Wizards
-----------

TransientModel views live in ``wizards/``. No ``<sheet>``, no ``<header>``, no
``<chatter/>``; buttons go in ``<footer>``. ``res.config.settings`` is a wizard
and belongs here.

.. code-block:: xml

   <form>
     <group>
       <field name="partner_id"/>
       <separator string="Options"/>
       <field name="option_ids" nolabel="1"/>
     </group>
     <footer>
       <button string="Apply" name="action_apply" type="object" class="btn-primary"/>
       <button string="Cancel" special="cancel"/>
     </footer>
   </form>

3.5 Inheritance
---------------

.. code-block:: xml

   <record id="view_sale_order_form_inherit_custom" model="ir.ui.view">
     <field name="name">sale.order.form.inherit.custom</field>
     <field name="model">sale.order</field>
     <field name="inherit_id" ref="sale.view_sale_order_form"/>
     <field name="arch" type="xml">
       <xpath expr="//field[@name='partner_id']" position="after">
         <field name="custom_field"/>
       </xpath>
     </field>
   </record>

Prefer ``name=`` targets over positional XPath. Positions are ``inside``,
``after``, ``before``, ``replace`` and ``attributes``; ``position="replace"`` with
empty content deletes an element. ``hasclass()`` targets by CSS class.

3.6 QWeb reports
----------------

Three parts -- document template, wrapper, action:

.. code-block:: xml

   <template id="report_sale_order_document">
     <t t-call="web.external_layout">
       <div class="page"><!-- content --></div>
     </t>
   </template>

   <template id="report_sale_order">
     <t t-call="web.html_container">
       <t t-foreach="docs" t-as="doc">
         <t t-call="module.report_sale_order_document"/>
       </t>
     </t>
   </template>

   <record id="action_report_sale_order" model="ir.actions.report">
     <field name="name">Sales Order</field>
     <field name="model">sale.order</field>
     <field name="report_type">qweb-pdf</field>
     <field name="report_name">module.report_sale_order</field>
     <field name="binding_model_id" ref="sale.model_sale_order"/>
     <field name="binding_type">report</field>
     <field name="binding_view_types">list,kanban</field>
   </record>

``report_name`` is required and points at the QWeb template. ``report_file`` is
optional -- a PDF base-filename hint core often omits. ``binding_type`` is
``"report"`` (Print menu) or ``"action"``; ``binding_view_types`` is
order-significant and is most often ``list,kanban``. Use ``t-lang=`` at the
``t-call`` level to localise.

3.6.1 PDF rendering is WeasyPrint
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This fork renders ``qweb-pdf`` with **WeasyPrint** and real CSS Paged Media;
wkhtmltopdf is gone, and so is its folklore. The engine is ``WeasyPrintEngine`` in
``odoo/addons/base/models/ir_actions_report.py``; the paged-media CSS is
``addons/web/static/src/webclient/actions/reports/report_paged_media.css`` and
``report_pdf_layout.css``, both with substantial header comments.

**Layout**

* Bootstrap **5** class names only. ``text-right`` / ``text-left`` no longer exist
  and fail silently -- use ``text-end`` / ``text-start``, ``float-end``, ``ms-*`` /
  ``me-*``.
* Responsive breakpoints (``col-md-*``, ``d-md-*``) are meaningless in paged media.
  Core layouts branch on ``report_type == 'pdf'`` and use CSS Grid there
  (``o_report_header_*``, ``o_report_footer_grid``). Do not lay out with
  ``<table>``.
* Report CSS goes in an SCSS file added to ``web.report_assets_common``, not in
  inline ``<style>`` blocks or ``style=`` attributes. Consume the per-company
  design tokens (``--co-primary``, ``--co-font``, ``--rp-*``) instead of
  hard-coding colours.

**Paperformat**

Live fields: ``format`` / ``page_width`` / ``page_height``, ``margin_*`` (mm),
``orientation``, ``header_line``, ``css_margins``. ``dpi``, ``header_spacing`` and
``disable_shrinking`` still exist on the model but are wkhtmltopdf-era and inert
-- do not set them on new paperformats. Header and footer size is controlled by
``margin_top`` / ``margin_bottom``; the ``.header`` and ``.footer`` divs become CSS
running elements in the page margin boxes.

**Paged-media toolbox**

* Page numbers: ``<span class="page"/>`` and ``<span class="topage"/>``, backed by
  CSS counters. Never JavaScript.
* Break control: ``o_page_break_before`` / ``o_page_break_after``,
  ``break-inside: avoid``, and ``o_thead_no_repeat`` to stop a ``<thead>``
  repeating on long tables.
* PDF outline: ``bookmark-level`` is set on ``h2[name="document_title"]`` and
  ``h3[name]``, so real headings give multi-record batches a navigable outline.
* Also supported, and preferable to hacks: ``string-set`` running headers,
  ``target-counter()`` with ``leader('.')`` for tables of contents, named
  ``@page`` rules for landscape annexes, and ``float: footnote``.
* PDF/A-3 with Factur-X and XMP metadata is native -- see ``_build_pdf_options``.
  The same ``data["__pdf_options__"]`` channel takes ``dpi`` and ``jpeg_quality``,
  the two file-size levers for image-heavy reports.

**Engine services** -- no template work required

* **Metadata**: ``/Title`` is the evaluated ``print_report_name`` (falling back to
  the action label); ``/Author`` the company, ``/Creator`` ``Odoo``, ``/Lang`` the
  record's language, which also switches on ``hyphens: auto``.
* **Watermark**: ``with_context(report_watermark="DRAFT")`` stamps text diagonally
  on every page of that print.
* **Themes**: ``report.theme`` (Settings → General → Document Layout) emits the
  ``--rp-*`` tokens per company via ``web.styles_company_report``.
* **Diagnostics**: WeasyPrint CSS warnings are captured per render. A failed
  render names the offending rule in its ``UserError``; successful renders log
  warnings at DEBUG.

In test mode ``_render_qweb_pdf`` returns raw HTML unless
``force_report_rendering`` is set. Render-path tests are in
``odoo/addons/base/tests/test_reports.py``.

3.7 Actions and menus
---------------------

.. code-block:: xml

   <record id="action_sale_order" model="ir.actions.act_window">
     <field name="name">Sales Orders</field>
     <field name="res_model">sale.order</field>
     <field name="view_mode">list,form</field>
     <field name="path">sales/orders</field>
     <field name="context">{"search_default_my_orders": 1}</field>
     <field name="domain">[('state', '!=', 'cancel')]</field>
     <field name="help" type="html">
       <p class="o_view_nocontent_smiling_face">Create a new sales order</p>
     </field>
   </record>

``view_mode`` is kanban-first for operational screens, list-first for admin and
reporting. ``path`` gives the action a readable URL. In XML domains use lists, not
tuples, and ``uid`` unquoted for the current user.

Every menuitem in a module goes in ``views/ir_ui_menu_views.xml``, not scattered
across view files:

.. code-block:: xml

   <odoo>
     <menuitem id="menu_sale_root" name="Sales" sequence="10"/>
     <menuitem id="menu_sale_order" name="Orders"
               parent="menu_sale_root" action="action_sale_order" sequence="1"/>
   </odoo>

3.8 Settings views
------------------

``<app>`` → ``<block>`` → ``<setting>``, in ``wizards/res_config_settings_views.xml``:

.. code-block:: xml

   <xpath expr="//form" position="inside">
     <app string="My Module" name="my_module">
       <block title="Features">
         <setting string="Feature X" help="Enable feature X">
           <field name="enable_feature_x"/>
         </setting>
       </block>
     </app>
   </xpath>

----

4. JavaScript
=============

4.1 Modules and files
---------------------

Colocate a component's ``.js`` and ``.xml`` in a feature folder
(``static/src/<feature>/<component>.js`` + ``.xml``). ES6 imports only, no
``require()``.

.. code-block:: javascript

   import { Component } from "@odoo/owl";
   import { registry } from "@web/core/registry";
   import { _t } from "@web/core/translation";

``/** @odoo-module **/`` is a **routing directive for the asset bundler**, parsed
from the first 500 bytes of the file by ``odoo/tools/assets/esm_graph.py`` -- not
a cosmetic header. Files under ``static/src`` and ``static/tests`` are routed by
path, so the bare form is optional there. Write it explicitly for a modifier, or
for a file outside those paths:

* ``@odoo-module ignore`` -- keep the file out of the ESM pipeline (a classic
  script or vendored library).
* ``@odoo-module native`` -- treat as a true native ES module.
* ``@odoo-module alias=<specifier>`` -- register under an additional import path.
* ``@odoo-module default=<name>`` -- control default-export bridging.

Two asset mistakes take a whole page down while the HTTP response stays ``200``,
because the pipeline degrades rather than raises, and neither is caught by a
module's own test suite:

* **Every ``@addon/...`` import must resolve to a file**
  ``[test_lint test_esm_specifiers]``. esbuild fails the *entire bundle* on one
  unresolvable specifier, and a failed build is served as an empty one -- so a
  module moved inside ``web`` blanks the web client of every database carrying an
  addon that still imports the old path, including addons not installed. ADR-0023
  records the second half: a specifier that does not resolve in a *test* file
  registers no suite at all, so the run reports fewer tests rather than an error.
* **A bundle rendered by ``t-call-assets`` must be declared under the manifest's
  ``esm`` key if it carries ES-module sources** ``[test_lint test_esm_bundles]``.
  Undeclared, it is concatenated as legacy JS and every module-syntax file in it
  is replaced by a ``console.error`` stub, so the page boots into nothing. A
  bundle only ever ``('include', ...)``-ed into another needs no declaration.

Run both after any move, rename or new bundle -- about two seconds::

   odoo-bin -d <db> -i test_lint --test-enable --stop-after-init --no-http \
       --test-tags '/test_lint:TestEsmSpecifiers,/test_lint:TestEsmBundles'

Under ``--test-enable`` or ``--dev=assets`` a failed esbuild build **raises**
(``EsbuildBundleError``) instead of degrading to an empty bundle. A run that dies
naming a bundle is reporting the breakage that, in production, is a page loading
with no JavaScript. Fix the import or the declaration; do not ignore the bundle.
Escape hatch for a run that must survive a known-broken bundle:
``ir.config_parameter`` ``web.esbuild.fail_closed = 0``.

4.2 Naming
----------

* Components ``PascalCase``; methods and variables ``camelCase``.
* **When JS names a Python method, the string must match exactly.** An ORM call or
  a button ``name`` targeting ``action_view_invoices`` uses that name verbatim.
  This is about the call target, not about frontend handlers.
* Portal template ``t-name`` values follow the field naming conventions
  (``invoice_state``, not ``invoice_status``).

4.3 OWL
-------

4.3.1 Rules
~~~~~~~~~~~

* **``super.setup()`` first** when patching -- before anything else.
* **``useState`` for reactive state.** A plain assignment does not re-render.
* **Verify import paths.** Odoo moves components between releases; assume a
  recalled path is stale.
* **POS: ``t-inherit`` for markup, ``patch`` for behaviour.** Reserve
  ``onMounted`` DOM access for measurement and focus -- raw DOM injection breaks
  on re-render.

4.3.2 ``this`` in a template is not always the component
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

OWL renders against a *derived* context, not the component
(``addons/web/static/lib/owl/owl.es.js``)::

   const ctx = Object.assign(Object.create(this.component), { this: this.component });

Template expressions compile to lookups on ``ctx``. Because ``ctx`` only
*inherits* from the component, **reads** always resolve, but a **write** to a bare
instance property lands on ``ctx`` -- a per-render throwaway, invisible to the
component and gone on the next render.

.. list-table::
   :header-rows: 1

   * - Reference in the template
     - ``this`` inside the member
     - Bare ``this.x = …``
   * - ``this.foo()``
     - the component
     - safe
   * - ``t-on-click="foo"``
     - the component -- invoked as ``handler.call(node.component, ev)``
     - safe
   * - ``onFoo.bind="foo"``
     - the component
     - safe
   * - ``foo`` / ``foo.bar`` (bare getter or method)
     - the derived ``ctx``
     - **lost**

Only the last row is dangerous, and it fails silently:

* ``this.someObject.key = v`` is safe everywhere -- the *read* resolves through
  the prototype chain to the component's object and the mutation lands on it. Only
  rebinding the property itself (``this.counter = 1``) is lost.
* A member reached transitively binds like its entry point: a bare template getter
  calling ``this.helper()`` still runs ``helper`` on ``ctx``.

When a bare template member must persist something, mutate a container object
created in ``setup()`` -- see ``Many2XAutocomplete.emptySearchMemo``.

4.3.3 Patching
~~~~~~~~~~~~~~

.. code-block:: javascript

   import { patch } from "@web/core/utils/patch";
   import { useService } from "@web/core/utils/hooks";
   import { useState, onWillStart } from "@odoo/owl";

   patch(ProductCard.prototype, {
       setup() {
           super.setup(); // always first
           this.orm = useService("orm");
           this.customState = useState({ data: null });
           onWillStart(async () => {
               this.customState.data = await this.orm.call(
                   "product.product", "custom_read", [],
               );
           });
       },
   });

Choosing an approach:

.. code-block::

   Change the markup of an existing component?   -> t-inherit the template
   Change its behaviour?                          -> patch(Component.prototype, {...})
   New UI element?                                -> new OWL component + registry entry
   Unsure?                                        -> read reference/owl/ before guessing

4.4 Tests
---------

Frontend changes ship with a test ``[review]``. QUnit is removed -- do not write
it.

* **Unit and component tests -- Hoot.** ``static/tests/**/*.test.js``, importing
  from ``@odoo/hoot`` and ``@odoo/hoot-dom``, with the mock server for ORM calls.
  This is the default.

  .. code-block:: javascript

     import { expect, test } from "@odoo/hoot";
     import { click } from "@odoo/hoot-dom";

     test("counter increments on click", async () => {
         await click("button.increment");
         expect("span.value").toHaveText("1");
     });

* **Integration and end-to-end -- tours.** Register in the ``web_tour.tours``
  registry and drive from a Python ``HttpCase`` tagged
  ``@tagged("post_install", "-at_install")`` via
  ``self.start_tour(url, "tour_name", login=...)``. Use tours for flows spanning
  backend and UI.

Two operational facts about the Hoot runner:

* **The unit-test bundle is not rebuilt while the server runs** -- not for XML,
  not for a new ``.test.js``, not for a plain source edit. Restart the server after
  every change; a green run only proves the bundle you built.
* **An import failure reads as a lower pass count, never as a failure.** Read the
  import-failure line rather than trusting "Passed N".

JavaScript is also covered by the ESLint and ``tsc`` ratchets. Neither is expected
to be clean; neither may get worse.

----

5. CSS / SCSS
=============

5.1 Naming and organisation
---------------------------

* Module-prefixed classes: ``.o_module_name_element``.
* Files in ``static/src/scss/``, or colocated with the component they style.
* Declared in ``__manifest__.py`` under ``assets``, in the bundle that loads where
  the style is needed. Wrong-bundle CSS either does nothing or bloats every page.

.. list-table::
   :header-rows: 1

   * - Bundle
     - Loads in
   * - ``web.assets_backend``
     - backend web client -- most module UI
   * - ``web.assets_frontend``
     - website and portal
   * - ``point_of_sale._assets_pos``
     - Point of Sale client
   * - ``web.report_assets_common``
     - QWeb PDF reports
   * - ``web._assets_primary_variables``
     - SCSS variable **overrides**, loaded first; emits no rules

5.2 Theming
-----------

* **Bootstrap first.** The UI is Bootstrap 5 -- reuse its utilities and components
  before writing SCSS.
* **Override variables, not values.** Customise through Odoo and Bootstrap SCSS
  variables injected into ``web._assets_primary_variables`` (or
  ``_secondary_variables``). Never hard-code a colour or spacing a variable
  already controls.
* **Dark mode** is file-based: a ``*.dark.scss`` sibling is globbed automatically
  into ``web.assets_backend_dark`` / ``web.assets_web_dark``. Put dark overrides
  there and drive colours from variables.
* **RTL** is generated automatically. Use logical properties
  (``margin-inline-start``) and Odoo's RTL-aware mixins, not hard ``left`` /
  ``right``.

5.3 Browser floor
-----------------

**Current evergreen browsers. This fork does not support old ones, and no
declaration carries a fallback for them** ``[review]``. The JS floor is
``_ESBUILD_TARGET = "es2023"`` in ``odoo/tools/assets/esbuild.py``; the CSS floor
is stated here so authors stop guessing conservatively. Anything **Baseline newly
available** may be used directly, in every bundle, including the public ones:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Use
     - Instead of
   * - ``color-mix(in srgb, C N%, transparent)``
     - ``rgba($c, .N)`` -- Baseline *widely* available, the workhorse
   * - ``hsl(from C h s calc(l - 10))``
     - ``darken($c, 10%)`` -- reproduces the Sass value exactly, HSL for HSL
   * - ``light-dark(a, b)``
     - a one-off colour that differs by scheme and deserves no token name
   * - ``oklch(from C calc(l - .1) c h)``
     - a *deliberate* palette change: perceptually uniform, so a step looks the
       same on yellow as on blue. It does **not** reproduce ``darken()``

A Sass colour function resolves when the bundle compiles, which is why this fork
ships every stylesheet twice; the CSS equivalents resolve in the cascade, so one
stylesheet answers both colour schemes. ``test_lint``'s ``TestSchemeDuplication``
measures the distance still to go.

``contrast-color()`` is the exception, on semantics rather than support: it
returns only white or black, while ``o-scheme-contrast()`` picks among four
foregrounds. Contrast picks stay compile-time and published per scheme.

5.4 Moving a variable onto a token
----------------------------------

``o-token(--name, $fallback)`` turns a Sass assignment into a ``var()``, so the
value is decided in the cascade and one declaration answers both schemes. Two
things make a variable ineligible, and only the first announces itself
``[review]``:

* **It is read by Sass colour maths.** ``darken()``, ``mix()``, ``rgba()``,
  ``color-contrast()`` and friends take a colour, and a ``var()`` is not one.
  Sass raises ``$color: var(…) is not a color`` and the bundle fails to compile.
  Grep the whole workspace before converting -- ``$card-bg`` is read by
  ``color-contrast()`` from ``portal``, four addons away from where it is assigned.
* **It is interpolated into an SVG data URI.** ``$form-check-*-color`` reaches
  ``stroke='#{…}'`` inside ``url("data:image/svg+xml,…")``. A custom property
  there is inert: the URI is not CSS, so the ``var()`` neither resolves nor
  errors -- the compile succeeds and the icon simply stops being drawn, and
  nothing reports it. Convert the variable only alongside the image that reads it.

The same applies to a value handed to a mixin: ``o-button-variant-from()`` and
``o-print-color-rgb()`` accept tokens deliberately and say so, but a mixin written
for colours will fail on the first function it reaches.

5.5 Restating a rule for the other scheme
-----------------------------------------

Where neither a token nor ``light-dark()`` can carry a value -- a
``color-contrast()`` pick, a ``shift-color()``, a variable a colour function reads
-- the rule is restated under ``:root[data-color-scheme="dark"]``, which outscores
the plain rule (0,2,0) against (0,1,0). ``scheme_rules.scss`` and
``html_editor.scheme_rules.scss`` are where those live ``[review]``.

* **One rule per original rule, with its whole selector list.** Grouping three of
  Bootstrap's ``:focus`` rules into one scoped rule answers *none* of them, and
  ``.navbar-dark`` alone does not answer
  ``.navbar-dark,.navbar[data-bs-theme=dark]``. Copy the selector as the bundle
  emits it.
* **Only the dark half.** Whatever emits the light half already did so.
* **Screen only.** ``assets_web_print`` includes the backend bundle and is linked
  unconditionally, so an unscoped block answers the attribute in print.
* **Not where it cannot apply.** A file riding ``assets_frontend`` should not
  carry the dark half, since nothing there sets the attribute. Split it into a
  sibling declared in the backend bundle alone -- ``html_editor.scheme_rules.scss``
  exists because emitting it from the shared file put 24 KB on every public page.
* **Never call ``tint-color()`` or ``shade-color()`` from a scoped block.** The
  dark bundle carries ``bs_functions_overridden.dark.scss``, which redefines both
  -- in dark, tint mixes with *black* -- so calling Bootstrap's own function from
  a light bundle computes the light meaning of the word and the two bundles
  disagree about a colour they both call dark. Use ``o-scheme-tint(…, $-scheme)``
  / ``o-scheme-shade(…, $-scheme)``, which take the mix colour from the scheme.
* **``@extend`` does not compose with a scope** unless what the placeholder emits
  carries no colour, in which case the light half already answers and the dark
  half must omit it. See ``o-bg-color()``'s ``$extend-heading-reset``.

5.6 Weighing a conversion
-------------------------

**Weigh the bytes.** A ``var(--name, <fallback>)`` is longer than the colour it
replaces, once per use. Converting ``$focus-ring-color`` added 34 KB to every
backend bundle and answered nothing, because ``$focus-ring-box-shadow`` had
flattened the composed shadow into a string before the token reached it. Read the
compiled size alongside ``TestSchemeDuplication``'s count; a conversion that moves
neither is a conversion to drop.

----

6. Tests
========

6.0 Choosing a tier
-------------------

The framework ships three tiers. Pick the lightest one that can express the test;
§6.1 onwards concerns Tier 3, which is what most addon tests use.

.. list-table::
   :header-rows: 1
   :widths: 16 34 50

   * - Tier
     - Entry point
     - Use when
   * - **1 -- Component**
     - ``odoo/orm/components/tests/`` and the other ``pytest`` suites
     - Exercising ORM algorithms in isolation -- cache, compute scheduling, flush
       convergence, trigger graph -- against the real component objects. No
       fields, no ``@api.depends``, no ``odoo`` imports. Milliseconds.
   * - **2 -- ORM, database-free**
     - ``model_test_env`` / ``ModelRegistry`` (``odoo/orm/model_test_env.py``)
     - Real model methods, real ``@api.depends`` computes and real ``Field``
       descriptors against an in-memory backend. No PostgreSQL.
   * - **3 -- Integration**
     - ``TransactionCase`` / ``HttpCase``
     - Anything needing SQL, ACLs, several modules, or the web client.

Tier 1's hand-rolled dependency graph *is* the subject under test; not reusing
Tier 2's real ORM is intentional, not duplication.

Tiers 1 and 2 are plain ``pytest`` and need **two invocations** -- Tier 1
registers process-global ``sys.modules`` stubs that would shadow Tier 2's real
imports:

.. code-block:: bash

   cd <odoo repo>

   pytest                                          # Tier 1 (config: pytest.ini)
   pytest odoo/orm/tests odoo/http/tests tests/service   # Tier 2 — separate run

Pass **all three** Tier-2 paths. None is in Tier 1's ``testpaths``, so a shorter
command silently skips whole suites and still reports success.

Two further suites sit outside the tiers because they need real resources:

.. code-block:: bash

   pytest tests/contract   # needs PostgreSQL + psql/pg_dump on PATH; <1s
   pytest tests/process    # boots real odoo-bin processes; POSIX + PostgreSQL; ~20s

**Contract tests** pin the behaviour of our *dependencies* -- psycopg's exception
hierarchy, what ``pg_dump`` emits, how ``psql`` lexes a meta-command, whether
``Popen`` closes its pipes -- not our own logic. Every defect in the July 2026
service-layer audit was an assumption mismatch rather than a logic error: the
mocks were internally consistent and encoded the wrong external behaviour. Write
one whenever code branches on how a dependency behaves, and assert the dependency
directly, so a version bump fails in a test that *names the assumption*. The suite
skips when a dependency is missing, so a green local run may have compared
nothing; CI sets ``ODOO_CONTRACT_REQUIRE_DEPS=1``.

**Process tests** assert only what an outside observer can see: a listening port,
a process tree, an HTTP response. The suite is deliberately tiny -- the service
layer is covered far more cheaply by the mock-based suites in ``tests/service``.
Add one only for behaviour that emerges from real processes and vanishes the
moment anything is mocked. Two rules keep it from rotting:

* Assert on observables, never on internal state -- otherwise it is a slow unit
  test.
* **Readiness is a served request, never a log line.** ``ThreadedServer.run``
  spawns the WSGI server and logs "HTTP service (werkzeug) running" *before*
  ``preload_registries``, both under ``Registry._lock``, so the socket accepts and
  the log claims readiness while requests still block.

6.1 Layout and base classes
---------------------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Base class
     - Use for
   * - ``TransactionCase``
     - standard ORM tests; each method runs in its own rolled-back transaction
   * - ``SingleTransactionCase``
     - tests deliberately sharing state across methods
   * - ``HttpCase``
     - controllers, web UI, headless Chrome; tag
       ``@tagged("post_install", "-at_install")``

Tests live in ``tests/``, one file per feature, and **every file must be imported
exactly once from ``tests/__init__.py``** ``[test_lint test_test_holes]``. A file
that is never imported never runs and reports nothing, hence a hard gate.

.. code-block::

   tests/
     __init__.py          # from . import test_sale_order, test_sale_order_line
     test_sale_order.py
     test_sale_order_line.py

Naming: files ``test_<feature>.py``, classes ``TestFeatureName``, methods
``test_<specific_scenario>``.

6.2 Isolation
-------------

* **Create records in ``setUpClass()``** -- it runs once per class, not once per
  method. Use ``setUp()`` only when a method genuinely mutates shared state.
* **Freeze time.** ``datetime.now()`` makes tests flaky; use
  ``odoo.tests.freeze_time``.
* **Mock external services.** Tests run offline.
* **Test with minimal permissions** -- a user in only the group under test
  surfaces access-rule bugs early. ``@users("demo")`` covers multi-user cases.
* **Never call ``cr.commit()``.** Test data lives in the test transaction and is
  rolled back; a commit permanently pollutes the database. The one exception is a
  concurrency or cron test that deliberately opens ``self.registry.cursor()``.
* A test class is **either ``at_install`` or ``post_install``**, never both and
  never neither ``[review]``. Pure ORM tests are ``at_install``; anything touching
  other modules, the web client or tours is ``post_install``. ``@tagged`` only
  *warns* on a violation and the run proceeds, so a class tagged both ways is
  caught by review or not at all.

.. code-block:: python

   @classmethod
   def setUpClass(cls):
       super().setUpClass()
       cls.partner = cls.env["res.partner"].create({"name": "Test Partner"})

6.3 ``BaseCommon``
------------------

``odoo.addons.base.tests.common.BaseCommon`` gives a quiet environment with mail
and tracking disabled. Not the default -- most tests still use ``TransactionCase``
-- but the right base class when mail noise is irrelevant.

It provides ``DISABLED_MAIL_CONTEXT``; pre-built ``cls.company``, ``cls.currency``,
``cls.partner``; the groups ``cls.group_user`` / ``cls.group_portal`` /
``cls.group_system``; and the helpers ``quick_ref(xmlid)``, ``_create_partner()``,
``_create_new_internal_user()``, ``_create_new_portal_user()``. It does **not**
create an independent user or company by default -- ``setup_independent_user`` and
``setup_independent_company`` return ``None`` unless a subclass overrides them.

6.4 Structure and completeness
------------------------------

Structure each test as setup → action → assertion, separated by blank lines.

.. code-block:: python

   def test_order_confirmation_sets_date(self):
       order = self.env["sale.order"].create({
           "partner_id": self.partner.id,
           "order_line": [Command.create({"product_id": self.product.id})],
       })

       order.action_confirm()

       self.assertEqual(order.state, "sale")
       self.assertTrue(order.date_order)

* Use specific assertions (``assertEqual``, ``assertIn``, ``assertRaises``) rather
  than bare ``assertTrue`` / ``assertFalse``.
* **Negative tests are mandatory** ``[review]``: every test class covers at least
  one expected-failure path -- a constraint raising ``ValidationError``, an
  unauthorised user getting ``AccessError``, an invalid state transition refused.
* **Parameterise with ``subTest()``**, so one failing case does not mask the rest:

  .. code-block:: python

     for amount, rate, expected in cases:
         with self.subTest(amount=amount, rate=rate):
             self.assertAlmostEqual(
                 self.env["account.tax"]._compute_amount(amount, rate), expected, places=2,
             )

* Use the ``Form`` simulator (``from odoo.tests import Form``) to test onchange
  behaviour without HTTP.
* **Lock hot paths with ``assertQueryCount``.** ``@warmup`` primes caches first.
* **A moved count is a question, not a verdict** ``[review]``. A count changes
  when the work *moves* as readily as when it grows, and only the stack of the
  extra calls tells those apart: a pin asserting *exactly* one QWeb compile per
  batch reads **0** once the compiled template outlives the call, which is a fix
  landing rather than a regression. **Get the stack before moving a pin**, then
  move it and say in the commit what each unit bought.
* **Pin the guarantee, not the arithmetic** ``[review]``. Assert a bound, then
  assert the mechanism. ``assertEqual(compiles, 1)`` breaks the day caching
  improves it to zero; ``assertLessEqual(compiles, 1)`` followed by a second
  render asserting zero says *compiled once, never again*. **Both halves are
  required: a bound alone is satisfied by the work not happening at all.**

6.5 Raw SQL in tests
--------------------

The ORM defers writes, so flush before asserting on database state:

.. code-block:: python

   self.order.write({"state": "sale"})
   self.order.flush_recordset(["state"])
   self.env.cr.execute("SELECT state FROM sale_order WHERE id = %s", (self.order.id,))
   self.assertEqual(self.env.cr.fetchone()[0], "sale")

6.6 Lint relaxations in tests
-----------------------------

``**/tests/**`` suppresses these ``ruff`` rules; keep the list in sync with
``ruff.toml``: ``B017`` (broad ``assertRaises``), ``RUF015``, ``PLW0603``
(fixtures), ``T201`` (``print``), ``PLR6201``, ``S110``, ``S113`` (HTTP without
timeout), ``TRY002``, ``TRY203``, ``EM101``, ``PLR0124`` (self-comparison),
``A001`` / ``A002`` (builtin shadowing), and ``RUF069`` -- exact float assertions
of deterministic values are legitimate in a test.

``D`` and ``ANN`` are also exempt inside ``odoo/libs/`` and
``odoo/orm/components/`` tests.

6.7 Tagging
-----------

* Default: ``standard`` + ``at_install``.
* ``HttpCase``: ``@tagged("post_install", "-at_install")``.
* Slow or external tests excluded from the standard run: ``@tagged("-standard")``,
  optionally with a real selector tag such as ``external`` or ``nightly``. There
  is no ``heavy`` tag -- do not invent one.
* **Localisation tests** carry exactly one of ``post_install_l10n`` or
  ``external_l10n``, each paired with its base tag ``[test_lint test_l10n]``.
* **JS (HOOT) tests** carry ``desktop``, ``mobile`` or ``headless`` -- via
  ``test.tags(...)`` or a file-level ``describe.current.tags(...)`` ``[review]``.
  A test that mounts nothing and imports no ``@odoo/hoot-dom`` is ``headless``;
  one that branches on viewport or touch is ``desktop`` or ``mobile``. Leaving a
  test untagged is not neutral: it runs in *both* passes, so a DOM-free test pays
  a second run at 375x667 that can only repeat the first. ``headless`` still runs
  in the desktop pass -- it means DOM-free, not "no browser".

6.8 Coverage
------------

Aim above **80%** on custom modules -- aspirational, not gated. Cover edge cases,
constraints and validations, and give every ``action_*`` method at least one test.

.. code-block:: bash

   # a module's tests, during (re)install
   odoo-bin -d <db> -i <module> --test-enable --test-tags /<module> --stop-after-init

   # one class or method
   odoo-bin -d <db> --test-enable --test-tags /<module>:TestClass.test_method --stop-after-init

   # the post_install (HttpCase / tour) phase
   odoo-bin -d <db> -i <module> --test-enable --test-tags post_install --stop-after-init

   # coverage
   coverage run odoo-bin -d <db> -i <module> --test-enable --test-tags /<module> --stop-after-init
   coverage report

Two traps. Redirecting server output with ``>`` drops and reorders lines (Odoo
writes from several file descriptors without ``O_APPEND``) -- use ``>>``, ``tee``
or ``--logfile``, and gate on the exit code plus the ``N failed, M error(s)``
summary. And stopping a background run kills only the shell: ``odoo-bin`` survives
and keeps holding its HTTP port.

6.9 Pre-existing failures
-------------------------

**Do not re-run a suite to find out whether a red test was already red.** Diff the
run against its recorded failure set instead ``[review]``:

.. code-block:: bash

   odoo-bin -d <db> -i <module> --test-enable --test-tags /<module> \
       --stop-after-init --logfile run.log
   tooling/testbaseline/testbaseline.py /<module> run.log

``0 new, 0 newly-passing`` means nothing in the run is attributable to your change.
A newly-passing test is reported too, and is banked with ``--update`` in the commit
that fixed it -- the same one-way discipline the ratchets apply to counts, for the
same reason: a win nobody records is one that silently reverts.

Two rules the tool exists to enforce, both measured rather than assumed:

- **Never count failures by grepping for** ``ERROR``. PostgreSQL error text is
  embedded verbatim in log records of *passing* tests, so a test that provokes a
  bad ``COPY`` contributes a line reading ``ERROR: ...``. Measured on the ``/base``
  log taken at ``ca4ee2ddd79`` on 2026-08-22, that grep answers 14 and the truth is
  3 -- a frozen reading of one run, not a tree census. Anchor on the structured record
  ``<ts> <pid> ERROR uid:... <logger>: FAIL|ERROR: <Class.method>``, or on the
  server's own ``N failed, M error(s) of T tests`` summary.
- **Diff failure names, never counts.** ``quality_control`` held at two failures
  across a day in which one recorded test was fixed and an unrecorded one broke.
  A matching count reads as "both known" and ships the regression.

A suite with no baseline gets no verdict rather than a guess. ``tooling/testbaseline/README.md``
carries the measurement behind each choice.

----

7. Git
======

7.1 Commits
-----------

Subject line ``[TAG] module: description`` -- aim for 50 characters, hard cap 72,
and keep it shorter than the PR title.

``module`` is a single module (``account_cfdi``, or with a sub-path such as
``stock/routes``), a comma-separated list when the change genuinely spans several
(``[FIX] sale,purchase: ...``), or ``*`` for a tree-wide change. Prefer ``*`` over
an unreadable list.

**Thirteen tags, no others.** The first seven are upstream Odoo's; the rest are
AgroMarin additions.

.. list-table::
   :header-rows: 1

   * - Tag
     - Use for
   * - ``FIX``
     - bug fix
   * - ``IMP``
     - improvement to existing functionality
   * - ``ADD``
     - new module or feature
   * - ``REM``
     - removal of code, files or resources
   * - ``REF``
     - refactor, no behaviour change
   * - ``MOV``
     - file relocation (use ``git mv``)
   * - ``REV``
     - revert
   * - ``REL``
     - release / version bump
   * - ``MERGE``
     - merge commit
   * - ``I18N``
     - translation update
   * - ``PERF``
     - performance optimisation
   * - ``CLN``
     - cleanup, no functional change -- stricter than ``REF``
   * - ``LINT``
     - linting or formatting only

One primary tag per commit, chosen by dominant intent; if a change has two
intents, split it. ``LINT`` and ``CLN`` must contain no behaviour change -- if
they do, the tag is ``REF``.

.. code-block::

   [IMP] product_asset: filter Fleet views by fuel card

   Fleet and Fleet Service Logs showed all assets regardless of fuel card
   assignment, making the views noisy for operators.

   Solution:
   - Add domain filter on fuel_card_id to the Fleet list view
   - Apply the same filter to Fleet Service Logs

   Task ID: 17012

The ``Solution:`` block is mandatory. The ``Task ID`` line is **optional**: name
the task whenever the change has one, and leave the line out when it does not.
Never invent one, and never write ``Task ID: N/A``.

**Name files in a pathspec, never a directory** ``[review]``. ``git commit --
<path>`` records the *working tree* at that path, deletions included, and a
directory pathspec sweeps in every deletion under it:

.. code-block::

   rm research/note.md              # missing from the working tree

   git commit -m A -- research/keep.md    # note.md survives
   git commit -m B -- research            # note.md deleted, unmentioned

Branch B is how a 567-line note was removed by a commit whose message described
only an edit to its sibling. Name the files, and read ``git status`` for ``D``
lines before committing.

7.2 Branches and task IDs
-------------------------

Feature branches are ``<odoo_version>-t<task_id>-<github_username>``, e.g.
``19.0-t17352-suniagajose``, whenever the work has a task behind it. The task ID
on the branch and its commits is what traces a code change to a business
requirement.

Neither is required. Work with no task -- a hotfix, a chore, a guideline edit --
may be committed directly to the integration branch under a descriptive subject.
That is a normal outcome, not an exception to argue for afterwards.

7.3 Pull requests
-----------------

A PR is the default route and the only one that gets review, but it is **not
required**: a production hotfix, a small correction, or work its author owns end
to end may go straight to a shared branch. The knowledge repository works directly
on ``main`` in every case.

**Title**: ``[TAG] module: short description``, under 70 characters. For a
single-commit PR it mirrors the commit subject; for a change spanning modules, use
the dominant functional scope rather than a module list.

**Body**:

.. code-block:: markdown

   # [Task ID: XXXXX](https://$DOMAIN/odoo/project.task/XXXXX)

   ## Problem
   One to three sentences on what the user or system was experiencing.

   ## Solution
   - One bullet per logical unit of change, not per file

   ## Verification
   - Commands run, manual steps, or a checklist
   - `EXPLAIN ANALYZE` output for any new raw SQL (§11.6)
   - Screenshot or GIF for UI changes

Required:

* At least one commit per logical unit -- do not squash unrelated changes.
* No merge commits from the base branch in the PR history; rebase instead.
* No force-push to a **shared** branch (``main``, ``19.0``, ``19.0-marin``,
  ``19.0-dev``). Force-push is expected on your own feature branch.

Optional: the task-ID heading, as a **hyperlink** rather than plain text. Drop the
heading entirely when there is no task; do not leave ``XXXXX`` standing, and do
not write ``N/A``.

PRs land by **rebase merge**, which rewrites every SHA. Afterwards a local branch
reads "N ahead, N behind"; that is cosmetic. Confirm with
``git diff <local> origin/<branch>`` (empty means identical trees), then
``git reset --keep origin/<branch>`` -- ``--keep``, never ``--hard``: it preserves
uncommitted work and aborts rather than clobbering it.

Branch model: ``19.0`` is a pristine upstream mirror and never receives AgroMarin
work; ``19.0-marin`` is the integration branch; feature branches cut from and
merge back into it. The same model applies to the fork's other upstream mirror.

----

8. Translations
===============

8.1 Python
----------

Use ``self.env._()``. The legacy ``_()`` walks back up the call stack with
``inspect.currentframe()`` to infer the language and the calling module, which is
both slower and wrong where the frame above is not the one you think --
decorators, comprehensions, callbacks.

.. code-block:: python

   message = self.env._("Order confirmed successfully")
   raise UserError(self.env._("Order %s cannot be confirmed.", order.name))

Four rules, all enforced by ``_checker_gettext``, which recognises both ``_()``
and ``self.env._()``:

* **The first argument is a literal string** ``[test_lint E8502]``. A variable
  defeats extraction -- there is nothing for the exporter to find.
* **Two or more placeholders must be named** ``[test_lint E8503]``. With
  ``"%s of %s"`` a translator cannot reorder the arguments; write
  ``self.env._("%(done)s of %(total)s", done=x, total=y)``.
* **No ``%r``** ``[test_lint E8504]``. Its output is a Python repr, neither
  translatable nor meaningful to a user.
* **User-facing exceptions take a translated message** ``[test_lint E8505]``, not
  a bare literal (§2.7).

``ruff``'s ``INT`` rules match only the bare ``_()`` form, so ``test_lint`` is
what actually covers the form this guide mandates.

For constants declared outside a method, use ``LazyTranslate``:

.. code-block:: python

   from odoo.tools import LazyTranslate

   _lt = LazyTranslate(__name__)
   STATES = [("draft", _lt("Draft")), ("done", _lt("Done"))]

8.2 JavaScript and templates
----------------------------

.. code-block:: javascript

   import { _t } from "@web/core/translation";

   const message = _t("Operation completed");

Static string props on OWL components are extracted automatically
``[test_lint test_i18n, test_jstranslate]`` -- which means a user-facing string
assembled at runtime silently escapes translation. Keep literals literal.

A module with JS translations must register itself:

.. code-block:: python

   class IrHttp(models.AbstractModel):
       _inherit = "ir.http"

       @classmethod
       def _get_translation_frontend_modules_name(cls):
           return super()._get_translation_frontend_modules_name() + ["my_module"]

8.3 ``.pot`` / ``.po``
----------------------

Keep the template at ``i18n/<module>.pot`` and language files at
``i18n/<lang>.po``. Re-export after changing user-facing strings -- **including
deleting one**, or the template keeps advertising a message that no longer exists:

.. code-block:: bash

   odoo-bin --addons-path=odoo/addons,addons i18n export -d <db> <module>

Export through the **community trees only**. The header records
``odoo.release.version``, which an enterprise addons path turns into
``Odoo Server 19.0+e``, writing a fact about your checkout into the template.

Never hand-edit a ``msgid`` to "fix" the English -- change the source string and
re-export. Duplicate entries in a ``.pot`` are a failure
``[test_lint test_pofile]``. Translations round-trip through Weblate
(``.weblate.json``); do not commit machine-merged ``.po`` churn that fights it.

----

9. Code review checklist
========================

What tooling cannot check. Do not re-verify lint codes by hand; skip an item that
does not apply, with a note.

**Security**

#. Dynamic SQL is parameterised or wrapped in ``SQL()`` -- including identifiers
   built from ORM metadata.
#. ``sudo()`` writes of user-submitted payloads whitelist the allowed fields.
#. Related fields reaching sensitive models (``ir.attachment``, ``hr.payslip``)
   have explicit access control (§10.5).
#. Every public method is *intentionally* an RPC endpoint.
#. Security validation uses ``if … raise``, never ``assert``.
#. Handlers expose no tracebacks or SQL fragments to users.
#. State-mutation code fails closed -- partial operations sit inside a savepoint.
#. No hard-coded URLs, credentials or service endpoints.

**Correctness**

#. No query call inside a loop over a recordset.
#. Computes assign fields directly; they never call ``write()``.
#. CRUD overrides call ``super()``; ``create`` uses ``@api.model_create_multi``.
#. ``@api.depends`` lists every sub-field the body reads --
   ``"partner_id.country_id"``, not ``"partner_id"`` (§11.4).
#. Every ``Monetary`` field has a currency field on the same model.
#. Error types match intent: ``UserError`` for business rules,
   ``ValidationError`` inside constraints, ``MissingError`` for deleted records.
#. ``.exists()`` is called where another transaction may have deleted the record.
#. Overridden framework methods carry ``@typing.override``.

**Performance**

#. Counts use ``search_count()``; aggregation uses ``_read_group()``.
#. No ``cr.commit()`` outside ``_commit_progress()``.
#. Crons batch with ``itertools.batched`` and ``_commit_progress()``.
#. Locking uses ``NOWAIT`` or ``SKIP LOCKED`` -- no unbounded waits.
#. New raw SQL ships ``EXPLAIN ANALYZE`` output in the PR description.
#. State-filtered tables use partial or expression indexes where they pay.

**Tests**

#. At least one negative test per test class.
#. No ``cr.commit()`` in tests.
#. Parameterised scenarios use ``subTest()``.
#. New test files are imported in ``tests/__init__.py``.

**Style**

#. External HTTP calls pass a ``timeout``.
#. Company and user come from ``self.env.company`` / ``self.env.user``.
#. Context is read with ``self.env.context.get()``, not direct indexing.
#. Methods stay under roughly 40 lines; longer logic is extracted.
#. Comprehensions use at most one ``for`` and one ``if``.
#. New code matches ``ruff format``'s style without reformatting the rest of the
   file (§2.1).

On complexity: ``max-complexity = 20`` is configured under ``[lint.mccabe]``, but
``C901`` sits in ``ruff.toml``'s ignore list on the deliberate grounds that Odoo's
ORM and QWeb methods are irreducibly branchy -- the ``c901`` ratchet re-selects it
on the CLI. Complexity is a review judgement in-file. Do not "fix" the config
without reversing that decision explicitly.

----

10. Security
============

10.1 Method visibility
----------------------

A public method -- no leading underscore -- is callable over XML-RPC and JSON-RPC
by any authenticated user. ACL checks happen during CRUD operations only; a custom
public method enforces nothing on its own.

* **Default every method to private.** Remove the underscore only after deliberate
  review.
* ``@api.private`` blocks RPC on a method that must keep a public *name*. It is
  enforced at the RPC boundary across the whole MRO, so a subclass cannot
  re-expose it. Use ``_`` for new code and ``@api.private`` to retrofit.

10.2 ``sudo()``
---------------

* **Prefer narrower escalation.** ``with_user(user)`` and ``with_company(company)``
  keep ACLs and record rules *enforced* under a different identity. Reserve
  ``sudo()`` for genuine cross-tenant or system operations.
* **Whitelist fields** when writing a user-submitted payload. A ``sudo()`` read of
  one field is low-risk; ``sudo().write(payload)`` is the dangerous shape.
* **Minimise scope** -- smallest recordset, fewest operations.

.. code-block:: python

   def action_update(self, values):
       allowed = {"description", "tag_ids"}
       self.sudo().write({k: v for k, v in values.items() if k in allowed})

10.3 Input validation
---------------------

``assert`` is stripped under ``python -O``. Any validation guarding
security-sensitive logic uses ``if`` / ``raise`` ``[review]``; ``ruff``'s ``S101``
is disabled, because Odoo uses ``assert`` for ORM invariants, so the linter will
not catch a security ``assert``.

.. code-block:: python

   if access_mode not in ("read", "write", "create", "unlink"):
       raise ValueError(f"Invalid access mode: {access_mode!r}")

10.4 SQL injection
------------------

**All dynamic SQL uses parameters or the ``SQL`` wrapper** ``[test_lint E8501]``.
f-strings, ``.format()`` and ``%`` on a query string are violations even when the
value comes from ORM metadata such as ``_table`` or ``field.name``.

.. code-block:: python

   from odoo.tools import SQL

   self.env.cr.execute("SELECT id FROM res_partner WHERE name = %s", (name,))

   self.env.cr.execute(SQL(
       "SELECT id FROM %s WHERE %s = %s",
       SQL.identifier(model._table),
       SQL.identifier(field.name),
       value,
   ))

``ruff``'s ``S608`` is disabled because the ORM legitimately builds SQL through
the ``SQL()`` wrapper. The ``test_lint`` checker covers this: it tracks constant
propagation across assignments and function boundaries, and treats
underscore-prefixed attributes such as ``self._table`` as trusted.

10.5 Related fields and ACLs
----------------------------

**Related fields default to ``compute_sudo=True``**, so a related field traversing
into a sensitive model is read as superuser and **bypasses the reader's ACLs and
record rules**. (Plain computed fields default to ``compute_sudo = store`` -- sudo
only when stored.) Do not reason from the field type; pick one of:

* set ``compute_sudo=False`` explicitly on that field, or
* restrict it with ``groups="..."``, or
* replace the related field with an explicit, ACL-respecting compute.

10.6 Controllers
----------------

* ``auth="public"`` runs as the Public user -- unauthenticated visitors reach it.
  Validate and sanitise every parameter, schema-validate the payload, and
  rate-limit the endpoint.
* ``auth="none"`` means no database access; it is mainly for framework use.
* ``auth="bearer"`` tokens must be scoped and validated, and never logged.
* Use ``Markup()`` for intentional HTML and escape user content. Never interpolate
  user input into ``Markup()`` with an f-string -- that is an XSS hole.
* Do not set ``csrf=False`` on a ``type="http"`` POST route without a written
  justification. ``jsonrpc`` is CSRF-exempt by design.

10.7 Constraints run privileged
-------------------------------

**A deliberate fork deviation.** ``@api.constrains`` methods run as ``sudo()`` by
default, like stored computed fields. Consequences:

* Reads inside a constraint never raise ``AccessError``, and any write it performs
  executes privileged -- hold constraint bodies to the same discipline as explicit
  ``sudo()`` code (§10.2).
* Opt back into user-aware validation with ``@api.constrains(..., sudo=False)``
  when the check must see the current user's view of the data.
* A callable spec (``@api.constrains(lambda self: ...)``) is resolved once per
  registry class and memoised, so an env-dependent field list is frozen at its
  first evaluation.

10.8 Access control
-------------------

Every new model ships explicit access rules ``[review]``. A model with no
``ir.model.access`` line is inaccessible -- or worse, silently admin-only.

* **ACLs** are table-level, in ``security/ir.model.access.csv``: one line per
  (model, group) with ``perm_read,perm_write,perm_create,perm_unlink``. Grant the
  minimum -- typically ``1,1,1,0`` for a user group and ``1,1,1,1`` for a manager
  group. Avoid group-less global lines.
* **Record rules** (``ir.rule``) are row-level: use them when access depends on
  the record's data -- owner, company, state. A rule with no groups applies to
  everyone.
* **Multi-company** rules use ``[("company_id", "in", company_ids + [False])]`` so
  company-less shared records stay visible. Pair with ``check_company=True`` on
  relational fields (§2.9.10).
* Restrict sensitive **fields** with ``groups="module.group_xxx"`` -- enforced on
  both read and write.

10.9 Configuration and secrets
------------------------------

* **No hard-coded URLs, credentials or endpoints.** Use ``ir.config_parameter``,
  environment variables, or ``odoo.conf``.
* **Namespace** config keys as ``<module>.<setting>``; read them with
  ``self.env["ir.config_parameter"].sudo().get_param(key, default)``.
* ``ir.config_parameter`` values are readable by ``base.group_system``. For true
  secrets -- API keys, tokens -- prefer environment variables or ``odoo.conf``
  over the database.
* External dependencies are declared in ``__manifest__.py`` *and* pinned in
  ``requirements.txt`` (§1.2).

10.10 Deployment checklist
--------------------------

* ``--dev`` disabled; ``list_db = False``; ``admin_passwd`` changed from the
  default.
* ``proxy_mode = True`` behind a reverse proxy, with ``http_interface`` bound to
  localhost so only the proxy is public.
* ``dbfilter`` set; ``server_wide_modules`` minimal (the 19.0 default is
  ``base,rpc,web``).
* ``workers > 0``, with ``limit_time_cpu`` / ``limit_time_real`` /
  ``limit_memory_soft`` / ``limit_memory_hard`` / ``limit_request`` tuned.
* ``db_sslmode = require`` or ``verify-full`` -- the default ``prefer`` does
  **not** enforce TLS to PostgreSQL.
* ``gevent_port`` set for websockets and longpolling (``longpolling_port`` was
  removed); ``x_sendfile = True`` behind nginx or Apache; ``data_dir`` on a
  persistent, backed-up volume.
* Python dependencies pinned with hashes; ``pip-audit`` in CI.

----

11. Performance
===============

11.1 N+1 queries
----------------

A ``search()``, ``search_count()``, ``search_fetch()`` or ``_read_group()`` call
inside a ``for`` loop over a recordset is a violation ``[test_lint E8507]``. The
checker is advisory today -- it logs at WARNING rather than failing. Treat a
warning as a finding, not as noise.

Aggregate outside the loop and index the result:

.. code-block:: python

   groups = self.env["child.model"]._read_group(
       [("parent_id", "in", records.ids)],
       groupby=["parent_id"],
       aggregates=["__count"],
   )
   count_map = {parent.id: count for parent, count in groups}
   for record in records:
       record.child_count = count_map.get(record.id, 0)

The same shape replaces nested loops:

.. code-block:: python

   lines_by_order = defaultdict(list)
   for line in all_lines:
       lines_by_order[line.order_id.id].append(line)
   for order in orders:
       for line in lines_by_order[order.id]:
           ...

11.2 Batching and aggregation
-----------------------------

.. list-table::
   :header-rows: 1

   * - Need
     - Use
     - Not
   * - Count
     - ``search_count(domain)``
     - ``len(search(domain))``
   * - Count an x2many
     - ``fields.Count("line_ids")``
     - a compute that spells ``len(record.line_ids)``
   * - Existence
     - ``bool(search(domain, limit=1))``
     - ``search_count(domain) > 0``
   * - Aggregate
     - ``_read_group(domain, aggregates=["x:sum"])``
     - ``sum(r.x for r in search(...))``
   * - Create many
     - ``create([vals1, vals2, ...])``
     - ``create(vals)`` in a loop
   * - Update many
     - ``write()`` on the whole recordset
     - iterate and write per record
   * - Load and read
     - ``search_fetch(domain, fields, limit=...)``
     - ``search(...)`` then attribute access
   * - Dicts, not records
     - ``search_read()``
     - ``search()`` + ``read()``

``search()`` instantiates every match in Python; ``search_count()`` is a
``SELECT COUNT(*)``. For aggregation, note the double unpack -- a group-less
``_read_group`` returns ``[(value,)]``:

.. code-block:: python

   [[total]] = self.env["account.move.line"]._read_group(domain, aggregates=["amount:sum"])

``search_fetch()`` returns a real recordset with the named fields pre-loaded,
unlike ``search_read()``, which returns dicts.

``len(record.line_ids)`` is the counting mistake that does not look like one: it
costs one query, not N, so it reads as batched, but ``One2many.read`` runs a
``search_fetch`` over the whole prefetch set and instantiates every line. On a
list-view page it is the slowest of the three, ``search_count()`` in a loop
included. **Do not convert one to ``_read_group`` by hand** -- on a form view,
where the lines have been read anyway, ``len()`` is the fastest of the three, and
a new record's lines are in cache and in no table. ``fields.Count("line_ids")``
takes that branch per call. Measurements: ADR-0052.

Iterating a recordset prefetches for the whole set, which is usually what you
want. For a large set processed one record at a time, ``with_prefetch([])`` stops
the ORM pulling every sibling's fields into memory.

11.3 ``ormcache``
-----------------

Use ``@ormcache`` for read-heavy, rarely-changing data: model metadata, parsed
views, ACL lookups, configuration values.

.. code-block:: python

   from odoo.tools import ormcache

   @ormcache("self.env.uid", "model_name")
   def _get_access_rights(self, model_name):
       """Return an access-rights mapping. Must not return recordsets."""
       ...

**Cached methods must never return recordsets.** The cursor that built the
recordset is closed by the time of a later call, and the result raises
``InterfaceError``. Return plain Python values.

The ORM invalidates automatically through ``modified()``;
``self.env.registry.clear_cache()`` clears everything.

11.4 Computed fields
--------------------

* ``store=True`` only when the field is searched, ordered or grouped on.
  Non-stored computes avoid recomputation on every write.
* **Every sub-field the body reads must appear in ``@api.depends``** ``[review]``.
  Incomplete chains cause silent stale data: if the method reads
  ``record.partner_id.country_id``, then ``"partner_id.country_id"`` must be
  listed -- ``"partner_id"`` alone is not enough.

  .. code-block:: python

     @api.depends("partner_id.country_id")
     def _compute_country(self):
         for rec in self:
             rec.country_id = rec.partner_id.country_id

* **Exception -- initialisation-only computes.** When a
  ``store=True, readonly=False`` compute exists to seed an initial value, a coarse
  ``"parent_id"`` dependency is deliberate: the precise ``"parent_id.lang"`` would
  recompute and overwrite the user's edit whenever the parent changed. Fields
  whose ``inverse`` writes back along the same path need the same coarsening to
  avoid a trigger cycle.
* Avoid long chains of stored computes depending on each other; flatten where you
  can.

11.5 Indexing
-------------

* ``index=True`` on fields used in search domains, ``ORDER BY`` or ``GROUP BY``.
* **The stored inverse Many2one of a One2many must be indexed**
  ``[test_lint test_index]``. Without it, every traversal of the One2many is a
  sequential scan of the child table. Genuine exceptions go in the checker's
  allow-list with a reason, not into a bare ``index=False``.
* Every index costs write and create time -- beyond the rule above, index
  selectively, driven by measurement.
* ``models.Index()`` takes a raw definition, which is how composite, partial and
  expression indexes are declared:

  .. code-block:: python

     _account_date_idx = models.Index("(account_id, date)")
     _state_date_idx = models.Index("(date_order) WHERE state != 'done'")
     _name_upper_idx = models.Index("(UPPER(name))")

* A **partial** index is the right default where queries always filter on a state.
  An **expression** index avoids a full scan for case-insensitive lookups. Other
  access methods are available through the same raw form -- ``USING gin`` is in
  use in the tree, and ``USING brin`` suits append-only time-series tables.
  Neither is a default; justify one with a query plan.

11.6 Raw SQL
------------

Any raw ``cr.execute()`` added in a PR ships ``EXPLAIN ANALYZE`` output in the
description, showing the plan uses the indexes you expect ``[review]``.

The ORM defers writes, so bracket raw SQL accordingly:

.. code-block:: python

   self.flush_model()          # push pending values to the database
   self.env.cr.execute(...)
   self.invalidate_model()     # drop the cache after writing behind the ORM's back

11.7 Cron batching
------------------

Scheduled actions over large recordsets batch with progress reporting. Do **not**
call ``cr.commit()`` -- ``_commit_progress`` commits for you and tells you how
much time is left.

.. code-block:: python

   from itertools import batched

   def _cron_process_orders(self):
       orders = self.env["sale.order"].search([("state", "=", "pending")])
       commit_progress = self.env["ir.cron"]._commit_progress
       commit_progress(0, remaining=len(orders))          # set the total once
       for batch_ids in batched(orders.ids, 100):
           orders.browse(batch_ids)._process()
           time_left = commit_progress(processed=100)     # framework decrements remaining
           if not time_left:                              # budget exhausted; it reschedules
               break

* Batch 100--1000 records to bound memory and lock duration. ``split_every`` is
  deprecated; use ``itertools.batched``.
* ``_commit_progress(processed=0, *, remaining=None, deactivate=False)`` --
  ``remaining`` is **keyword-only**. It returns the **remaining cron time in
  seconds** (``inf`` outside a cron, ``0`` at the deadline), not a record count.
  Set ``remaining`` once; afterwards pass only ``processed``.
* Pass ``deactivate=True`` on the final call of a one-shot cron.

11.8 Locking
------------

.. code-block:: python

   # fail immediately if another transaction holds the lock
   self.env.cr.execute(SQL(
       "SELECT id FROM %s WHERE id = %s FOR UPDATE NOWAIT",
       SQL.identifier(self._table), self.id,
   ))

   # skip locked rows — job queues, cron dispatch
   self.env.cr.execute(SQL(
       "SELECT id FROM %s WHERE state = %s FOR UPDATE SKIP LOCKED",
       SQL.identifier(self._table), "pending",
   ))

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - Mode
     - Use for
   * - ``FOR UPDATE NOWAIT``
     - critical sections -- sequences, payment processing. Raises
       ``OperationalError`` when locked; always handle it.
   * - ``FOR UPDATE SKIP LOCKED``
     - job queues and cron dispatch; silently skips locked rows
   * - ``FOR NO KEY UPDATE``
     - updates that do not touch foreign-key columns

Lock, operate and commit as fast as possible. Prefer an ORM ``search()`` with a
domain over a table-level lock.

----

12. Migration Scripts
=====================

12.1 Layout
-----------

.. code-block::

   migrations/
     19.0.1.1.0/
       pre-migrate.py
       post-migrate.py

The directory name matches the module ``version`` in ``__manifest__.py`` that
introduces the change. Both forms work: the bare module version (``1.2.0``, the
common case) or the full ``19.0.1.2.0`` -- Odoo prefixes a bare version with the
server major at load time. The special ``0.0.0`` directory runs on **every**
update: first in the ``pre`` stage, last in ``post`` and ``end``.

Scripts are matched on the **stage prefix alone** -- ``name.startswith("pre-")`` /
``"post-"`` / ``"end-"`` -- so any suffix runs, ``-migrate.py`` and
``-migration.py`` included, and a descriptive name such as
``post-migrate_update_taxes.py`` is fine. Within a stage they run in filename
order.

The ``migrate`` function's signature is checked and must be exactly two positional
parameters named ``(cr, version)`` -- ``_cr`` / ``_version`` are the only accepted
aliases. Anything else raises ``TypeError`` at migration time, when the upgrade is
already running.

Lint rules are relaxed under ``**/migrations/**`` -- ``E501``, ``UP``, ``PTH`` and
``ERA`` are suppressed, because migration scripts are raw SQL, legacy patterns and
commented reference code by nature.

12.2 Writing one
----------------

.. list-table::
   :header-rows: 1
   :widths: 20 14 66

   * - Script
     - ORM
     - Use for
   * - ``pre-migrate.py``
     - no
     - renaming columns and preventing data loss before the ORM recreates them
   * - ``post-migrate.py``
     - yes
     - data transformation and field-value migration
   * - ``end-migrate.py``
     - yes
     - cross-module cleanup after every module is processed

.. code-block:: python

   def migrate(cr, version):
       if not version:
           return
       ...

The framework passes a **cursor**, not an environment. Guard ``pre-migrate`` SQL
with the helpers in ``odoo.db.schema`` -- ``table_exists``, ``column_exists``,
``index_exists``, ``create_column``, ``convert_column``, ``drop_constraint`` --
rather than hand-written ``information_schema`` queries. (There is no
``odoo.tools.sql`` in this fork.) ``openupgradelib`` is available but is not the
house default.

**Removing a stored field: its column is dropped in the same upgrade, and
post-migrate is the last place its values can be read** ``[review]``. Odoo deletes
the ``ir.model.fields`` row for a field the code no longer declares and issues
``ALTER TABLE ... DROP COLUMN CASCADE`` for it, from ``ir.model.data._process_end``
-- which ``modules/loading.py`` runs *after* every ``post-migrate``. So a
``post-migrate`` that harvests the old values into their new home works, and there
is nothing left for a later version to harvest.

**A Many2many is the exception: its relation table is never dropped**
``[review]``. ``_drop_m2m_tables`` skips any field whose ``state`` is not
``manual``, and a field declared in Python is ``base``. Removing a code-defined
Many2many deletes its ``ir_model_fields`` row and leaves the join table, its rows
and its foreign keys in place for good. Useful -- the old configuration stays
readable -- but not cleanup: drop the table yourself if the data is not worth
keeping, and say so in the script.

**Do not plan that harvest across two versions** ``[review]``. ``migrate_module``
runs **every** ``pre`` script for every version in range before **any** ``post``
script, so a ``pre-migrate`` at a *higher* version still executes before a *lower*
version's ``post-migrate``. Splitting "copy the values" and "drop the column"
across two versions therefore drops first and copies nothing -- and the data is
gone with no error, because dropping a column the ORM was going to drop anyway
raises nothing. Copy and link in one ``post-migrate``.

12.3 When one is required
-------------------------

**Required**: adding or removing a required field on an existing model; changing a
field's type; renaming a model or field; any non-trivial data transformation.

**Not required**: adding an optional field; installing a new module; view-only
changes; adding or removing a Many2many relation.

----

Appendix A — Fork field renames
================================

``project.task`` renames fields in this fork. Reading, searching or sorting on a
vanilla name raises, surfacing as a 500 over JSON-RPC and MCP. Apply these
regardless of what training data suggests.

.. list-table::
   :header-rows: 1

   * - Vanilla Odoo
     - This fork
   * - ``stage_id``
     - ``step_id`` (Many2one → ``project.workflow.step``)
   * - ``date_deadline``
     - ``date_end``
   * - ``date_last_stage_update``
     - ``date_last_status_change``
   * - ``personal_stage_type_id``
     - ``personal_triage_id`` (Many2one → ``project.task.triage``). Note the
       separate related field ``triage_id`` → ``project.triage``.
   * - ``depend_on_ids``
     - ``predecessor_ids``
   * - ``dependent_ids``
     - ``successor_ids``

So ``("stage_id.fold", "=", False)`` becomes ``("step_id.fold", "=", False)``, and
``order="date_deadline asc"`` becomes ``order="date_end asc"``.

``purchase.order`` and ``purchase.order.line`` rename one field, so the date a
human committed to has a single name across order types:

.. list-table::
   :header-rows: 1

   * - Vanilla Odoo
     - This fork
   * - ``date_planned``
     - ``date_commitment``

``sale.order.date_commitment`` already carried that meaning -- the delivery date
promised to the customer -- while purchase spelled the vendor's promised arrival
``date_planned``. Shared code in ``base_order`` now names it once:
``mixin.order``'s ``is_late`` domain reads ``date_commitment`` on both.

**``date_planned`` still exists, and still means something else**: a *derived,
unstored* estimate on ``sale.order`` (and on ``sale.order.line`` under
``sale_stock``), the scheduling date on ``stock.move`` and ``stock.picking``, the
key in the procurement ``values`` dicts, and a field on the replenishment wizard.
None of those were renamed.

Order lines: ``product_qty`` and ``product_uom_qty`` swapped meanings
---------------------------------------------------------------------

Both names still exist on ``sale.order.line`` and ``purchase.order.line``, and
both carry the *other* one's upstream meaning. ``mixin.order.line.amount``
(``addons/base_order/models/mixin_order_line_amount.py``) defines them:

.. list-table::
   :header-rows: 1

   * - Field
     - This fork
     - Upstream
   * - ``product_qty``
     - the ordered quantity, **in the line's own unit** (``product_uom_id``).
       Computed with ``readonly=False`` — this is the one to write.
     - the ordered quantity converted to the product's reference unit
   * - ``product_uom_qty``
     - the same quantity converted to the product's **reference** unit
       (``product_id.uom_id``). Computed, stored, ``readonly=True``.
     - the ordered quantity in the line's own unit

**Writing ``product_uom_qty`` does not raise; it silently does the wrong
thing.** In ``create`` the value is discarded and ``product_qty`` falls back to
its default of 1 — a test that orders 10 orders 1 and usually still passes. In
``write`` the value lands in the stored column while ``product_qty`` keeps its
old value, so the two disagree until something recomputes: a line reading 1 in
its own unit and 3 in the reference unit, for a product whose two units are the
same. Both shapes were found across the mrp ring, in tests and in model code
(``sale_mrp`` and ``purchase_mrp`` fed ``product_uom_qty`` to a conversion that
declares its input to be in ``product_uom_id``).

So: **write ``product_qty``**, and read it wherever the quantity is about to be
converted from ``product_uom_id`` or compared with a BoM's ``product_qty``.
Read ``product_uom_qty`` only where the reference unit is what is wanted — for
example comparing a line against free stock. ``stock.move.product_uom_qty`` is
unrelated and unchanged: it is a real, writable field there.

Counted by ``tooling/architecture/order_line_qty.py`` and ratcheted as
``orderlineqty``. A count rather than a raise on the field, on ADR-0033's
argument: the tree opens with well over a hundred of these, so the floor is
frozen first and driven down module by module. The raise is where it ends —
that is what every other rename here does, and a write that silently half-lands
is the failure mode the raise exists to prevent.

Appendix B — References
========================

In this repo:

* ``ruff.toml`` -- linter and formatter configuration, with the rationale for
  every suppression
* ``odoo/addons/test_lint/`` -- the fork's own checkers
* ``tooling/ratchet/baselines/`` -- the committed floors
* ``pytest.ini`` -- the Tier 1 suite definition

In the knowledge repository's ``reference/``:

* ``odoo/odoo-19-development-context.md`` -- Odoo 17→19 API changes
* ``dev/error-catalog.md`` -- known PATH / CONFIG / SERVICE / POSTGRES errors
* ``owl/`` -- OWL hooks, stores and lifecycle
* ``python-pg/`` -- Python 3.14 and PostgreSQL 18 / psycopg 3 patterns

External:

* `Odoo 19 Coding Guidelines <https://www.odoo.com/documentation/19.0/contributing/development/coding_guidelines.html>`_
* `OCA CONTRIBUTING.rst <https://github.com/OCA/odoo-community.org/blob/master/website/Contribution/CONTRIBUTING.rst>`_
* `PEP 8 <https://peps.python.org/pep-0008/>`_

Appendix C — Retired patterns
==============================

Flag these on sight; migrate opportunistically when you are already editing the
file.

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Retired
     - Replacement
   * - Suffix XML IDs (``sale_order_view_form``)
     - Prefix style (§3.2)
   * - Commit tags ``[MIG]``, ``[CLA]``
     - ``ADD`` / ``REF`` on the migration script; ``REF`` on the licence change
       (§7.1) -- both described the *subject*, not the intent
   * - Suffix mixin names, and abstract models that are mixins but carry no marker
     - Prefix ``mixin.`` (§2.2.1)
   * - Two model classes in one ``models/*.py``
     - One per file, named from ``_name`` (§1.3)
   * - Field ordering by type
     - Semantic blocks (§2.3)
   * - Method ordering by Spanish category
     - The section banners in §2.2
   * - Google-style docstrings (``Args:``, ``Returns:``)
     - Sphinx fields (§2.5)
   * - ``<tree>`` views and ``view_mode`` ``tree``
     - ``<list>`` (§3.3); core is fully migrated
   * - ``attrs=`` / ``states=``
     - Python expressions ``invisible=`` / ``readonly=`` / ``required=`` (§3.3)
   * - Renaming an inherited core method to fit §2.4
     - Override under the original name (§2.4)
   * - ``split_every``
     - ``itertools.batched`` (§11.7)
   * - ``with_context(force_company=...)``
     - ``with_company()`` (§2.6) -- the key is now ignored with only a
       ``DeprecationWarning``, so surviving call sites silently use the wrong
       company
   * - ``_sql_constraints = [...]``
     - ``models.Constraint`` (§2.9.8)
   * - ``def create(self, vals)``
     - ``@api.model_create_multi def create(self, vals_list)`` (§2.6)
   * - Magic x2many tuples ``(0, 0, {})``
     - ``Command.*`` (§2.9.7)
   * - ``name_get`` / ``_name_search``
     - ``_compute_display_name`` / ``_search_display_name`` (§2.4, §2.6)
   * - OCA ``queue_job``
     - ``ir.job`` and ``@api.job`` (§2.9.14)
   * - wkhtmltopdf workarounds; ``dpi`` / ``header_spacing`` /
       ``disable_shrinking`` on paperformats
     - WeasyPrint paged media (§3.6.1)

Appendix D — Document history
==============================

One row per change, saying what moved. The argument lives in the section it moved.

.. list-table::
   :header-rows: 1
   :widths: 8 12 80

   * - Version
     - Date
     - Summary
   * - 6.3
     - 2026-08-23
     - **Appendix A gains the order-line quantity swap.** ``product_qty`` and
       ``product_uom_qty`` both exist on ``sale.order.line`` and
       ``purchase.order.line`` and each carries the other's upstream meaning:
       ``product_qty`` is the quantity in the line's own unit and is the
       writable one, ``product_uom_qty`` is that quantity in the product's
       reference unit and is ``readonly``. Writing ``product_uom_qty`` does not
       raise — in ``create`` it is discarded and the line silently becomes
       quantity 1, in ``write`` it lands in the column while ``product_qty``
       keeps its old value and the two disagree. Both shapes were live across
       the mrp ring: six ``sale.order.line`` creates and three
       ``purchase.order.line`` creates ordering 1 instead of the quantity they
       named, seven ``write`` calls desynchronising a rental line, and model
       code in ``sale_mrp`` and ``purchase_mrp`` feeding the reference-unit
       number to a conversion that declares its input to be in the line's unit.
       Nothing is retired: the field names are unchanged, only their meanings,
       and the appendix now says which is which. Counted by
       ``tooling/architecture/order_line_qty.py`` and ratcheted as
       ``orderlineqty``, on ADR-0033's argument — a rule this size is frozen
       where it stands and driven down, not blocked on day one.
   * - 6.2
     - 2026-08-22
     - §6.9 added: diff a run against its recorded failure set rather than
       re-running the suite to learn whether a red test was already red; never
       count failures by grepping ``ERROR``; diff names, not counts.
   * - 6.1
     - 2026-08-22
     - Narration cut throughout. No rule added, removed or changed: every
       ``[label]``, table, code block and gated figure is carried over, and every
       sentence ``doc_restated_counts`` pins is re-anchored in the same commit.
       Worked examples keep the rename pair and drop the story around it;
       Appendix D's rows are condensed to one clause each.
   * - 6.0
     - 2026-08-22
     - Full rewrite into a direct, rule-first style; §2.4 gains numbered
       subsections §2.4.1--§2.4.17.
   * - 5.42
     - 2026-08-22
     - §2.9.8: the constraint attribute names the columns; a rename is carried by
       module-data cleanup, not a migration; the rename breaks the translations.
   * - 5.41
     - 2026-08-22
     - §2.4: a payload builder named for the operation it feeds borrows its
       caller's verb; the ``@api.constrains`` family, named for the condition it
       enforces rather than its triggers; a ``Protocol`` declaration is a binding.
   * - 5.40
     - 2026-08-22
     - §2.4: running is the domain operation of a scheduler; a callback is a role;
       a count of spellings is not a count of violations; it is worse when the
       field exists; provenance separates artifacts, not arithmetic; the cache
       verbs are reserved for caches.
   * - 5.39
     - 2026-08-21
     - §2.4: a trailing preposition is an operand; the tail says which
       representation; ``field`` is a ``Field`` and ``field_name`` is a name.
   * - 5.38
     - 2026-08-21
     - §2.4: head-first is a test as well as an ordering; a memo takes the
       spelling of what it memoizes; a slot and its implementation are one
       contract; a shape suffix binds every override; the never-raising
       ``@api.constrains``-bound ``_check_``.
   * - 5.37
     - 2026-08-21
     - §2.2.1: mixins are named ``mixin.<what they add>`` -- prefix, not suffix.
   * - 5.36
     - 2026-08-20
     - §2.4: a domain builder leads with its object (ADR-0054, superseding
       ADR-0050), plus four bindings no checker reaches.
   * - 5.35
     - 2026-08-20
     - §2.4: an error is built here and raised there; a canonical verb can be
       wrong; an addition's tail names what is added; the signature can prove a
       public spelling was an accident.
   * - 5.34
     - 2026-08-20
     - §2.4: the execution-verb rule gains worked examples and its first
       principled exception.
   * - 5.33
     - 2026-08-20
     - §2.4: wearing a dispatch prefix does not make a name a key.
   * - 5.32
     - 2026-08-20
     - §2.4: the assemble verbs are enforced for one shape; the payload suffix
       list is a search; object construction takes ``_prepare_``.
   * - 5.31
     - 2026-08-20
     - §2.4: what "name the domain operation" looks like, worked. Corrects 5.29's
       helper-class figure.
   * - 5.30
     - 2026-08-20
     - §2.4: ``exists`` joins the reserved verbs; the pure ORM reads move to
       ``_get_``.
   * - 5.29
     - 2026-08-20
     - §2.4: ``_find_`` is three operations wearing one verb; the class-membership
       blind spot covers module-level helpers and plain classes both.
   * - 5.28
     - 2026-08-20
     - §2.4: a signature does not identify a family; the abolished table maps
       spellings, not methods.
   * - 5.27
     - 2026-08-20
     - §2.4: the scope test is class membership, so a module's own helpers are
       ungoverned; the object rule widens past collections; a provider noun is a
       namespace.
   * - 5.26
     - 2026-08-19
     - §2.4: the object leads its qualifier; the public form drops the underscore,
       not the verb.
   * - 5.25
     - 2026-08-19
     - §2.4: ``@api.ondelete`` gains a row; canonical
       ``_unlink_except_<case that raises>``.
   * - 5.24
     - 2026-08-19
     - §2.4: the field-hook rule reaches five attributes and there are six; a
       decorator binding is out of reach by construction; a hook may hold two
       bindings.
   * - 5.23
     - 2026-08-19
     - §2.4: four rules from ``avatar.mixin`` -- a hook's prefix is reserved for
       hooks, the verb leads, ``_generate_``, provenance as tiebreak.
   * - 5.22
     - 2026-08-18
     - §2.4's figures are derived rather than stated, through
       ``doc_restated_counts.py`` (ADR-0041); the census is re-scoped to this
       repository.
   * - 5.21
     - 2026-08-18
     - §1.4: a machine-doc figure is gated or frozen, never bare (ADR-0043).
   * - 5.20
     - 2026-08-17
     - §7.2, §7.3: the task ID and the PR stop being mandatory.
   * - 5.19
     - 2026-08-15
     - §12.2: a removed Many2many keeps its relation table forever (ADR-0039).
   * - 5.18
     - 2026-08-15
     - §12.2: a removed field's column goes in the same upgrade, and the harvest
       cannot be split across versions (ADR-0040).
   * - 5.17
     - 2026-08-17
     - The ratchets: adds ``pyfunclen_addons``, the first ``--mode no-increase``
       floor, for excess extracted out of ``odoo/`` into an addon.
   * - 5.16
     - 2026-08-14
     - Change protocol: cite the record, and write one where a rule is a
       decision. ADR-0007 (the CI integration lane) and ADR-0021 (*service*
       facades) were checked and deliberately not cited.
   * - 5.15
     - 2026-08-15
     - §7.1 requires a pathspec to name files, not a directory.
   * - 5.14
     - 2026-08-15
     - §6.4 splits the query-count rule in three: get the stack, pin the
       guarantee, assert the mechanism.
   * - 5.13
     - 2026-08-11
     - §2.9.14 gains ``_defer()`` -- not finished is not failed.
   * - 5.12
     - 2026-08-10
     - §2.9.8 forbids UNIQUE over a translated column.
   * - 5.11
     - 2026-08-10
     - §8.3's re-export command corrected; deleting a string also needs a
       re-export.
   * - 5.10
     - 2026-08-09
     - pydocstyle retired: docstring presence is ``[review]``, only accuracy is
       mechanical.
   * - 5.9
     - 2026-08-09
     - The ratchets section states no count; the tool is the reading.
   * - 5.8
     - 2026-08-09
     - §12.2 named a module that does not exist; the helpers are in
       ``odoo/db/schema.py``.
   * - 5.7
     - 2026-08-09
     - Appendix A records ``date_planned`` → ``date_commitment`` on purchase.
   * - 5.6
     - 2026-08-09
     - §2.4 gains the cache lifecycle verbs.
   * - 5.5
     - 2026-08-08
     - §1.2 names the right requirements file, and when *not* to declare an
       external dependency.
   * - 5.4
     - 2026-08-07
     - Cyclomatic complexity is gated by a ``c901`` floor separate from ``ruff``.
   * - 5.3
     - 2026-08-07
     - ``test_lint`` runs in CI; ratchets table completed.
   * - 5.2
     - 2026-08-06
     - §2.4 gains the verb vocabulary: canonical verb per operation, the abolished
       table, the reserved verbs, the *provisional* rules.
   * - 5.1
     - 2026-07-30
     - Corrections: ``force_company`` does not raise; ``<group>`` does carry
       attributes in search views; ratchets fail both ways; the
       ``at_install``/``post_install`` XOR is warned, not enforced; E8507 has no
       escalation; §2.9.4 and §12.1 corrected.
   * - 5.0
     - 2026-07-30
     - Full fact-check and rewrite. The countable gates are *ratchets* over
       committed floors, not blocking lint; ``[label]`` markers replace 🔧/👁;
       the ``test_lint`` layer documented; roughly a quarter of the length cut.
   * - 4.2
     - 2026-06-30
     - XML IDs reversed from suffix back to prefix; the XML fixers, the
       single-line ``domain``/``context`` rule, and sorter-then-formatter order.
   * - 4.1
     - 2026-06-23
     - §2.4 expanded: mail and framework-hook rows, naming-determines-section,
       field wiring, the class-eval ``default=`` note.
   * - 4.0
     - 2026-06-22
     - Linter claims reconciled with ``ruff.toml``; broken examples fixed; markers,
       TL;DR and glossary introduced; rules added for ``Command``,
       ``models.Constraint``, ``@api.model_create_multi``, multi-company, float
       comparison and modern typing.
   * - 3.0
     - 2026-04-20
     - Prior canonical revision (suffix XML IDs, 16-section model layout, Sphinx
       docstrings, unified 13-tag commit catalog).

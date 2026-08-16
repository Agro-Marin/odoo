.. _coding_guidelines:

===========================
AgroMarin Coding Guidelines
===========================

:Version: 5.19
:Date: 2026-08-15
:Base: `Odoo 19.0 Coding Guidelines <https://www.odoo.com/documentation/19.0/contributing/development/coding_guidelines.html>`_
       + `OCA CONTRIBUTING.rst <https://github.com/OCA/odoo-community.org/blob/master/website/Contribution/CONTRIBUTING.rst>`_

This is the single coding standard for the AgroMarin fork of Odoo 19.0. It is
authoritative where it speaks; where it is silent, follow upstream Odoo 19, then
OCA.

Every factual claim below — enforcement codes, file paths, API signatures,
defaults — is checked against the tree it describes. If you find one that no
longer holds, fix it here in the same PR as the code that broke it; a guideline
that lies is worse than one that is missing.

.. contents::
   :local:
   :depth: 2

----

How rules are enforced
======================

Each rule carries a bracketed label naming the gate that catches it:

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Label
     - Meaning
   * - ``[ruff CODE]``
     - ``ruff check`` reports it. See *The ratchets* below for what CI actually
       blocks on.
   * - ``[test_lint CODE]``
     - A checker in the ``test_lint`` module fails on it. Codes ``E8501``–``E8507``
       belong to the AST checkers; other ``test_lint`` gates have no code and are
       named by their test.
   * - ``[fixer NAME]``
     - A behaviour-preserving fixer exists and owns the formatting. Run it rather
       than hand-editing.
   * - ``[review]``
     - No tool checks this. A human does, using §9.

Do not infer enforcement from how a rule is phrased. Several rules that read
like lint rules are review-only because the corresponding ``ruff`` code is
deliberately disabled, each with a written rationale in ``ruff.toml``.

The ratchets
------------

**``ruff check`` is not expected to be clean, and CI does not require it to be.**
The fork inherits a large upstream codebase, so the countable gates are
*ratchets*: each workflow measures a total and compares it against a committed
floor in ``tooling/ratchet/baselines/``. *How rules are enforced* states the
model and what closed the gaps that let the floors drift.

**A ratchet fails in both directions.** ``ratchet.py`` defaults to ``exact`` mode
and every floor but one is invoked without ``--mode``, so the count must *equal*
the floor: an improvement fails the build just as a regression does. This is
deliberate — it forces the gain to be locked in rather than silently re-spent.
When you lower a count, commit the new floor in the same PR:

.. code-block:: bash

   python tooling/ratchet/ratchet.py <gate> --count <N> --update

This bites most often through ``.pre-commit-config.yaml``, which runs
``ruff-check --fix``: touching any file that carries baseline findings can repair
unrelated ones and drop the count. A green local commit is not a green CI run
unless the floor moved with it.

**The one exception is** ``pyfunclen_addons``, invoked ``--mode no-increase``.
It measures the whole bundled-addons tree, which moved by roughly 1700 excess
lines in each direction over a month against 587 commits touching
``addons/**/*.py`` in a fortnight; under ``exact`` it would be red almost
continuously, and a floor re-cut reflexively to clear a build is a floor nobody
audits. One-sided keeps the property the gate exists for — excess relocated out
of ``odoo/`` into an addon fails it — and gives up the one it cannot hold. An
improvement there is free, not owed; lower it whenever you measure it lower.
Prefer ``exact`` for every new floor, and record the argument here if you cannot
have it.

.. list-table::
   :header-rows: 1
   :widths: 16 30 22 32

   * - Gate
     - Command
     - Scope
     - Workflow
   * - ruff
     - ``ruff check odoo/ --no-cache --statistics``
     - ``odoo/`` only — a **hard zero**
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

**Why a ratchet rather than a hard zero** is ADR-0006. Why each *architecture*
gate above exists is a separate question per gate, and the answer is in the gate:
every module in ``tooling/architecture/`` declares the record that argues for it
as a module-level ``ADR`` constant, which ``test_gate_adr_coverage.py`` checks
resolves to an ``Accepted`` record. The mapping is deliberately not repeated
here — restating it would be a second copy of something the modules already say.

``tooling/ratchet/baselines/`` is the authoritative list: **one JSON per gate,
and the directory is the count.** No number is written here on purpose. This
paragraph said "nine floors today" beside a table of ten rows, one of which was
not a ratchet at all, while the directory held thirteen — the same drift the
ratchets exist to stop, in the document that defines them. Read the floors and
their number off the tool:

.. code-block:: bash

   python tooling/ratchet/ratchet.py --list

The layer-boundary gate is **not** a ratchet and is no longer listed above:
crossings are held at exactly zero and any new one fails outright, so there is
no floor and no baseline file. It is described under the fourth consequence
below. The ``test_lint`` ratchets are counted separately, inside the module's
own ``assert_ratchet`` (see below), and are not baselined here either.

Five consequences you must internalise:

* **The ruff ratchet measures ``odoo/``, not ``addons/``.** Addon code — including
  every ``agromarin`` module — is outside the counted scope. For addons, ``ruff``
  is a local discipline enforced by pre-commit and review, not by the ratchet.
* **A finding on a file you touched may predate you.** Compare against ``git diff``,
  not against a whole-file lint report.
* **``ruff`` is measured at a hard zero, over the whole selected ruleset.** It
  once carried ``--ignore D`` against a separate ``ruff_docstring`` floor; both
  are gone, because pydocstyle is no longer selected at all (§2.5). The episode
  is kept here for the rule it established, which outlives the gate: an
  exact-match ratchet over one integer cannot tell "someone added a docstring"
  from "someone introduced a real defect". 758 of the aggregate's 759 findings
  were D1xx, so every added docstring bought room for an unrelated new finding,
  and one genuine defect hid there for exactly that reason. **A gate whose floor
  is nonzero can always launder a regression against an unrelated improvement** —
  split it before that matters, not after, and retire it if the debt it pins is
  debt nobody intends to pay.
* **``ruff`` and ``c901`` are two floors over one command.** ``ruff.toml``
  ignores ``C901`` so it stays out of the aggregate, and the ``c901`` step
  re-selects it on the CLI, which overrides that ignore. Its threshold is
  ``[lint.mccabe] max-complexity`` — raising the threshold lowers the count
  without fixing anything, so move it only as deliberately as the floor itself,
  and say so in the baseline note. Complexity was ungated until 19.0-marin:
  ``ruff.toml`` selected the ``C90`` family while ignoring ``C901``, its only
  rule, and the two branch-complexity rules each justified their suppression by
  naming the other.
* **The architecture gate is different**: layer crossings are held at exactly
  zero and any new one fails outright. It is not a ratchet. The same job also
  holds JS *import cycles* at zero (``tooling/architecture/js_cycle_check.py``,
  ADR-0019; ADR-0034 is the Python counterpart),
  because a cycle's damage depends on evaluation order rather than on the code:
  the same cycle throws a ``ReferenceError`` under debug's per-file native ESM
  and silently substitutes ``undefined`` under ``esbuild --bundle``. Pre-existing
  cycles are pinned in ``KNOWN_CYCLES`` with a rationale, like the layer gate's
  ``KNOWN_VIOLATIONS``.

Each gate runs on ``pull_request`` and on ``push`` to ``19.0-marin`` / ``19.0``,
so direct commits and merge skew cannot silently move a floor.

The ``test_lint`` module
------------------------

``odoo/addons/test_lint`` is the fork's own enforcement layer: AST checkers and
registry-level tests that encode Odoo-specific rules no general-purpose linter
knows about. Every rule is an exact-match ratchet (``LintCase.assert_ratchet``):
the count may not rise, and it may not fall silently either, so a fix that gets
undone fails just as loudly as a new offence.

**It runs in CI in two lanes.** ``test_lint.yml`` installs ``base`` +
``test_lint`` and runs ``/test_lint`` on every pull request with no ``paths:``
filter, because these gates scan the whole tree rather than a subtree: a new
``.py`` anywhere can add an N+1 finding, a deleted file can break a manifest
asset path. ``asset_lint.yml`` covers the classes that need a
real registry (bundles, dark siblings, ESM specifiers) against a wider install
set. ``integration_tests.yml`` installs only ``base`` and does not run these.

Run it yourself before opening a PR that touches Python, XML or manifests:

.. code-block:: bash

   odoo-bin -d <db> -i test_lint --test-enable --stop-after-init

Rules it enforces, and where each is documented:

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
     - Query call inside a ``for`` loop (§11.1). **Advisory only** — logs at
       WARNING, does not fail, and there is no escalation mechanism today
       (``_BATCH_FAIL_MODULES`` is named in a docstring but not implemented).
   * - ``_checker_noqa_rationale``
     - —
     - ``# noqa`` without a written rationale (§*Suppressing a rule*)
   * - ``test_index``
     - —
     - Stored One2many inverse not indexed (§11.5)
   * - ``test_onchange_domains``
     - —
     - Domain returned from an ``@api.onchange`` (§2.9.9)
   * - ``test_naming``
     - —
     - Public method with an ``ids`` or ``context`` parameter (§2.4)
   * - ``test_override_signatures``
     - —
     - Override whose signature diverges from its parent (§2.4)
   * - ``test_orm_import``
     - —
     - Addon runtime code importing ``odoo.orm`` directly (§2.1)
   * - ``test_manifests``
     - —
     - Unknown or misordered ``__manifest__.py`` key (§1.2)
   * - ``test_test_holes``
     - —
     - Test file not imported exactly once in ``tests/__init__.py`` (§6.1)
   * - ``test_docstring``
     - —
     - Docstring fields disagreeing with the signature (§2.5)
   * - ``test_routes``
     - —
     - Inherited route restating an unchanged attribute (§2.8)
   * - ``test_l10n``
     - —
     - Mis-tagged localisation test (§6.7)
   * - ``test_xml_records``
     - —
     - ``<field>`` child order / element attribute order (§3.1)
   * - ``test_pretty_xml``
     - —
     - XML formatting (§3.1)
   * - ``test_dunderinit``
     - —
     - Module without an ``__init__.py``
   * - ``test_markers``
     - —
     - Version-control conflict markers left in a file
   * - ``test_pofile``
     - —
     - Duplicate entries in a ``.pot`` file (§8.3)
   * - ``test_i18n`` / ``test_jstranslate``
     - —
     - Untranslatable static strings in templates and JS (§8.2)
   * - ``test_eslint``
     - —
     - ESLint over JS (skipped when ``eslint`` is absent)
   * - ``test_pep649``
     - —
     - Annotations that fail to resolve under PEP 649

Suppressing a rule
------------------

Every suppression must say why ``[test_lint]``:

.. code-block:: python

   value = compute()  # noqa: RUF015 — ordering is guaranteed by the caller

``# noqa`` bare, or ``# noqa: CODE`` with nothing after it, is itself a violation.
The rationale must carry at least four non-space characters including a letter.

For the ``E85xx`` checkers, ``# noqa: E8501`` and ``# pylint: disable=sql-injection``
are both recognised. Broader escapes — ``ruff.toml`` ``per-file-ignores``, the
allow-lists inside ``test_index.py`` and ``test_override_signatures.py`` — are
config changes and need review on their own merits.

Quick Reference
===============

The one-screen version. Each entry links to the rule that explains it.

**Python**

* Double quotes, line length 88; match ``ruff format``'s output in what you write,
  but never reformat a whole inherited file (§2.1).
* One model per file, named after the model's ``_name`` (§1.3) ``[review]``.
* Reach the ORM through ``odoo.api`` / ``odoo.fields`` / ``odoo.models`` — never
  import ``odoo.orm`` from addon runtime code (§2.1) ``[test_lint]``.
* Every model declares ``_name`` and ``_description`` (§2.6) ``[review]``.
* Override ``create`` as ``@api.model_create_multi def create(self, vals_list)``,
  and always ``super()`` in ``create`` / ``write`` / ``unlink`` / ``copy_data`` /
  ``default_get`` (§2.6) ``[review]``.
* Deletion constraints use ``@api.ondelete``; a ``raise`` inside an ``unlink``
  override is a violation (§2.6) ``[test_lint E8506]``.
* Name new buttons ``action_*`` — never rename an inherited core method (§2.4).
* One verb per operation: ``_prepare_`` builds payloads, ``_get_`` reads, ``_check_``
  raises, ``_is_``/``_has_``/``_can_`` return booleans, ``_update_`` writes,
  ``_add_``/``_remove_`` for collections. ``_build_``, ``_fetch_``, ``_validate_``,
  ``_verify_``, ``_ensure_``, ``_do_``, ``_run_``, ``_perform_`` are abolished
  (§2.4) ``[review]``.
* ``odoo.fields.Command`` for x2many writes, never raw tuples (§2.9.7) ``[review]``.
* Never compare money or floats with ``==`` / ``!=`` / ``<`` / ``>`` — use
  ``float_compare`` / ``float_is_zero`` (§2.9.12). Only ``==`` / ``!=`` is linted
  ``[ruff RUF069]``.
* User-facing text goes through ``self.env._(...)`` with ``%s`` arguments
  (§8.1) ``[test_lint E8502]``.
* ``raise X from Y`` inside ``except`` (§2.7) ``[ruff B904]``.
* No ``cr.commit()`` in business code — the framework owns transactions (§2.6).
* ``datetime.now(UTC)``; ``datetime.utcnow()`` is banned (§2.9.6) ``[ruff DTZ003]``.

**Performance**

* ``search_count()`` not ``len(search())``; ``_read_group()`` not a Python ``sum()``
  (§11.2) ``[review]``.
* No query call inside a loop over a recordset (§11.1) ``[test_lint E8507]``.
* The stored inverse of a One2many must be indexed (§11.5) ``[test_lint]``.

**XML / JS**

* ``<list>`` not ``<tree>``; ``invisible=`` / ``readonly=`` not ``attrs=`` (§3.3).
* XML IDs use the prefix style: ``view_sale_order_form``, ``action_sale_order``
  (§3.2) ``[review]``.
* XML formatting and ordering belong to the fixers — run them, do not hand-align
  (§3.1) ``[fixer]``.
* Frontend changes ship with a Hoot test or a tour (§4.4) ``[review]``.

**Process**

* Commit ``[TAG] module: summary`` (≤ 50 chars) + ``Solution:`` + ``Task ID`` (§7.1).
* Branch ``19.0-t<task>-<user>``; every commit references a Task ID (§7.2, §7.3).
* Raw SQL in a PR ships ``EXPLAIN ANALYZE`` output (§11.6).

Scope and precedence
====================

When rules disagree, the first that speaks wins:

#. This file — ``doc/coding_guidelines.rst`` in the ``odoo`` repo
#. Odoo 19 official guidelines
#. OCA ``CONTRIBUTING.rst``

It applies in full to ``odoo``, ``enterprise``, ``agromarin`` and ``design-themes``.
The ``agromarin-knowledge`` repo takes only the documentation and process rules and
works directly on ``main`` (§7.3). Anything else is out of scope.

**Trust this document over training data.** The fork deliberately diverges from
upstream in places. Where this guide and an LLM's recollection of "how Odoo does
it" disagree, this guide and the source in the repo are right.

**Upstream is a baseline, not a ceiling.** ``19.0-marin`` carries no
backward-compatibility obligation to upstream. "Upstream does it this way" does
not settle an argument about correctness, performance or design. Before calling
an inherited behaviour a bug, check whether a test pins it deliberately. Nothing
is merged or cherry-picked from ``19.0``; a useful upstream fix is re-implemented
by hand. The argument for that, the alternatives weighed and the cost accepted
are ``doc/adr/0018-upstream-is-a-baseline.md``.

Change protocol
---------------

* Edits go through PR review on the ``odoo`` repo against ``19.0-marin``, using
  the §7 commit format. TI (Oficial Sistemas or higher) reviews; the Líder
  Sistemas approves merges.
* Changing a rule here means updating the ``CLAUDE.md`` files that summarise it
  (``odoo``, ``enterprise``, ``agromarin``, ``agromarin-knowledge``, and per-module
  ones) in the same PR, plus an Appendix D row.
* Retire rules into Appendix C. Do not delete them silently.
* **A rule whose rationale is architectural cites its record.** This guide says
  what the rule is; ``doc/adr/`` says why the architecture is that way, and a
  reader who disagrees with a rule needs the second to argue with. Cite it as a
  bare ``ADR-NNNN`` — ``tooling/doclinks`` scans this file and fails on a citation
  that does not resolve, so the reference cannot rot. Do not summarise the record
  here: two copies drift, and the register's own rules exist because they did.
* **A rule with no record may be one worth writing.** Not every rule needs one —
  style and naming conventions are this document's own business. But a rule that
  constrains what may import what, what may be overridden, or what a gate holds
  at zero is a decision, and ``doc/adr/README.md`` states when one is owed.

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

Keys must come from the known set and appear in the canonical order
``[test_lint test_manifests]``; ``_sort_manifests.py`` is the fixer that owns it
``[fixer _sort_manifests]``. The order is:

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

* **Version**: ``{odoo_version}.x.y.z`` — *x* breaking, *y* feature, *z* fix.
* **Omit empty keys** rather than writing them empty.
* **``depends`` lists direct dependencies only**, never transitive ones.
* **``auto_install``** only for a genuine bridge module between two independent
  modules (the way ``sale_crm`` bridges ``sale`` and ``crm``).
* **Demo data belongs in ``demo``**, not ``data``.
* **``license``** must match how the module is actually distributed. The fork
  ships a mix (``LGPL-3``, ``OPL-1``, ``AGPL-3``, ``OEEL-1``); copying a
  neighbour's value without checking is how a module ends up mislicensed.
* **External dependencies** are declared in the manifest *and* pinned in the
  requirements file of the repo that owns the module — ``requirements-addons.txt``
  in ``odoo``, ``requirements.txt`` in ``enterprise`` and ``agromarin``. The
  server's own ``odoo/requirements.txt`` is not that file: it carries only what
  the framework and the always-loaded addons import, so adding a module's
  dependency there puts it on every install that will never load the module.

  .. code-block:: python

     "external_dependencies": {"python": ["requests"], "bin": ["wkhtmltopdf"]},

  Use the **PyPI distribution name**, not the import name
  (``python-ldap``, not ``ldap``): ``check_python_external_dependency`` resolves
  it through ``importlib.metadata.version``, and falls back to importing the
  name only after logging a warning.

  **Declare only what the module cannot start without.** A dependency behind a
  ``find_spec`` guard, a function-local import or ``try/except ImportError`` is
  optional by construction, and declaring it converts a feature that degrades
  into an install that is refused. ``base_import`` is the worked example: it
  declares ``chardet``, which it imports at module level, and deliberately does
  not declare ``xlrd``, ``odfpy`` or ``openpyxl``, which it imports inside the
  reader for each format.

  **An ``auto_install`` module cannot rely on the declaration at all.**
  ``odoo/modules/db.py`` marks the auto-install closure in raw SQL and never
  consults ``external_dependencies``, which is checked only on the UI install
  path — so the dependency has to be pinned as a server requirement instead.
  ``cbor2`` (``auth_passkey``) and ``ofxparse``
  (``account_bank_statement_import_ofx``) are the two such cases.

1.3 File naming
---------------

**One model per file** ``[review]``. The file name derives from the model's ``_name``.

.. list-table::
   :header-rows: 1

   * - Type
     - Pattern
     - Example
   * - Model
     - ``models/{model_name}.py``
     - ``sale_order.py`` for ``sale.order``
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

----

2. Python
=========

2.1 Style and imports
---------------------

* PEP 8, **line length 88** — the style ``ruff format`` produces.
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

**Reach the ORM through the public façade** ``[test_lint test_orm_import]``. Addon
runtime code imports from ``odoo.api``, ``odoo.fields``, ``odoo.models`` — never
from the ``odoo.orm`` package, whose internals are restructured freely by the
fork. ADR-0008 argues the boundary and ADR-0009 records how its scope was closed;
the freedom it buys is what ADR-0001's decomposition spends. Test files are exempt by location, since testing an internal
necessarily imports it.

**On running the formatter.** ``ruff format`` is deliberately not automated and has
no CI gate; ``.pre-commit-config.yaml`` runs ``ruff-check --fix`` and pointedly not
``ruff-format``. Formatting is whole-file, so running it over a file inherited from
upstream rewrites untouched lines and turns the next upstream merge into a conflict.

The rule is therefore about **what you write**: match the formatter's output in the
code you add or substantially rewrite, and leave the rest of the file alone.
Reformatting a whole file is a change in its own right — make it its own commit and
justify it.

2.2 Model class organisation
----------------------------

.. code-block:: python

   class SaleOrder(models.Model):
       _name = "sale.order"
       _description = "Sales Order"
       _inherit = ["mail.thread", "mail.activity.mixin"]
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

Omit sections you do not need. The section *names* are fixed; wrapping them in a
rule of dashes, as ``sale/models/sale_order.py`` does, is cosmetic and fine — be
consistent within a file. Adoption across the tree is partial; apply the layout to
files you create or substantially rework rather than churning files you are only
passing through.

Within ``# COMPUTE METHODS`` and ``# ONCHANGE METHODS``, define a method before the
ones that consume its output; beyond that, group related methods. No strict
ordering is mandated, and no tool checks it.

2.3 Field conventions
---------------------

**Group fields semantically, not by type** ``[review]``. Label each group with a
``# <Noun> block`` comment. This is expected on models with roughly ten or more
fields; small single-purpose models do not need it.

Ordering ``company_id`` after every ``Char`` and ``Boolean`` because it happens to
be a ``Many2one`` hides the fact that it is the context determining the behaviour
of every other field on the model. Semantic groups read like an invariant list.

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

Blocks are per-model — ``# GPS block``, ``# Harvest block`` are as legitimate as
``# Financial block``. Relational fields mix freely inside a block. Line models
open with the ``related=`` fields inherited from their parent, ``order_id`` first.

**Naming patterns**:

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

**The verb vocabulary** ``[review]``. The table above governs prefixes that carry an
ORM role. Every other method opens with a free verb, and the tree currently spells
single operations many ways: 141 stems are written with two or more verbs drawn from
one semantic family, and 146 groups of methods share a byte-identical body under
different names. One verb per operation. The abolished spellings are not
lesser-preferred synonyms — they are wrong.

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
     - returns state that already exists; does not build it
   * - Predicate
     - ``_is_`` ``_has_`` ``_can_``
     - —
     - returns ``bool``, never raises, no side effect
   * - Validation
     - ``_check_*``
     - ``_validate_`` ``_verify_`` ``_ensure_`` ``_control_``
     - **raises** on failure; a boolean answer is a predicate
   * - Mutation
     - ``_update_*``
     - ``_assign_`` ``_fill_`` ``_inject_``
     - writes to records; ``_set_*`` is reserved for ``inverse=`` targets
   * - Addition
     - ``_add_*``
     - ``_append_``
     - ``_insert_`` / ``_push_`` are reserved, not abolished — see below
   * - Removal
     - ``_remove_*``
     - ``_delete_`` ``_purge_``
     - ``unlink`` stays reserved for the ORM operation; so do ``_drop_`` /
       ``_discard_``

**Reserved, not abolished** ``[review]``. Four verbs look like synonyms of ``_add_``
and ``_remove_`` and are not — each is a term of art from a layer below the ORM, and
collapsing it destroys information:

.. list-table::
   :header-rows: 1
   :widths: 16 84

   * - Verb
     - Reserved for
   * - ``_drop_``
     - SQL DDL — ``_drop_table``, ``_drop_column``
   * - ``_insert_``
     - SQL DML and ordered insertion — ``_insert_cache``, ``insert_rows``
   * - ``_push_``
     - stack or queue semantics — ``push_protection``
   * - ``_discard_``
     - the ``set.discard`` contract: remove if present, never raise

Use them **only** with those meanings. A business method that deletes records is
``_remove_*``, never ``_drop_*``.

**The vocabulary governs model methods.** It applies to classes deriving from
``models.Model`` / ``TransientModel`` / ``AbstractModel``. The framework packages
below the ORM — ``odoo/db``, ``odoo/http``, ``odoo/tools``, ``odoo/orm`` internals —
legitimately speak SQL and Python data-structure vocabulary, and are out of scope.

**``_get_`` is not a default.** At 7,965 definitions it is 17.6 % of every method in
the fork, having absorbed reading, building, deriving and computing. The split that
matters is against ``_prepare_``: 1,681 definitions are payload builders — they end
in ``_vals``, ``_values``, ``_data``, ``_dict``, ``_domain`` or ``_context`` — yet are
spelled ``get_*``, against 957 already spelled ``_prepare_*``. Apply the discriminator
per method; the suffix alone does not decide it, because some of those genuinely
retrieve rather than build.

**Validation raises; predicates return.** ``_check_*`` (1,474 definitions) is
canonical and matches ``@api.constrains``. ``_validate_`` (194) plus ``_verify_``,
``_ensure_`` and ``_control_`` (119 together) are the same operation under four names.
A method that *answers* a question rather than enforcing one is ``_is_*`` / ``_has_*``
/ ``_can_*`` and must not raise.

**Do not name a method for the act of running** — *provisional*. ``_do_``, ``_run_``,
``_perform_``, ``_execute_``, ``_process_`` and ``_handle_`` (506 definitions) describe
execution rather than behaviour; every method executes. Name the domain operation:
``_post_entries``, not ``_do_posting``. ``_run_`` survives only as a scheduled-job
entry point. This rule has no mechanical rewrite — each site needs judgement.

**``_set_`` versus ``_update_``** — *provisional*. ``_set_*`` (368 definitions) and
``_update_*`` (357) are near-evenly split and the boundary between them is the
fuzziest in this section. The rule above reserves ``_set_`` for methods wired as an
``inverse=`` target, where the field wiring already fixes the meaning; everything else
that writes to records is ``_update_``. Expect to revisit it.

**``_post_`` is overloaded** ``[review]``. 242 definitions carry three unrelated
meanings — ``account.move._post`` (accounting), ``message_post`` (mail) and HTTP
handlers. Do not add a fourth: new code names the domain operation. The existing
three are load-bearing and are not renamed by this section.

**Adoption** ``[ratchet naming]``. As with §2.2, apply the vocabulary to methods you
create or substantially rework rather than churning files you are passing through.
``tooling/architecture/naming_vocabulary.py`` counts the definitions still using an
abolished verb and feeds the shared ratchet — ADR-0033 argues why this section is
counted rather than blocked, and which of its rules are deliberately left
uncounted because no checker can decide them::

    python tooling/architecture/naming_vocabulary.py --count \
        | xargs python tooling/ratchet/ratchet.py naming --count

It measures the **mechanically decidable** rules only — the abolished-verb list.
The ``_get_``/``_prepare_`` split and the two *provisional* rules are excluded by
design, because a floor nobody can lower by reading the rule is a floor people learn
to ignore; those stay ``[review]``. A rename must rewrite the XML ``name="…"``
bindings and JS references in the same commit — a Python-only refactor breaks them
silently and no gate catches that today.

**Never rename an inherited core method** ``[review]``. These rules apply to methods
you author. Core ships many ``button_*`` methods bound by name from XML and many
``action_open_*`` methods; renaming one breaks the binding and every
``super()`` caller. Override under the original name.

**An override's signature must match its parent's** ``[test_lint test_override_signatures]``.
Adding, removing or renaming a parameter — or changing its default — on an
override is a hard failure, not a style note. This is what makes
``@typing.override`` (§2.9.11) useful rather than decorative.

**Public methods may not take an ``ids`` or ``context`` parameter**
``[test_lint test_naming]``, because both collide with the RPC calling convention.

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
   * - ``_prepare_*`` / ``_get_*`` and other internals
     - ``# HELPER METHODS``
   * - ``_auto_init`` / ``init``
     - ``# HOOKS``

**Field wiring beats the name.** A method referenced by ``inverse="..."`` is an
inverse even if it is called ``set_*``; ``compute=`` and ``search=`` likewise pin
their targets. A method used as a field ``default=`` is evaluated at class-creation
time, so it must be defined *above* the field block and stays there.

``_search_display_name(self, operator, value)`` is the Odoo 19 API hook backing
``name_search``. Override it; ``_name_search`` no longer exists.

**Cache lifecycle verbs: ``invalidate_`` / ``clear_`` / ``reset_``.** [review]
These three are not interchangeable, and the core used them as though they were:
an audit in 2026-08 counted **20 such methods across 9 classes** in
``orm/runtime``, ``orm/components``, ``modules`` and ``db`` — ``clear``,
``clear_all``, ``clear_group``, ``clear_cache``, ``clear_all_caches``,
``clear_caches``, ``clear_catalog_facts``, ``invalidate``, ``invalidate_field``,
``invalidate_all``, ``invalidate_field_data``, ``reset``, ``reset_changes``,
``reset_triggers``, ``reset_field_metadata``, ``reset_modules_state`` — with
nothing stating what separated them. ``Transaction.clear()`` and
``Transaction.invalidate_field_data()`` drop overlapping-but-different sets;
``FieldCache`` has both ``invalidate_all()`` and ``clear()``. Cache-coherency
bugs are the most expensive class of bug in this system, and that was the
vocabulary they are reasoned about in.

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
     - Drop everything held, unconditionally. A *lifecycle* operation —
       teardown, or handing the object to a new owner.
     - Leaking one transaction's or database's state into the next.
   * - ``reset_*``
     - Rebuild derived state **from its source**. Not a drop: the state exists
       again afterwards.
     - Reasoning over a derived structure that no longer matches what derived it.

Pick the verb by what the caller needs, and do not add a fourth. When a method
would honestly need two of them, it is doing two things.

2.5 Docstrings and comments
---------------------------

Mandatory on models and on non-trivial methods ``[review]``. Simple accessors may
omit them.

**No linter enforces docstring presence anywhere in this repo** ``[review]``.
``ruff``'s ``D`` rules (pydocstyle) are not selected, and the ``ruff_docstring``
ratchet that used to floor them is retired. ``eff67f80316`` stripped comments and
docstrings from ``odoo/`` deliberately; what it left was a floor payable only by
re-adding what the strip had removed, which made it a gate against its own
project's intent. Presence is therefore a **review** expectation everywhere —
core and addons alike — not a mechanical one.

Accuracy is still mechanical, and the distinction is the point. ``DOC``
(pydoclint) remains selected and fires only on docstrings that *exist*: an
extraneous ``:param:``, a documented exception that cannot be raised. Nothing
obliges you to write one; writing a wrong one still fails.

Two bodies of docstrings are load-bearing rather than prose and must not be
removed. ``odoo/cli/`` docstrings are the CLI's user-facing help text —
``help.py`` renders ``cmd.__doc__``, ``command.py`` feeds it to argparse, and
``upgrade_code.py`` calls ``__doc__.replace()``, which raises ``AttributeError``
the moment it becomes ``None``; eight ``base`` tests gate them. A handful more are
machine-checked contracts read by ``tooling/architecture/`` and ``tests/service/``
— ``orm/__init__.py``, ``orm/models/mixins/_metadata.py``, ``service/__init__.py``,
``service/db.py`` and ``http/tests/test_openapi.py``. Deleting either kind breaks
a test, not a style gate.

Where a docstring *does* document parameters, its fields must agree with the
signature ``[test_lint test_docstring]``: a ``:param:`` for an argument that does
not exist, or a ``:rtype:`` contradicting the annotation, is a failure.

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
* Field-by-field listings belong in each field's ``help=``, not in the class
  docstring.
* ``"""triple double quotes"""``, never ``'''single'''``.

**Accuracy and concision.** A docstring or comment that contradicts the code is
worse than none: it misleads and outlives what it described. Update it in the same
edit that changes a signature, a return type or a behaviour.

* **Be correct.** Verify every claim — parameters, return type, exceptions,
  referenced methods — against the code. Delete stale references rather than
  letting them rot.
* **Be direct.** Cut *Basically*, *Essentially*, *Note that*, *This method simply*.
  Use the imperative: "Return…", "Raise…", "Compute…".
* **Do not restate the obvious.** A docstring that echoes the method name, or
  retypes the signature already on the ``def`` line, is noise.
* **Comments explain why, not what.** Reserve them for a non-obvious rationale, an
  invariant, or an edge case. A comment narrating the next line has earned its
  deletion.

2.6 ORM
-------

**Always ``super()``** in ``create``, ``write``, ``unlink``, ``copy_data``,
``default_get`` and ``_compute_display_name`` ``[review]``. Prefer overriding
``copy_data`` over ``copy`` — it is the values hook ``copy`` is built on.

**Override ``create`` in batch form** ``[review]``:

.. code-block:: python

   @api.model_create_multi
   def create(self, vals_list):
       for vals in vals_list:
           ...
       return super().create(vals_list)

**Every model declares ``_name`` and ``_description``** ``[review]``. Set ``_order``
when insertion order is wrong. For the record label set ``_rec_name``, or override
``_compute_display_name`` calling ``super()``; ``name_get`` no longer exists.

**Deletion constraints use ``@api.ondelete``** ``[test_lint E8506]``. A ``raise``
inside an ``unlink()`` override fails the checker — the override runs at uninstall
too, and blocks it.

.. code-block:: python

   @api.ondelete(at_uninstall=False)
   def _unlink_if_draft(self):
       if any(r.state != "draft" for r in self):
           raise UserError(self.env._("Cannot delete a confirmed order."))

**The framework owns transactions.** Do not call ``self.env.cr.commit()`` or
``rollback()`` from business code. Only the framework, the cron runner and code
holding its own cursor (``self.env.registry.cursor()``) may commit.

**Assign fields directly in computes** (``self.field = value``). Calling ``write()``
in a compute recurses.

**``ensure_one()``** at the top of any method that assumes a single record.

**Context is a frozen dict** — propagate with ``with_context``. For company scoping
use ``with_company``: ``force_company`` stopped being honoured in 19.0.

.. code-block:: python

   order.with_context(tracking_disable=True).action_confirm()
   order.with_company(company).action_confirm()   # not with_context(force_company=...)

**``force_company`` fails silently, so grep for it rather than waiting for an
error.** ``with_context(force_company=...)`` emits a ``DeprecationWarning`` and
otherwise does nothing: no exception is raised, the key stays in the context, and
nothing reads it. Surviving call sites therefore run against the *wrong company*
without any runtime signal — the reason this is worth a targeted search rather
than an opportunistic fix.

**Prefer recordset operations** — ``filtered``, ``mapped``, ``sorted`` — over manual
loops, and ``odoo.tools.groupby`` over ``itertools.groupby``: it handles recordsets
and does not require pre-sorting.

**Think extendable.** Avoid hard-coded values that should be configuration. Split
methods so another module can override one piece without copying the rest.

**Deprecate explicitly**:

.. code-block:: python

   @api.deprecated("Since 19.0, use _prepare_invoice_vals instead")
   def _prepare_invoice(self):
       return self._prepare_invoice_vals()

Performance rules for the ORM — counts, aggregation, batching, N+1, indexing,
locking, ``ormcache``, cron batching — live in **§11**, which is their single
source.

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
     - Invalid arguments to internal methods — never user-facing

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

**Fail closed.** Handlers in state-mutation code must leave the system consistent.
Wrap each iteration in a savepoint so a failure rolls back or transitions to an
explicit error state:

.. code-block:: python

   for order in orders:
       try:
           with self.env.cr.savepoint():
               order._process_payment()
               order.action_confirm()
       except UserError:
           order.state = "error"
           _logger.error("Failed to process order %s", order.name, exc_info=True)

In financial or state-mutation code, log-and-continue is a violation.

``except Exception`` is ``[review]`` — ``BLE001`` is disabled in ``ruff.toml``
because Odoo legitimately catches ``Exception`` around external and ORM calls.
Use it for catch-log-reraise and for integration adapters, not as a default.

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

An overriding controller re-declares the route with ``@route()``, but **must not
restate attributes it does not change** ``[test_lint test_routes]`` — repeating
``type=`` and ``auth=`` at their inherited values hides what the override actually
modifies.

Security rules for controllers are in §10.6.

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
     - suppress mail tracking on ``write()`` — for bulk imports

A field may carry its own context for relational access:

.. code-block:: python

   child_ids = fields.One2many("res.partner", "parent_id", context={"active_test": False})

2.9.4 Monetary fields
~~~~~~~~~~~~~~~~~~~~~

``fields.Monetary`` needs a companion currency. A missing one is caught by an
``assert`` in ``Monetary.setup_nonrelated`` / ``setup_related``, so it fails when
the registry is built — at module load, not on first use — and, being an
``assert``, not at all under ``python -O`` (§10.3):

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
     - —
   * - Translations
     - ``%s`` / ``%(name)s`` args to ``self.env._()``
     - f-strings — extraction silently breaks
   * - Logging
     - ``%s`` args to the logger
     - f-strings ``[ruff G004]``
   * - SQL parameters
     - ``%s`` placeholders
     - f-strings — injection ``[test_lint E8501]``
   * - HTML in errors
     - ``%``-style or ``.format()`` inside ``Markup()``
     - f-strings — XSS

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
``TypeError``. Note that Odoo pins the process timezone to UTC at startup, so
inside a running server the OS-local zone *is* UTC — a discrepancy you reproduce
outside Odoo is usually an artefact of the harness, not a bug.

2.9.7 ``Command`` for x2many writes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use ``odoo.fields.Command`` ``[review]``; the raw magic tuples are unreadable and
easy to get wrong.

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

**Never declare UNIQUE over a translated column**
``[test_lint test_translated_unique]``. A ``translate=True`` field is stored as
``jsonb``, so the constraint compares whole translation *documents* rather than
values: two rows stop colliding the moment one carries a language the other does
not. That is not a later translation step — it is the next create, because Odoo
writes the active language alongside the source term. The rule enforces nothing
from then on, silently, and only in databases that have a second language, which
is why it survives review and testing.

Use ``name_uniq_index()`` from ``odoo/addons/base/models/catalog_mixin.py``,
which indexes the source term. It has to be a ``models.UniqueIndex`` rather than
a ``Constraint`` because the comparison is an expression and PostgreSQL allows
none in a UNIQUE constraint:

.. code-block:: python

   # CONSTRAINTS
   _name_src_uniq = name_uniq_index(
       "company_id",
       message="A template with this name already exists for this company.",
   )

When **converting an existing** ``UNIQUE(name, ...)``, pass
``nulls_distinct=True`` so only the comparison changes. The helper otherwise
defaults to ``NULLS NOT DISTINCT``, which is right for a catalog adopting the
rule for the first time but tightens what the old constraint permitted: a plain
UNIQUE never fired for two rows sharing a NULL scope column, and code relies on
that (``res.groups`` holds several same-named groups with no privilege).

2.9.9 Onchange
~~~~~~~~~~~~~~

``@api.onchange`` takes plain field names — dotted paths are silently ignored. The
method runs on a pseudo-record that may not exist in the database, so calling any
CRUD method on it is undefined behaviour; assign fields or call ``update()``.

**Returning a domain from an onchange is forbidden**
``[test_lint test_onchange_domains]``. Dynamic domains belong on the field
(``domain=``) or in the view, where they survive the round trip. An onchange may
still return a ``warning`` dict.

A One2many or Many2many field cannot modify itself through an onchange — a
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
pairs with the signature gate in §2.4: together they turn a renamed or re-signed
parent from a silent behaviour change into an error.

2.9.12 Float and currency comparison
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Never compare floats or ``Monetary`` values directly.** Use the ORM helpers:

.. code-block:: python

   from odoo.tools import float_compare, float_is_zero, float_round

   rounding = order.currency_id.rounding
   if float_is_zero(line.price_subtotal, precision_rounding=rounding):
       ...
   if float_compare(paid, total, precision_rounding=rounding) >= 0:    # paid >= total
       order.state = "paid"
   amount = float_round(raw_amount, precision_rounding=rounding)

Pass ``precision_rounding=<currency>.rounding`` or ``precision_digits=<n>``. Do not
invent epsilons.

``[ruff RUF069]`` covers ``==`` and ``!=`` **only**, and only where it can infer
that both operands are floats. Ordering comparisons (``<``, ``>``, ``<=``, ``>=``)
and anything behind a recordset attribute are ``[review]``. Treat the linter as a
backstop, not as coverage.

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
     - unhandled exceptions and data corruption — with ``exc_info=True``

Pass arguments lazily; f-strings in a logging call are linted ``[ruff G004]``, and
eagerly stringifying an argument is too ``[ruff RUF065]``.

For cross-model flows (invoicing, EDI, payments) put a correlation identifier in
every line so one business transaction can be traced end to end:

.. code-block:: python

   _logger.info("[order:%s] Starting invoice creation", order.name)
   _logger.info("[order:%s] PAC stamping completed, UUID: %s", order.name, uuid)

2.9.14 Background jobs (``ir.job``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For deferred one-off work use the framework job queue — not ad-hoc threads, not
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
  refuses to run anything undecorated — a hand-crafted ``ir_job`` row cannot call
  arbitrary code.
* Arguments must be **JSON-serialisable**. Pass ids, not recordsets or datetimes;
  the records the job targets ride on ``delayed()``'s own recordset.
* Write bodies **idempotent or transaction-safe**. Completion is atomic with the
  job's writes, so partial effects never survive a crash — but external side
  effects (HTTP calls, mail) need their own guards.
* Transient failures raise ``RetryableJobError(seconds=...)``; any other exception
  also consumes one of ``max_retries`` before the job is marked failed. Both roll
  the job's transaction back.
* **Not finished is not failed.** When the body cannot complete because something
  outside it is not ready yet — a remote service still preparing an answer, a file
  that has not landed — call ``self.env["ir.job"]._defer(seconds, reason=...)`` and
  return normally. The job's writes are kept and committed, ``retry`` is untouched,
  nothing is recorded in ``exc_*``, and the job keeps its ``identity_key`` so a
  caller cannot queue a duplicate while it waits. Deferrals have their own budget,
  ``max_defers`` ``[review]``:

  .. code-block:: python

     @api.job(channel="sat", max_retries=3, max_defers=24)
     def _poll_remote_package(self):
         self._record_progress()          # kept, whatever happens next
         if not self._package_ready():
             self.env["ir.job"]._defer(600, reason="still preparing")

  Do not reach for ``RetryableJobError`` here: it is an exception, so the progress
  the poll just recorded is rolled back, and it spends a retry per attempt — an
  hour of honest polling would report a healthy request as a permanent failure.
  Re-enqueueing a fresh job from inside the body does not work either: a running
  job is in a queued state and still holds its ``identity_key``, so the enqueue is
  silently dropped and the chain ends after one attempt.
* Concurrency is bounded per **channel**. A channel absent from ``ir.job.channel``
  has an implicit capacity of 1 — give heavy integrations their own channel
  instead of tuning priorities.
* Chain with ``delayed(after=job)``, fan in by passing a union, and collapse bursts
  with ``identity_key``. A deferral does **not** release dependents: the job has
  not delivered yet.
* Defaults: ``channel="root"``, ``priority=10``, ``max_retries=5``,
  ``max_defers=100``.
* Ops surface: Settings → Technical → Automation → Background Jobs. Smoke-test a
  deployment with ``env["ir.job"].delayed()._job_ping()``.

2.10 Lazy imports
-----------------

**Imports go at module level unless there is a documented reason.** Imports inside
functions hide dependencies, duplicate across methods and defeat module-graph
analysis. ``PLC0415`` is globally suppressed because Odoo's architecture genuinely
requires some lazy imports — which makes this a ``[review]`` rule, and makes the
explanatory comment mandatory.

Acceptable reasons:

#. A **circular dependency** that cannot be restructured away:

   .. code-block:: python

      def json_default(obj):
          from odoo import fields  # circular: tools -> fields
          ...

#. An **optional external dependency**, guarded by ``try`` / ``except ImportError``.
#. **CLI startup cost** — keeping ``--help`` fast.
#. **``import odoo.addons``**, whose ``__path__`` is populated at runtime.
#. **Addon model imports from framework code**, which are not registered at
   framework import time.

"Just in case" and precautionary laziness are not reasons. If the same import
appears in two functions of one file, promote it.

----

3. XML
======

3.1 Format
----------

Formatting and ordering are **owned by fixers** — do not hand-align
``[test_lint test_pretty_xml, test_xml_records]`` ``[fixer _pretty_xml, _sort_xml_records]``.
Run the sorter first and the formatter last: the formatter preserves order, the
sorter does not preserve formatting.

The conventions they enforce:

* 4-space indentation; root element ``<odoo>``, not ``<data>``.
* Double-quoted attribute values; empty elements self-close.
* Attribute order: ``id`` then ``model`` on records; ``name`` first on fields.
* One blank line between top-level records, and after ``<odoo>`` / before ``</odoo>``.
* 88 columns; a tag exceeding it wraps one attribute per line. A single attribute
  longer than 88 — a large ``domain`` or ``context`` — stays on its own line.
* ``domain``, ``context`` and ``options`` values go on **one line**. XML normalises
  newlines inside an attribute value to spaces, so a multi-line form is purely
  cosmetic and cannot survive the formatter.

3.2 XML IDs
-----------

**Prefix style** — role first, entity second ``[review]``. This matches Odoo
Community core, so new records sit beside the core records they relate to and no
mental translation is needed when you ``ref`` one.

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

A few legacy core ids are model-first (``sale_order_menu``, ``sale_menu_root``) and
multi-company rules keep the core ``{model}_comp_rule`` form. Leave them; ``ref``
their real id.

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

**List** — ``<list>``, never ``<tree>``:

.. code-block:: xml

   <list multi_edit="1">
     <field name="name"/>
     <field name="amount_total" sum="Total"/>
     <field name="state" decoration-success="state == 'done'"/>
     <field name="technical_field" column_invisible="True"/>
     <field name="optional_field" optional="hide"/>
   </list>

**Search** — inside a ``<search>``, ``<group>`` no longer accepts ``string`` or
``expand``; both are rejected by view validation. ``name``, ``invisible``,
``groups``, ``colspan`` and ``col`` remain valid, and ``name`` is expected here as
everywhere else so inheritance has a stable target. Every filter needs a ``name``
too, so it can be reached by XPath:

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

**Kanban** — the card template is ``t-name="card"``, and the CSS classes are
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

TransientModel views live in ``wizards/``:

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

No ``<sheet>``, no ``<header>``, no ``<chatter/>``. Buttons go in ``<footer>``, which
renders at the dialog's bottom. ``res.config.settings`` is a wizard and belongs here.

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

Prefer ``name=`` targets over positional XPath. Positions are ``inside``, ``after``,
``before``, ``replace`` and ``attributes``; ``position="replace"`` with empty content
deletes an element. ``hasclass()`` targets by CSS class.

3.6 QWeb reports
----------------

Three parts — document template, wrapper, action:

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
optional — a PDF base-filename hint that core often omits. ``binding_type`` is
``"report"`` (Print menu) or ``"action"``; ``binding_view_types`` is
order-significant and is most often ``list,kanban``. Use ``t-lang=`` at the
``t-call`` level to localise.

3.6.1 PDF rendering is WeasyPrint
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This fork renders ``qweb-pdf`` with **WeasyPrint** and real CSS Paged Media.
wkhtmltopdf is gone; so is its folklore. The engine is ``WeasyPrintEngine`` in
``odoo/addons/base/models/ir_actions_report.py``; the paged-media CSS is
``addons/web/static/src/webclient/actions/reports/report_paged_media.css`` and
``report_pdf_layout.css``, both with substantial header comments.

**Layout**

* Bootstrap **5** class names only. ``text-right`` / ``text-left`` no longer exist
  and fail silently — use ``text-end`` / ``text-start``, ``float-end``, ``ms-*`` / ``me-*``.
* Responsive breakpoints (``col-md-*``, ``d-md-*``) are meaningless in paged media.
  Core layouts branch on ``report_type == 'pdf'`` and use CSS Grid there
  (``o_report_header_*``, ``o_report_footer_grid``). Follow that; do not lay out
  with ``<table>``.
* Report CSS goes in an SCSS file added to ``web.report_assets_common`` — it
  benefits from the process-wide parsed-CSS cache — not in inline ``<style>`` blocks
  or ``style=`` attributes. Consume the per-company design tokens (``--co-primary``,
  ``--co-font``, ``--rp-*``) instead of hard-coding colours.

**Paperformat**

Live fields: ``format`` / ``page_width`` / ``page_height``, ``margin_*`` (mm),
``orientation``, ``header_line``, ``css_margins``.

``dpi``, ``header_spacing`` and ``disable_shrinking`` still exist on the model but
are wkhtmltopdf-era and inert — do not set them on new paperformats. Header and
footer size is controlled by ``margin_top`` / ``margin_bottom``; the ``.header`` and
``.footer`` divs become CSS running elements in the page margin boxes.

**Paged-media toolbox**

* Page numbers: ``<span class="page"/>`` and ``<span class="topage"/>``, backed by
  CSS counters. Never JavaScript.
* Break control: ``o_page_break_before`` / ``o_page_break_after``,
  ``break-inside: avoid``, and ``o_thead_no_repeat`` to stop a ``<thead>`` repeating
  on long tables.
* PDF outline: ``bookmark-level`` is set on ``h2[name="document_title"]`` and
  ``h3[name]``, so real headings give multi-record batches a navigable outline for
  free.
* Also supported, and preferable to hacks: ``string-set`` running headers
  ("Invoice X — continued"), ``target-counter()`` with ``leader('.')`` for tables of
  contents and cross-references, named ``@page`` rules for landscape annexes, and
  ``float: footnote`` for legal boilerplate.
* PDF/A-3 with Factur-X and XMP metadata is native — see ``_build_pdf_options``.
  The same ``data["__pdf_options__"]`` channel takes ``dpi`` and ``jpeg_quality``,
  the two file-size levers for image-heavy reports.

**Engine services** — no template work required

* **Metadata**: ``/Title`` is the evaluated ``print_report_name`` (falling back to
  the action label); ``/Author`` the company, ``/Creator`` ``Odoo``, ``/Lang`` the
  record's language, which also switches on ``hyphens: auto``.
* **Watermark**: ``with_context(report_watermark="DRAFT")`` stamps text diagonally
  on every page of that print.
* **Themes**: ``report.theme`` (Settings → General → Document Layout) emits the
  ``--rp-*`` tokens per company via ``web.styles_company_report``. New report CSS
  consumes tokens; it never hard-codes.
* **Diagnostics**: WeasyPrint CSS warnings are captured per render. A failed render
  names the offending rule in its ``UserError``; successful renders log warnings at
  DEBUG.

In test mode ``_render_qweb_pdf`` returns raw HTML unless ``force_report_rendering``
is set. Render-path tests are in ``odoo/addons/base/tests/test_reports.py``.

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

Every menuitem in a module goes in ``views/ir_ui_menu_views.xml`` — not scattered
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
from the first 500 bytes of the file by ``odoo/tools/assets/esm_graph.py`` — not a
cosmetic header. Files under ``static/src`` and ``static/tests`` are routed by path,
so the bare form is optional there. Write it explicitly when you need a modifier,
or for a file outside those paths:

* ``@odoo-module ignore`` — keep the file out of the ESM pipeline (a classic script
  or vendored library).
* ``@odoo-module native`` — treat as a true native ES module.
* ``@odoo-module alias=<specifier>`` — register under an additional import path.
* ``@odoo-module default=<name>`` — control default-export bridging.

Two asset mistakes take a whole page down while the HTTP response stays ``200``,
because the pipeline degrades rather than raises. Both are cheap to check and
neither is caught by a module's own test suite:

* **Every ``@addon/...`` import must resolve to a file.** esbuild fails the
  *entire bundle* on one unresolvable specifier, and a failed build is served as
  an empty one. A module moved inside ``web`` therefore blanks the web client of
  every database carrying an addon that still imports the old path — including
  addons that are not installed on yours ``[test_lint test_esm_specifiers]``.
  ADR-0023 records the second half of this: a specifier that does not resolve in
  a *test* file registers no suite at all, so the run reports fewer tests rather
  than an error.
* **A bundle rendered by ``t-call-assets`` must be declared under the manifest's
  ``esm`` key if it carries ES-module sources.** Undeclared, it is concatenated
  as legacy JS and every module-syntax file in it is replaced by a
  ``console.error`` stub, so the page boots into nothing. A bundle that only
  ever gets ``('include', ...)``-ed into another needs no declaration of its own
  ``[test_lint test_esm_bundles]``.

Run both after any move, rename or new bundle — they take about two seconds::

   odoo-bin -d <db> -i test_lint --test-enable --stop-after-init --no-http \
       --test-tags '/test_lint:TestEsmSpecifiers,/test_lint:TestEsmBundles'

Under ``--test-enable`` or ``--dev=assets`` a failed esbuild build now **raises**
(``EsbuildBundleError``) instead of degrading to an empty bundle. A run that
dies naming a bundle is reporting a real breakage in it — the same breakage
that, in production, shows up as a page that loads with no JavaScript. Do not
work around it by ignoring the bundle; fix the import or the declaration. The
escape hatch, for a run that has to survive a known-broken bundle, is
``ir.config_parameter`` ``web.esbuild.fail_closed = 0``.

4.2 Naming
----------

* Components ``PascalCase``; methods and variables ``camelCase``.
* **When JS names a Python method, the string must match exactly.** An ORM call or
  a button ``name`` targeting ``action_view_invoices`` uses that name verbatim. This
  is about the call target, not about frontend handlers.
* Portal template ``t-name`` values follow the field naming conventions
  (``invoice_state``, not ``invoice_status``).

4.3 OWL
-------

4.3.1 Rules
~~~~~~~~~~~

* **``super.setup()`` first** when patching — before anything else.
* **``useState`` for reactive state.** A plain assignment does not re-render.
* **Verify import paths.** Odoo moves components between releases; assume recalled
  paths are stale.
* **POS: ``t-inherit`` for markup, ``patch`` for behaviour.** Reserve ``onMounted``
  DOM access for measurement and focus — raw DOM injection breaks on re-render.

4.3.2 ``this`` in a template is not always the component
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

OWL renders against a *derived* context, not the component
(``addons/web/static/lib/owl/owl.es.js``)::

   const ctx = Object.assign(Object.create(this.component), { this: this.component });

Template expressions compile to lookups on ``ctx``. Because ``ctx`` only *inherits*
from the component, **reads** always resolve, but a **write** to a bare instance
property lands on ``ctx`` — a per-render throwaway, invisible to the component and
gone on the next render.

.. list-table::
   :header-rows: 1

   * - Reference in the template
     - ``this`` inside the member
     - Bare ``this.x = …``
   * - ``this.foo()``
     - the component
     - safe
   * - ``t-on-click="foo"``
     - the component — invoked as ``handler.call(node.component, ev)``
     - safe
   * - ``onFoo.bind="foo"``
     - the component
     - safe
   * - ``foo`` / ``foo.bar`` (bare getter or method)
     - the derived ``ctx``
     - **lost**

Only the last row is dangerous, and it fails silently. Two corollaries:

* ``this.someObject.key = v`` is safe everywhere — the *read* resolves through the
  prototype chain to the component's object and the mutation lands on it. Only
  rebinding the property itself (``this.counter = 1``) is lost.
* A member reached transitively binds like its entry point: a bare template getter
  calling ``this.helper()`` still runs ``helper`` on ``ctx``.

When a bare template member must persist something, mutate a container object
created in ``setup()`` — see ``Many2XAutocomplete.emptySearchMemo``, which exists
for exactly this reason.

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

Frontend changes ship with a test ``[review]``. QUnit is removed — do not write it.

* **Unit and component tests — Hoot.** ``static/tests/**/*.test.js``, importing from
  ``@odoo/hoot`` and ``@odoo/hoot-dom``, with the mock server for ORM calls. This is
  the default.

  .. code-block:: javascript

     import { expect, test } from "@odoo/hoot";
     import { click } from "@odoo/hoot-dom";

     test("counter increments on click", async () => {
         await click("button.increment");
         expect("span.value").toHaveText("1");
     });

* **Integration and end-to-end — tours.** Register in the ``web_tour.tours`` registry
  and drive from a Python ``HttpCase`` tagged ``@tagged("post_install", "-at_install")``
  via ``self.start_tour(url, "tour_name", login=...)``. Use tours for flows spanning
  backend and UI.

Two operational facts about the Hoot runner, which cost more debugging time than
any other frontend issue here:

* **The unit-test bundle is not rebuilt while the server runs** — not for XML, not
  for a new ``.test.js``, not for a plain source edit. Restart the server after
  every change; a green run only proves the bundle you built.
* **An import failure reads as a lower pass count, never as a failure.** Always read
  the import-failure line in the output rather than trusting "Passed N".

JavaScript is also covered by the ESLint and ``tsc`` ratchets (see *The ratchets*).
Neither is expected to be clean; neither may get worse.

----

5. CSS / SCSS
=============

5.1 Naming and organisation
---------------------------

* Module-prefixed classes: ``.o_module_name_element``.
* Files in ``static/src/scss/`` (or colocated with the component they style).
* Declared in ``__manifest__.py`` under ``assets``, in the bundle that loads where
  the style is needed. Wrong-bundle CSS either does nothing or bloats every page.

.. list-table::
   :header-rows: 1

   * - Bundle
     - Loads in
   * - ``web.assets_backend``
     - backend web client — most module UI
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

* **Bootstrap first.** The UI is Bootstrap 5 — reuse its utilities and components
  before writing SCSS.
* **Override variables, not values.** Customise through Odoo and Bootstrap SCSS
  variables injected into ``web._assets_primary_variables`` (or
  ``_secondary_variables``). Never hard-code a colour or spacing a variable
  already controls.
* **Dark mode** is file-based: a ``*.dark.scss`` sibling is globbed automatically
  into ``web.assets_backend_dark`` / ``web.assets_web_dark``. Put dark overrides
  there and drive colours from variables — do not hard-code light-only hex values.
* **RTL** is generated automatically. Use logical properties
  (``margin-inline-start``) and Odoo's RTL-aware mixins, not hard ``left`` / ``right``.

5.3 Browser floor
-----------------

**Current evergreen browsers. This fork does not support old ones, and no
declaration carries a fallback for them.** ``[review]``

The JS side has said this for a while — ``_ESBUILD_TARGET = "es2023"`` in
``odoo/tools/assets/esbuild.py`` — and the CSS side said nothing at all, so
authors have been guessing conservatively: ``color-mix()`` appears in 26 files
and ``light-dark()`` in none. It is written here so the guess stops.

Anything **Baseline newly available** may be used directly, in every bundle,
including the ones served to the public:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Use
     - Instead of
   * - ``color-mix(in srgb, C N%, transparent)``
     - ``rgba($c, .N)`` — Baseline *widely* available, the workhorse
   * - ``hsl(from C h s calc(l - 10))``
     - ``darken($c, 10%)`` — reproduces the Sass value exactly, HSL for HSL
   * - ``light-dark(a, b)``
     - a one-off colour that differs by scheme and deserves no token name
   * - ``oklch(from C calc(l - .1) c h)``
     - a *deliberate* palette change: perceptually uniform, so a step looks the
       same on yellow as on blue. It does **not** reproduce ``darken()``

The point is not novelty. A Sass colour function resolves when the bundle
compiles, which is why this fork ships every stylesheet twice; the CSS
equivalents resolve in the cascade, which is what lets one stylesheet answer
both colour schemes. ``test_lint``'s ``TestSchemeDuplication`` measures the
distance still to go.

``contrast-color()`` is the exception, and on semantics rather than support: it
returns only white or black, while ``o-scheme-contrast()`` picks among four
foregrounds — ``website`` puts ``$color-contrast-dark`` on ``o-color("900")``
so a frontend label lands on ``#212529``. Contrast picks stay compile-time and
published per scheme.

5.4 Moving a variable onto a token
----------------------------------

``o-token(--name, $fallback)`` turns a Sass assignment into a ``var()``, so the
value is decided in the cascade and one declaration answers both schemes. Two
things make a variable ineligible, and only the first announces itself.
``[review]``

* **It is read by Sass colour maths.** ``darken()``, ``mix()``, ``rgba()``,
  ``color-contrast()`` and friends take a colour, and a ``var()`` is not one.
  Sass raises ``$color: var(…) is not a color`` and the bundle fails to compile,
  so this is caught the first time it is run. Grep the whole workspace before
  converting — ``$card-bg`` is read by ``color-contrast()`` from ``portal``, four
  addons away from where it is assigned.
* **It is interpolated into an SVG data URI.** ``$form-check-*-color`` reaches
  ``stroke='#{…}'`` inside ``url("data:image/svg+xml,…")``. A custom property
  there is inert: the URI is not CSS, so the ``var()`` neither resolves nor
  errors — the compile succeeds and the icon simply stops being drawn. Nothing
  reports it. Convert the variable only alongside the image that reads it, or
  leave both and restate the pair under the scheme scope.

The same applies to a value handed to a mixin: ``o-button-variant-from()`` and
``o-print-color-rgb()`` accept tokens deliberately and say so, but a mixin that
was written for colours will fail on the first function it reaches.

5.5 Restating a rule for the other scheme
-----------------------------------------

When neither a token nor ``light-dark()`` can carry a value — a
``color-contrast()`` pick, a ``shift-color()``, a variable a colour function
reads — the rule is restated under ``:root[data-color-scheme="dark"]``, which
outscores the plain rule (0,2,0) against (0,1,0). ``scheme_rules.scss`` and
``html_editor.scheme_rules.scss`` are where those live. ``[review]``

* **One rule per original rule, with its whole selector list.** Grouping three
  of Bootstrap's ``:focus`` rules into one scoped rule answers *none* of them,
  and ``.navbar-dark`` alone does not answer
  ``.navbar-dark,.navbar[data-bs-theme=dark]``. Copy the selector as the bundle
  emits it.
* **Only the dark half.** Whatever emits the light half already did so.
* **Screen only.** ``assets_web_print`` includes the backend bundle and is
  linked unconditionally, so an unscoped block answers the attribute in print.
* **Not where it cannot apply.** A file riding ``assets_frontend`` should not
  carry the dark half: nothing there sets the attribute. Split it into a
  sibling declared in the backend bundle alone —
  ``html_editor.scheme_rules.scss`` exists because emitting it from the shared
  file put 24 KB on every public page.
* **Never call ``tint-color()`` or ``shade-color()`` from a scoped block.** The
  dark bundle carries ``bs_functions_overridden.dark.scss``, which redefines
  both — in dark, tint mixes with *black*. Calling Bootstrap's own function from
  a light bundle therefore computes the light meaning of the word, and the two
  bundles disagree about a colour they both call dark. Use
  ``o-scheme-tint(…, $-scheme)`` / ``o-scheme-shade(…, $-scheme)``, which take
  the mix colour from the scheme. The same applies to anything else a dark-only
  file redefines; ``TestSchemeDuplication`` is what catches it, because the
  restated rule simply keeps disagreeing.
* **``@extend`` does not compose with a scope** unless what the placeholder
  emits carries no colour, in which case the light half already answers and the
  dark half must simply omit it. See ``o-bg-color()``'s
  ``$extend-heading-reset``.

----

5.6 Weighing a conversion
-------------------------

**Weigh the bytes.** A ``var(--name, <fallback>)`` is longer than the colour it
replaces, once per use. Converting ``$focus-ring-color`` — read by
``$focus-ring-box-shadow``, which Bootstrap composes into a dozen rules — added
34 KB to every backend bundle and answered nothing, because the composed shadow
had already been flattened into a string by the time it reached the token. Read
the compiled size alongside ``TestSchemeDuplication``'s count; a conversion that
moves neither is a conversion to drop.

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
   * - **1 — Component**
     - ``odoo/orm/components/tests/`` and the other ``pytest`` suites
     - Exercising ORM algorithms in isolation — cache, compute scheduling, flush
       convergence, trigger graph — against the real component objects. No fields,
       no ``@api.depends``, no ``odoo`` imports. Milliseconds.
   * - **2 — ORM, database-free**
     - ``model_test_env`` / ``ModelRegistry`` (``odoo/orm/model_test_env.py``)
     - Real model methods, real ``@api.depends`` computes and real ``Field``
       descriptors against an in-memory backend. No PostgreSQL.
   * - **3 — Integration**
     - ``TransactionCase`` / ``HttpCase``
     - Anything needing SQL, ACLs, several modules, or the web client.

Tier 1's hand-rolled dependency graph *is* the subject under test; it deliberately
does not reuse Tier 2's real ORM. That is intentional, not duplication.

Tiers 1 and 2 are plain ``pytest``, and need **two invocations** — Tier 1 registers
process-global ``sys.modules`` stubs that would shadow Tier 2's real imports:

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

**Contract tests** pin the behaviour of our *dependencies* — psycopg's exception
hierarchy, what ``pg_dump`` emits, how ``psql`` lexes a meta-command, whether
``Popen`` closes its pipes — rather than our own logic. They exist because every
defect found in the July 2026 service-layer audit was an assumption mismatch, not a
logic error: the mocks were internally consistent, thoroughly exercised, and encoded
the wrong external behaviour, with nothing comparing them to the real thing. Write
one whenever code branches on how a dependency behaves, and assert the dependency
directly — a version bump then fails in a test that *names the assumption* instead
of silently re-opening the defect several modules downstream.

The suite skips when a dependency is missing, which is safe locally but means a
green run may have compared nothing. CI sets ``ODOO_CONTRACT_REQUIRE_DEPS=1`` to
turn a missing dependency into a failure there.

**Process tests** assert only what an outside observer can see: a listening port, a
process tree, an HTTP response. The suite is deliberately tiny — almost everything
about the service layer is covered far more cheaply by the mock-based suites in
``tests/service``. Add one only for behaviour that emerges from real processes and
vanishes the moment anything is mocked: a listen socket surviving a re-exec, a
master replacing a killed child, a bounded thread pool under real half-open sockets.
Two rules keep it from rotting into a flaky suite nobody trusts:

* Assert on observables, never on internal state — otherwise it is a slow unit test.
* **Readiness is a served request, never a log line.** ``ThreadedServer.run`` spawns
  the WSGI server and logs "HTTP service (werkzeug) running" *before*
  ``preload_registries``, both under ``Registry._lock`` — so the socket accepts and
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
     - controllers, web UI, headless Chrome; tag ``@tagged("post_install", "-at_install")``

Tests live in ``tests/``, one file per feature, and **every file must be imported
exactly once from ``tests/__init__.py``** ``[test_lint test_test_holes]``. A file
that is never imported never runs, and reports nothing — which is why this is a
hard gate rather than a convention.

.. code-block::

   tests/
     __init__.py          # from . import test_sale_order, test_sale_order_line
     test_sale_order.py
     test_sale_order_line.py

Naming: files ``test_<feature>.py``, classes ``TestFeatureName``, methods
``test_<specific_scenario>``.

6.2 Isolation
-------------

* **Create records in ``setUpClass()``** — it runs once per class, not once per
  method. Use ``setUp()`` only when a method genuinely mutates shared state.
* **Freeze time.** ``datetime.now()`` makes tests flaky; use ``odoo.tests.freeze_time``.
* **Mock external services.** Tests run offline.
* **Test with minimal permissions** — a user in only the group under test surfaces
  access-rule bugs early. ``@users("demo")`` covers multi-user cases.
* **Never call ``cr.commit()``.** Test data lives in the test transaction and is
  rolled back; a commit permanently pollutes the database. The one exception is a
  concurrency or cron test that deliberately opens ``self.registry.cursor()``.
* A test class is **either ``at_install`` or ``post_install``**, never both and never
  neither ``[review]``. Pure ORM tests are ``at_install``; anything touching other
  modules, the web client or tours is ``post_install``. ``@tagged`` only *warns* on
  a violation (``odoo/tests/common.py``, ``_logger.warning``) and the run proceeds,
  so nothing fails — a class tagged both ways is caught by review or not at all.

.. code-block:: python

   @classmethod
   def setUpClass(cls):
       super().setUpClass()
       cls.partner = cls.env["res.partner"].create({"name": "Test Partner"})

6.3 ``BaseCommon``
------------------

``odoo.addons.base.tests.common.BaseCommon`` gives a quiet environment with mail and
tracking disabled. It is not the default base class — most tests still use
``TransactionCase`` — but it is the right one when mail noise is irrelevant.

It provides ``DISABLED_MAIL_CONTEXT``; pre-built ``cls.company``, ``cls.currency``,
``cls.partner``; the groups ``cls.group_user`` / ``cls.group_portal`` /
``cls.group_system``; and the helpers ``quick_ref(xmlid)``, ``_create_partner()``,
``_create_new_internal_user()``, ``_create_new_portal_user()``.

It does **not** create an independent user or company by default —
``setup_independent_user`` and ``setup_independent_company`` return ``None`` unless a
subclass overrides them.

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
* **Negative tests are mandatory** ``[review]``: every test class covers at least one
  expected-failure path — a constraint raising ``ValidationError``, an unauthorised
  user getting ``AccessError``, an invalid state transition being refused.
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
  when the work *moves* as readily as when it grows, and the number cannot tell
  those apart — only the stack of the extra calls can. Two sessions misread one
  on 2026-08-15, in opposite directions, and both were a call site away from the
  wrong remedy. A pin asserting *exactly* one QWeb compile per batch read **0**
  once the compiled template outlived the call: that reads as a regression and
  was the fix landing. A pin asserting one ``_notify_get_reply_to`` for five
  records read **6** against another session's in-flight tree: read as their
  regression it invited deleting the local hoist, which was the very thing their
  fix had been written to honour. Get the stack before moving a pin, then move it
  and say in the commit what each unit bought. ``marketing_card``'s send pin went
  54 → 56 because two reads stopped being warmed incidentally by a scan that was
  removed — the same reads, in the window that needs them, against 25 fewer
  elsewhere. That is not the same fact as two reads being added, and only the
  second is a regression.
* **Pin the guarantee, not the arithmetic** ``[review]``. Where the mechanism is
  what you mean, assert a bound and then assert the mechanism:
  ``assertEqual(compiles, 1)`` breaks the day caching improves it to zero, while
  ``assertLessEqual(compiles, 1)`` followed by a second render asserting zero
  says *compiled once, never again* — which is the property, and survives the
  improvement. **Both halves are required: a bound alone is satisfied by the
  work not happening at all.** Applied to the
  ``_notify_get_reply_to`` pin this rule is drawn from, the second half failed
  on its first run — ten notifications where five were expected — because the
  class fixture assigned an activity before each test and notified once more.
  The exact-count pin had never seen it, counting only calls inside the patched
  block; asserting the outcome exposed a fixture that had been doubling every
  test in the class.

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

``**/tests/**`` suppresses these ``ruff`` rules. Keep the list in sync with
``ruff.toml``:

``B017`` (broad ``assertRaises``), ``RUF015``, ``PLW0603`` (fixtures), ``T201``
(``print``), ``PLR6201``, ``S110`` (cleanup ``try``/``except``/``pass``), ``S113``
(HTTP without timeout), ``TRY002``, ``TRY203``, ``EM101``, ``PLR0124``
(self-comparison), ``A001`` / ``A002`` (builtin shadowing), and ``RUF069`` — exact
float assertions of deterministic values are legitimate in a test.

``D`` and ``ANN`` are also exempt inside ``odoo/libs/`` and
``odoo/orm/components/`` tests, matching the tree-wide convention that tests carry
neither docstrings nor full annotations.

6.7 Tagging
-----------

* Default: ``standard`` + ``at_install``.
* ``HttpCase``: ``@tagged("post_install", "-at_install")``.
* Slow or external tests excluded from the standard run: ``@tagged("-standard")``,
  optionally with a real selector tag such as ``external`` or ``nightly`` to pass to
  ``--test-tags``. There is no ``heavy`` tag — do not invent one.
* **Localisation tests** must carry exactly one of ``post_install_l10n`` or
  ``external_l10n``, each paired with its base tag (``post_install`` and ``external``
  respectively) ``[test_lint test_l10n]``.
* **JS (HOOT) tests** carry ``desktop``, ``mobile`` or ``headless`` — via
  ``test.tags(...)`` or a file-level ``describe.current.tags(...)``. A test that
  mounts nothing and imports no ``@odoo/hoot-dom`` is ``headless``; one that
  branches on viewport or touch is ``desktop`` or ``mobile``. Leaving a test
  untagged is not neutral: it runs in *both* passes, so a DOM-free test pays a
  second run at 375x667 that can only ever repeat the first. ``headless`` still
  runs in the desktop pass — it means DOM-free, not "no browser" ``[review]``.

6.8 Coverage
------------

Aim above **80%** on custom modules — aspirational, not gated. Cover edge cases,
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

Two things that will waste your time otherwise: redirecting server output with
``>`` drops and reorders lines (Odoo writes from several file descriptions without
``O_APPEND``) — use ``>>``, ``tee`` or ``--logfile``, and gate on the exit code plus
the ``N failed, M error(s)`` summary. And stopping a background run kills only the
shell: ``odoo-bin`` survives and keeps holding its HTTP port.

----

7. Git
======

7.1 Commits
-----------

Subject line ``[TAG] module: description`` — aim for 50 characters, hard cap 72, and
keep it shorter than the PR title.

``module`` is a single module (``account_cfdi``, or with a sub-path such as
``stock/routes``), a comma-separated list when the change genuinely spans several
(``[FIX] sale,purchase: ...``), or ``*`` for a tree-wide change. Prefer ``*`` over an
unreadable list.

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
     - cleanup, no functional change — stricter than ``REF``
   * - ``LINT``
     - linting or formatting only

One primary tag per commit, chosen by dominant intent; if a change has two intents,
split it. ``LINT`` and ``CLN`` must contain no behaviour change — if they do, the
tag is ``REF``.

.. code-block::

   [IMP] product_asset: filter Fleet views by fuel card

   Fleet and Fleet Service Logs showed all assets regardless of fuel card
   assignment, making the views noisy for operators.

   Solution:
   - Add domain filter on fuel_card_id to the Fleet list view
   - Apply the same filter to Fleet Service Logs

   Task ID: 17012

The ``Solution:`` block and the ``Task ID`` line are mandatory.

**Name files in a pathspec, never a directory** ``[review]``. ``git commit --
<path>`` records the *working tree* at that path, deletions included, and a
directory pathspec sweeps in every deletion under it. Measured:

.. code-block::

   rm research/note.md              # missing from the working tree

   git commit -m A -- research/keep.md    # note.md survives
   git commit -m B -- research            # note.md deleted, unmentioned

Branch B is how a 567-line note was removed by a commit whose message described
only an edit to its sibling. Naming the files is the fix; reading ``git status``
for ``D`` lines before committing is the check that catches the rest.

7.2 Branches and task IDs
-------------------------

Feature branches are ``<odoo_version>-t<task_id>-<github_username>``, e.g.
``19.0-t17352-suniagajose``. Every commit references a task ID and every branch
carries it, so a code change traces to a task and a task to a business requirement.

7.3 Pull requests
-----------------

Every change in scope goes through a PR, except in ``agromarin-knowledge``, which
works directly on ``main``.

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

* The task ID in the title line as a **hyperlink**, not plain text.
* At least one commit per logical unit — do not squash unrelated changes.
* No merge commits from the base branch in the PR history; rebase instead.
* No force-push to a **shared** branch (``main``, ``19.0``, ``19.0-marin``,
  ``19.0-dev``). Force-push is expected on your own feature branch — rebasing
  requires it.

PRs land by **rebase merge**, which rewrites every SHA. Afterwards a local branch
reads "N ahead, N behind"; that is cosmetic, not a conflict. Confirm with
``git diff <local> origin/<branch>`` (empty means identical trees), then
``git reset --keep origin/<branch>`` — ``--keep``, never ``--hard``: it preserves
uncommitted work and aborts rather than clobbering it.

Branch model: ``19.0`` is a pristine upstream mirror and never receives AgroMarin
work; ``19.0-marin`` is the integration branch; feature branches cut from and merge
back into it. The same applies to ``enterprise``.

----

8. Translations
===============

8.1 Python
----------

Use ``self.env._()``. It takes the language from the environment, whereas the
legacy ``_()`` walks back up the call stack with ``inspect.currentframe()`` to
infer the language and the calling module (``odoo/tools/translate.py``). Besides
being faster, it is correct in places where the frame above is not the one you
think — decorators, comprehensions, callbacks.

.. code-block:: python

   message = self.env._("Order confirmed successfully")
   raise UserError(self.env._("Order %s cannot be confirmed.", order.name))

Four rules, all enforced by ``_checker_gettext``, which recognises both ``_()`` and
``self.env._()``:

* **The first argument is a literal string** ``[test_lint E8502]``. Passing a
  variable defeats extraction — there is nothing for the exporter to find.
* **Two or more placeholders must be named** ``[test_lint E8503]``. With
  ``"%s of %s"`` a translator cannot reorder the arguments for their language; write
  ``self.env._("%(done)s of %(total)s", done=x, total=y)``.
* **No ``%r``** ``[test_lint E8504]``. Its output is a Python repr, which is neither
  translatable nor meaningful to a user.
* **User-facing exceptions take a translated message** ``[test_lint E8505]``, not a
  bare literal (§2.7).

Note that ``ruff``'s ``INT`` rules only match the bare ``_()`` form; they do not see
``self.env._()``. ``test_lint`` is what actually covers the form this guide
mandates.

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
``[test_lint test_i18n, test_jstranslate]`` — which means a user-facing string
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

Keep the template at ``i18n/<module>.pot`` and language files at ``i18n/<lang>.po``.
Re-export after changing user-facing strings — **including deleting one**, or the
template keeps advertising a message that no longer exists:

.. code-block:: bash

   odoo-bin --addons-path=odoo/addons,addons i18n export -d <db> <module>

Export through the **community trees only**. The header records
``odoo.release.version``, which the enterprise addons path turns into
``Odoo Server 19.0+e``; exporting a community module through a workspace path that
carries ``enterprise/`` therefore writes a fact about your checkout into its
template.

Never hand-edit a ``msgid`` to "fix" the English — change the source string and
re-export. Duplicate entries in a ``.pot`` are a failure ``[test_lint test_pofile]``.
Translations round-trip through Weblate (``.weblate.json``); do not commit
machine-merged ``.po`` churn that fights it.

----

9. Code review checklist
========================

The tooling checks what tooling can check. This list is what it cannot — do not
re-verify lint codes by hand. Skip an item that does not apply, with a note.

**Security**

#. Dynamic SQL is parameterised or wrapped in ``SQL()`` — including identifiers
   built from ORM metadata.
#. ``sudo()`` writes of user-submitted payloads whitelist the allowed fields.
#. Related fields reaching sensitive models (``ir.attachment``, ``hr.payslip``)
   have explicit access control (§10.5).
#. Every public method is *intentionally* an RPC endpoint.
#. Security validation uses ``if … raise``, never ``assert``.
#. Handlers expose no tracebacks or SQL fragments to users.
#. State-mutation code fails closed — partial operations sit inside a savepoint.
#. No hard-coded URLs, credentials or service endpoints.

**Correctness**

#. No query call inside a loop over a recordset.
#. Computes assign fields directly; they never call ``write()``.
#. CRUD overrides call ``super()``; ``create`` uses ``@api.model_create_multi``.
#. ``@api.depends`` lists every sub-field the body reads — ``"partner_id.country_id"``,
   not ``"partner_id"`` (§11.4).
#. Every ``Monetary`` field has a currency field on the same model.
#. Error types match intent: ``UserError`` for business rules, ``ValidationError``
   inside constraints, ``MissingError`` for deleted records.
#. ``.exists()`` is called where another transaction may have deleted the record.
#. Overridden framework methods carry ``@typing.override``.

**Performance**

#. Counts use ``search_count()``; aggregation uses ``_read_group()``.
#. No ``cr.commit()`` outside ``_commit_progress()``.
#. Crons batch with ``itertools.batched`` and ``_commit_progress()``.
#. Locking uses ``NOWAIT`` or ``SKIP LOCKED`` — no unbounded waits.
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
ORM and QWeb methods are irreducibly branchy. The setting is therefore inert and
complexity is a review judgement, not a gate. Do not "fix" the config to switch it
on without reversing that decision explicitly.

----

10. Security
============

10.1 Method visibility
----------------------

A public method — no leading underscore — is callable over XML-RPC and JSON-RPC by
any authenticated user. ACL checks happen during CRUD operations only; a custom
public method enforces nothing on its own.

* **Default every method to private.** Remove the underscore only after deliberate
  review.
* ``@api.private`` blocks RPC on a method that must keep a public *name*. It is
  enforced at the RPC boundary across the whole MRO, so a subclass cannot re-expose
  it. Use ``_`` for new code and ``@api.private`` to retrofit.

10.2 ``sudo()``
---------------

* **Prefer narrower escalation.** ``with_user(user)`` and ``with_company(company)``
  keep ACLs and record rules *enforced* under a different identity. Reserve
  ``sudo()`` for genuine cross-tenant or system operations.
* **Whitelist fields** when writing a user-submitted payload. A ``sudo()`` read of
  one field is low-risk; ``sudo().write(payload)`` is the dangerous shape.
* **Minimise scope** — smallest recordset, fewest operations.

.. code-block:: python

   def action_update(self, values):
       allowed = {"description", "tag_ids"}
       self.sudo().write({k: v for k, v in values.items() if k in allowed})

10.3 Input validation
---------------------

``assert`` is stripped under ``python -O``. Any validation guarding
security-sensitive logic uses ``if`` / ``raise`` ``[review]``:

.. code-block:: python

   if access_mode not in ("read", "write", "create", "unlink"):
       raise ValueError(f"Invalid access mode: {access_mode!r}")

``ruff``'s ``S101`` is disabled — Odoo uses ``assert`` for ORM invariants — so the
linter will not catch a security ``assert``.

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

``ruff``'s ``S608`` is disabled, because the ORM legitimately builds SQL through the
``SQL()`` wrapper. The ``test_lint`` checker is what covers this — it tracks constant
propagation across assignments and function boundaries, and treats
underscore-prefixed attributes such as ``self._table`` as trusted.

10.5 Related fields and ACLs
----------------------------

**Related fields default to ``compute_sudo=True``**, so a related field traversing
into a sensitive model is read as superuser and **bypasses the reader's ACLs and
record rules**. (Plain computed fields default to ``compute_sudo = store`` — sudo
only when stored.) Do not reason from the field type; pick one of:

* set ``compute_sudo=False`` explicitly on that field, or
* restrict it with ``groups="..."``, or
* replace the related field with an explicit, ACL-respecting compute.

10.6 Controllers
----------------

* ``auth="public"`` runs as the Public user — unauthenticated visitors reach it.
  Validate and sanitise every parameter, schema-validate the payload, and
  rate-limit the endpoint.
* ``auth="none"`` means no database access; it is mainly for framework use.
* ``auth="bearer"`` tokens must be scoped and validated, and never logged.
* Use ``Markup()`` for intentional HTML and escape user content. Never interpolate
  user input into ``Markup()`` with an f-string — that is an XSS hole.
* Do not set ``csrf=False`` on a ``type="http"`` POST route without a written
  justification. ``jsonrpc`` is CSRF-exempt by design.

10.7 Constraints run privileged
-------------------------------

**A deliberate fork deviation.** ``@api.constrains`` methods run as ``sudo()`` by
default, like stored computed fields. Consequences:

* Reads inside a constraint never raise ``AccessError``, and any write it performs
  executes privileged — hold constraint bodies to the same discipline as explicit
  ``sudo()`` code (§10.2).
* Opt back into user-aware validation with ``@api.constrains(..., sudo=False)`` when
  the check must see the current user's view of the data.
* A callable spec (``@api.constrains(lambda self: ...)``) is resolved once per
  registry class and memoised, so an env-dependent field list is frozen at its first
  evaluation.

10.8 Access control
-------------------

Every new model ships explicit access rules ``[review]``. A model with no
``ir.model.access`` line is inaccessible — or worse, silently admin-only.

* **ACLs** are table-level, in ``security/ir.model.access.csv``: one line per
  (model, group) with ``perm_read,perm_write,perm_create,perm_unlink``. Grant the
  minimum — typically ``1,1,1,0`` for a user group and ``1,1,1,1`` for a manager
  group. Avoid group-less global lines.
* **Record rules** (``ir.rule``) are row-level: use them when access depends on the
  record's data — owner, company, state. A rule with no groups applies to everyone.
* **Multi-company** rules use ``[("company_id", "in", company_ids + [False])]`` so
  company-less shared records stay visible. Pair with ``check_company=True`` on
  relational fields (§2.9.10).
* Restrict sensitive **fields** with ``groups="module.group_xxx"`` — enforced on both
  read and write.

10.9 Configuration and secrets
------------------------------

* **No hard-coded URLs, credentials or endpoints.** Use ``ir.config_parameter``,
  environment variables, or ``odoo.conf``.
* **Namespace** config keys as ``<module>.<setting>``; read them with
  ``self.env["ir.config_parameter"].sudo().get_param(key, default)``.
* ``ir.config_parameter`` values are readable by ``base.group_system``. For true
  secrets — API keys, tokens — prefer environment variables or ``odoo.conf`` over the
  database.
* External dependencies are declared in ``__manifest__.py`` *and* pinned in
  ``requirements.txt`` (§1.2).

10.10 Deployment checklist
--------------------------

* ``--dev`` disabled; ``list_db = False``; ``admin_passwd`` changed from the default.
* ``proxy_mode = True`` behind a reverse proxy, with ``http_interface`` bound to
  localhost so only the proxy is public.
* ``dbfilter`` set; ``server_wide_modules`` minimal (the 19.0 default is
  ``base,rpc,web``).
* ``workers > 0``, with ``limit_time_cpu`` / ``limit_time_real`` /
  ``limit_memory_soft`` / ``limit_memory_hard`` / ``limit_request`` tuned.
* ``db_sslmode = require`` or ``verify-full`` — the default ``prefer`` does **not**
  enforce TLS to PostgreSQL.
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
checker is advisory today — it logs at WARNING rather than failing — and modules are
escalated to blocking individually as they are cleaned up. Treat a warning as a
finding, not as noise.

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
``SELECT COUNT(*)``. For aggregation, note the double unpack — a group-less
``_read_group`` returns ``[(value,)]``:

.. code-block:: python

   [[total]] = self.env["account.move.line"]._read_group(domain, aggregates=["amount:sum"])

``search_fetch()`` returns a real recordset with the named fields pre-loaded, unlike
``search_read()``, which returns dicts.

Iterating a recordset prefetches for the whole set, which is usually what you want.
For a large set processed one record at a time, ``with_prefetch([])`` stops the ORM
pulling every sibling's fields into memory.

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

**Cached methods must never return recordsets.** The cursor that built the recordset
is closed by the time of a later call, and the result raises ``InterfaceError``.
Return plain Python values.

The ORM invalidates automatically through ``modified()``;
``self.env.registry.clear_cache()`` clears everything.

11.4 Computed fields
--------------------

* ``store=True`` only when the field is searched, ordered or grouped on. Non-stored
  computes avoid recomputation on every write.
* **Every sub-field the body reads must appear in ``@api.depends``** ``[review]``.
  Incomplete chains cause silent stale data: if the method reads
  ``record.partner_id.country_id``, then ``"partner_id.country_id"`` must be listed —
  ``"partner_id"`` alone is not enough.

  .. code-block:: python

     @api.depends("partner_id.country_id")
     def _compute_country(self):
         for rec in self:
             rec.country_id = rec.partner_id.country_id

* **Exception — initialisation-only computes.** When a ``store=True, readonly=False``
  compute exists to seed an initial value (inheriting ``lang`` from a parent on
  reparenting, say), a coarse ``"parent_id"`` dependency is deliberate: the precise
  ``"parent_id.lang"`` would recompute and overwrite the user's edit whenever the
  parent changed. Fields whose ``inverse`` writes back along the same path need the
  same coarsening to avoid a trigger cycle.
* Avoid long chains of stored computes depending on each other; flatten where you
  can.

11.5 Indexing
-------------

* ``index=True`` on fields used in search domains, ``ORDER BY`` or ``GROUP BY``.
* **The stored inverse Many2one of a One2many must be indexed**
  ``[test_lint test_index]``. Without it, every traversal of the One2many is a
  sequential scan of the child table. Genuine exceptions go in the checker's
  allow-list with a reason, not into a bare ``index=False``.
* Every index costs write and create time — beyond the rule above, index
  selectively, driven by measurement.
* ``models.Index()`` takes a raw definition, which is how composite, partial and
  expression indexes are declared:

  .. code-block:: python

     _account_date_idx = models.Index("(account_id, date)")
     _state_date_idx = models.Index("(date_order) WHERE state != 'done'")
     _name_upper_idx = models.Index("(UPPER(name))")

* A **partial** index is the right default where queries always filter on a state:
  it indexes only the rows actually queried.
* An **expression** index avoids a full scan for case-insensitive lookups.
* Other access methods are available through the same raw form —
  ``USING gin`` is in use in the tree, and ``USING brin`` suits append-only
  time-series tables. Neither is a default; justify one with a query plan.

11.6 Raw SQL
------------

Any raw ``cr.execute()`` added in a PR ships ``EXPLAIN ANALYZE`` output in the
description, showing the plan uses the indexes you expect ``[review]``. This makes
performance a review gate rather than a post-deployment discovery.

The ORM defers writes, so bracket raw SQL accordingly:

.. code-block:: python

   self.flush_model()          # push pending values to the database
   self.env.cr.execute(...)
   self.invalidate_model()     # drop the cache after writing behind the ORM's back

11.7 Cron batching
------------------

Scheduled actions over large recordsets batch with progress reporting. Do **not**
call ``cr.commit()`` — ``_commit_progress`` commits for you and tells you how much
time is left.

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

* Batch 100–1000 records to bound memory and lock duration. ``split_every`` is
  deprecated; use ``itertools.batched``.
* ``_commit_progress(processed=0, *, remaining=None, deactivate=False)`` — note that
  ``remaining`` is **keyword-only**. It returns the **remaining cron time in
  seconds** (``inf`` outside a cron, ``0`` at the deadline), not a record count. Set
  ``remaining`` once; afterwards pass only ``processed``.
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
     - critical sections — sequences, payment processing. Raises
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
common case) or the full ``19.0.1.2.0`` — Odoo prefixes a bare version with the
server major at load time. The special ``0.0.0`` directory runs on **every** update:
first in the ``pre`` stage, last in ``post`` and ``end``.

Scripts are matched on the **stage prefix alone** — ``name.startswith("pre-")`` /
``"post-"`` / ``"end-"`` — so any suffix runs, ``-migrate.py`` and ``-migration.py``
included, and a descriptive name such as ``post-migrate_update_taxes.py`` is fine.
Within a stage they run in filename order.

The ``migrate`` function's signature is checked and must be exactly two positional
parameters named ``(cr, version)`` — ``_cr`` / ``_version`` are the only accepted
aliases. Anything else raises ``TypeError`` at migration time, when the upgrade is
already running.

Lint rules are relaxed under ``**/migrations/**`` — ``E501``, ``UP``, ``PTH`` and
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

The framework passes a **cursor**, not an environment. Guard ``pre-migrate`` SQL with
the helpers in ``odoo.db.schema`` — ``table_exists``, ``column_exists``,
``index_exists``, ``create_column``, ``convert_column``, ``drop_constraint`` — rather
than hand-written ``information_schema`` queries. (There is no ``odoo.tools.sql`` in
this fork; the module is ``odoo/db/schema.py``.) ``openupgradelib`` is available but
is not the house default.

**Removing a stored field: its column is dropped in the same upgrade, and
post-migrate is the last place its values can be read.** Odoo deletes the
``ir.model.fields`` row for a field the code no longer declares and issues
``ALTER TABLE ... DROP COLUMN CASCADE`` for it, from ``ir.model.data._process_end``
— which ``modules/loading.py`` runs *after* every ``post-migrate``. So a
``post-migrate`` that harvests the old values into their new home works, and there is
nothing left for a later version to harvest. [review]

**A Many2many is the exception: its relation table is never dropped.**
``_drop_m2m_tables`` skips any field whose ``state`` is not ``manual``, and a field
declared in Python is ``base``. So removing a code-defined Many2many deletes its
``ir_model_fields`` row and leaves the join table, its rows and its foreign keys in
the database for good. That is useful — the old configuration stays readable, and a
post-migrate carrying it somewhere else can be written later rather than only in the
same upgrade — but it is not cleanup. Drop the table yourself if the data is not
worth keeping, and say so in the script. [review]

**Do not plan that harvest across two versions.** ``migrate_module`` runs **every**
``pre`` script for every version in range before **any** ``post`` script, so a
``pre-migrate`` at a *higher* version still executes before a *lower* version's
``post-migrate``. Splitting "copy the values" and "drop the column" across two
versions therefore drops first and copies nothing — and the data is gone with no
error, because dropping a column the ORM was going to drop anyway raises nothing.
Copy and link in one ``post-migrate``. [review]

12.3 When one is required
-------------------------

**Required**: adding or removing a required field on an existing model; changing a
field's type; renaming a model or field; any non-trivial data transformation.

**Not required**: adding an optional field; installing a new module; view-only
changes; adding or removing a Many2many relation.

----

Appendix A — Fork field renames
===============================

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
     - ``personal_triage_id`` (Many2one → ``project.task.triage``). Note the separate
       related field ``triage_id`` → ``project.triage``.
   * - ``depend_on_ids``
     - ``predecessor_ids``
   * - ``dependent_ids``
     - ``successor_ids``

So ``("stage_id.fold", "=", False)`` becomes ``("step_id.fold", "=", False)``, and
``order="date_deadline asc"`` becomes ``order="date_end asc"``.

``purchase.order`` and ``purchase.order.line`` rename one field, so that the date a
human committed to has a single name across order types:

.. list-table::
   :header-rows: 1

   * - Vanilla Odoo
     - This fork
   * - ``date_planned``
     - ``date_commitment``

``sale.order.date_commitment`` already carried that meaning — the delivery date
promised to the customer — while purchase spelled the vendor's promised arrival
``date_planned``. The two are the same concept, and shared code in ``base_order``
can now name it once: ``order.mixin``'s ``is_late`` domain reads
``date_commitment`` on both.

**``date_planned`` still exists, and still means something else.** It is a
*derived, unstored* estimate on ``sale.order`` (and on ``sale.order.line`` once
``sale_stock`` is installed), and it is the scheduling date on ``stock.move`` and
``stock.picking``, the key in the procurement ``values`` dicts the stock rules pass
around, and a field on the replenishment wizard. None of those were renamed. Read
the model before assuming which one a given ``date_planned`` refers to.

Appendix B — References
=======================

In this repo:

* ``ruff.toml`` — linter and formatter configuration, with the rationale for every
  suppression
* ``odoo/addons/test_lint/`` — the fork's own checkers
* ``tooling/ratchet/baselines/`` — the committed floors
* ``pytest.ini`` — the Tier 1 suite definition

In the knowledge repo (``agromarin-knowledge/reference/``):

* ``odoo/odoo-19-development-context.md`` — Odoo 17→19 API changes
* ``dev/error-catalog.md`` — known PATH / CONFIG / SERVICE / POSTGRES errors
* ``owl/`` — OWL hooks, stores and lifecycle
* ``python-pg/`` — Python 3.14 and PostgreSQL 18 / psycopg 3 patterns

External:

* `Odoo 19 Coding Guidelines <https://www.odoo.com/documentation/19.0/contributing/development/coding_guidelines.html>`_
* `OCA CONTRIBUTING.rst <https://github.com/OCA/odoo-community.org/blob/master/website/Contribution/CONTRIBUTING.rst>`_
* `PEP 8 <https://peps.python.org/pep-0008/>`_

Appendix C — Retired patterns
=============================

Flag these on sight; migrate opportunistically when you are already editing the file.

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Retired
     - Replacement
   * - Suffix XML IDs (``sale_order_view_form``)
     - Prefix style (§3.2) — it matches core, so inheriting and ``ref``-ing a core
       record needs no translation
   * - Commit tags ``[MIG]``, ``[CLA]``
     - ``ADD`` / ``REF`` on the migration script; ``REF`` on the licence change.
       Both described the *subject*, not the intent (§7.1)
   * - Field ordering by type
     - Semantic blocks (§2.3)
   * - Method ordering by Spanish category
     - The section banners in §2.2 — the old seven buckets had no home for search,
       inverse or mail methods
   * - Google-style docstrings (``Args:``, ``Returns:``)
     - Sphinx fields (§2.5) — mixing styles defeats every tool that parses them
   * - ``<tree>`` views and ``view_mode`` ``tree``
     - ``<list>`` (§3.3); core is fully migrated
   * - ``attrs=`` / ``states=``
     - Python expressions ``invisible=`` / ``readonly=`` / ``required=`` (§3.3)
   * - Renaming an inherited core method to fit §2.4
     - Override under the original name (§2.4)
   * - ``split_every``
     - ``itertools.batched`` (§11.7)
   * - ``with_context(force_company=...)``
     - ``with_company()`` — the key is now ignored with only a
       ``DeprecationWarning``, so surviving call sites silently use the wrong
       company (§2.6)
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
=============================

.. list-table::
   :header-rows: 1
   :widths: 8 12 80

   * - Version
     - Date
     - Summary
   * - 5.19
     - 2026-08-15
     - **A removed Many2many keeps its relation table forever.** §12.2 gains the
       exception to the rule added in 5.16: ``_drop_m2m_tables`` acts only on
       fields whose ``state`` is ``manual``, and a field declared in Python is
       ``base``, so a code-defined Many2many loses its ``ir_model_fields`` row and
       keeps its join table, rows and foreign keys. Measured while moving the AI
       fallback chain from ``ai.provider`` to ``ai.model`` (ADR-0040), where the
       old ``ai_provider_fallback_rel`` was still present and populated after the
       upgrade that removed the field. The asymmetry is worth stating because the
       scalar case is the opposite and unconditional.
   * - 5.18
     - 2026-08-15
     - **A removed field's column goes away in the same upgrade, and the harvest
       cannot be split across versions.** §12.2 gains both halves. Odoo drops the
       column for a field the code no longer declares, from
       ``ir.model.data._process_end``, which runs after every ``post-migrate`` —
       so post-migrate is the last place the old values are readable, and no
       later version can collect them. And because ``migrate_module`` runs every
       ``pre`` script before any ``post`` script, a ``pre-migrate`` at a higher
       version executes *before* a lower version's ``post-migrate``: the
       plan-shaped "copy in 1.13.0, drop in 1.14.0" drops first, copies nothing,
       and raises nothing while doing it. Found while moving twelve columns off
       ``ai.provider`` onto ``ai.model`` (ADR-0039), where that two-version plan
       had been written down before it was tried.
   * - 5.17
     - 2026-08-15
     - **Excess extracted out of** ``odoo/`` **into an addon was measured by
       nothing.** ``pyfunclen`` scopes to the core package and no gate covered
       ``addons/``, so a function moved across that line left both readings
       looking better — checked by hand once, when ``_run_action_webhook`` shed
       12 units into ``addons/api_transport``, and catchable by nothing the
       second time. ``py_function_length.py`` gains ``--addon addons``, the
       whole tree as one number, floored as ``pyfunclen_addons``. The per-module
       ``--addon`` pattern cannot close this seam: the receiving module is the
       one nobody onboarded. It is the **first floor invoked with** ``--mode``
       (``no-increase``) and *The ratchets* records why — the tree moves ~1700
       in each direction per month, and an exact floor on it would be red
       almost continuously.
   * - 5.16
     - 2026-08-14
     - **The Change protocol gains two rules about the decision register.** A
       rule whose rationale is architectural now cites its record as a bare
       ``ADR-NNNN``; ``tooling/doclinks`` scans this file and fails on a citation
       that does not resolve, so the reference cannot rot, and the record is
       never summarised here because two copies drift. A rule with no record may
       be one worth writing, and ``doc/adr/README.md`` states when one is owed.
       Five citations added where the record genuinely argues for the rule: the
       façade boundary (§2.1) to ADR-0008/0009, the ratchet *mechanism* to
       ADR-0006, §2.4's count to ADR-0033, ESM specifier resolution (§4.1) to
       ADR-0023, and the JS import-cycle gate to ADR-0019 with ADR-0034 as its
       Python counterpart. Two candidate citations were checked and **not**
       added, because the records do not argue for those rules: ADR-0007 is the
       CI integration lane rather than §6.0's test tiers, and ADR-0021 is about
       *service* facades rather than §4.3.3's component patching. The per-gate
       mapping for ``tooling/architecture/`` is deliberately absent — each module
       declares its own ``ADR`` constant, checked by ``test_gate_adr_coverage.py``.
   * - 5.15
     - 2026-08-15
     - **§7.1 requires a pathspec to name files, not a directory.** ``git commit
       -- <path>`` records the working tree at that path, deletions included, so
       a directory pathspec sweeps in every deletion under it — which is how a
       567-line research note was removed by a commit whose message described
       only an edit to its sibling. Measured both ways: naming the file leaves a
       missing sibling untouched, naming the directory deletes it. §12 of the
       workspace ``CLAUDE.md`` already warned about the additions half of this
       trap — another session's staged work riding along under your message —
       and this is the deletions half, which needs no second session to happen.
   * - 5.14
     - 2026-08-15
     - **§6.4 splits the query-count rule in three.** "A query-count increase is
       a regression" was the whole of it, and on one day two sessions acted on
       that sentence and both readings were wrong — in opposite directions. A
       pin asserting exactly one QWeb compile per batch read **0** once
       ``mail``'s template node cache let compiled code outlive the call, which
       looks like a regression and was the fix landing; a pin asserting one
       ``_notify_get_reply_to`` per batch read **6** against another session's
       in-flight tree, and reading it as their regression invited deleting a
       local hoist their fix had been written to honour. Both needed the *stack*
       of the extra calls, not the number. The rule now separates locking a hot
       path from interpreting a move, and adds: pin the guarantee rather than
       the arithmetic — ``assertLessEqual`` plus a second call asserting zero
       says *compiled once, never again*, and survives the improvement that
       ``assertEqual(…, 1)`` breaks on. Both halves are required, and the
       second earned its keep the same day: applied to the
       ``_notify_get_reply_to`` pin, asserting the outcome failed at once on a
       class fixture that had been doubling every test's notifications, which
       the exact-count pin could not see because it counted only inside the
       patched block.
   * - 5.13
     - 2026-08-11
     - **§2.9.14 gains ``_defer()``**: a job saying "not finished, and nothing
       went wrong". The queue had two ways out of a body — done, or an
       exception — so a job polling a remote service had to report progress as
       failure: ``RetryableJobError`` rolls back what the poll learned and
       spends a retry per attempt, and a package the SAT legitimately takes an
       hour to prepare exhausted ``max_retries`` and was marked failed.
       Re-enqueueing from inside the body silently does nothing, because a
       running job is in a queued state and still holds the ``identity_key``
       its replacement would need. ``_defer(seconds, reason=)`` keeps the
       body's writes, leaves ``retry`` and ``exc_*`` alone, holds the identity
       key, and draws on its own ``max_defers`` budget. Added to the framework
       in the same series (odoo ``ir.job``/``@api.job``), first consumer
       ``documents_l10n_mx_edi``'s SAT verify phase.
   * - 5.12
     - 2026-08-10
     - **§2.9.8 forbids UNIQUE over a translated column**, gated at a hard zero
       by ``test_lint``'s ``test_translated_unique``. A ``translate=True``
       field is ``jsonb``, so the constraint compares translation *documents*
       and stops matching as soon as one row carries a language the other does
       not — reproduced on ``utm.tag``, where two rows named "DupeProof"
       coexisted under ``unique (name)``. 29 rules were in this state across
       the three repos and were fixed in the same series (odoo ``27836af2f3e``,
       enterprise ``47a6a928a64``, agromarin ``34e0b495``), so the floor is 0
       with no debt for a new one to hide behind. The section also records the
       trap the fix walked into: ``name_uniq_index`` defaults to ``NULLS NOT
       DISTINCT`` while a plain UNIQUE does not, and tightening that silently
       broke ``base``'s own ``test_ir_embedded_actions`` — hence
       ``nulls_distinct=True`` when converting rather than adopting. The gate
       is whole-tree rather than per-file because whether a column is
       translated is often decided on another module's extension or an
       inherited mixin.
   * - 5.11
     - 2026-08-10
     - **§8.3's re-export command no longer parses.** It gave
       ``odoo-bin -d <db> --i18n-export=... --modules=...``; that option is gone
       and the entry point is the ``i18n export`` subcommand
       (``odoo/cli/i18n.py``). Found by following the rule as written while
       re-exporting ``addons/barcodes`` — a documented command that errors out
       is worse than no command, since the reader concludes the export is not
       expected of them. Added the addons-path constraint the same export
       exposed: the template header records ``odoo.release.version``, which
       becomes ``Odoo Server 19.0+e`` when the path carries ``enterprise/``, so
       a community module exported through a full workspace path records a fact
       about the exporter's checkout (187 of this repo's templates carry that
       suffix and 360 do not). Also made explicit that *deleting* a
       user-facing string requires the re-export too.
   * - 5.10
     - 2026-08-09
     - **pydocstyle retired: ``D`` is no longer selected, and the
       ``ruff_docstring`` ratchet is gone.** The floor pinned what
       ``eff67f80316`` created by stripping docstrings from ``odoo/`` on
       purpose, so it could only be paid down by reversing that strip — a gate
       against its own project's intent, and the one floor §2.5 and
       ``gates.md`` both described as having an open *direction*. Direction
       settled by retiring it, which is the alternative
       ``.github/workflows/ruff.yml`` had named in place all along ("the honest
       change is to ignore D1 in ruff.toml rather than ratchet it"). §2.5
       rewritten: presence is a **review** expectation everywhere, ``DOC``
       (pydoclint) still enforces *accuracy* on docstrings that exist, and the
       two load-bearing bodies — ``odoo/cli/`` help text and the
       machine-checked contracts — are named so a future strip does not take
       them. ``ruff``'s command loses ``--ignore D`` (a no-op against a config
       that does not select D, and a claim to a scope the gate no longer has).
       A trap recorded with it: a CLI ``--select`` **re-selects rules
       ``ruff.toml`` ignores**, so a step counting ``--select D`` reports a
       family the linter does not enforce — measured at 745 against the
       configured run's 526.
   * - 5.9
     - 2026-08-09
     - **The ratchets table listed nine floors over ten rows against thirteen
       baseline files, and one of the ten was not a ratchet.** Missing:
       ``ruff_docstring``, ``c901_addons``, ``pyfunclen`` and
       ``jsforcedrender``; miscounted: "nine floors today"; misfiled: the
       layer-boundary gate, which is drift-zero with no baseline file and is
       now described only under the consequences. ``ruff``'s command was also
       written without ``--ignore D``, which is how CI has measured it since
       the 2026-08-08 docstring split — following the guide as written
       reproduced neither floor. **No count is stated in this section any
       more**: the directory is the list and ``ratchet.py --list`` is the
       reading. Both ``CLAUDE.md`` files updated in the same change, per the
       change protocol; the workspace root's copy of the table dropped its
       Floor column for the same reason.
   * - 5.8
     - 2026-08-09
     - **§12.2 named a module that does not exist.** The pre-migrate SQL
       helpers were credited to ``odoo.tools.sql``; there is no such module in
       this fork — ``table_exists``, ``column_exists``, ``index_exists``,
       ``create_column``, ``convert_column`` and ``drop_constraint`` all live in
       ``odoo.db.schema``. Following the guideline as written raised
       ModuleNotFoundError. Revision 5.0 had already struck one dead reference
       under that path (``rename_column``) without correcting the path itself.
   * - 5.7
     - 2026-08-09
     - **Appendix A records the purchase ``date_planned`` ->
       ``date_commitment`` rename.** sale already stored the date promised to
       the customer as ``date_commitment`` while purchase called the vendor's
       promised arrival ``date_planned``, so one concept had two names and one
       name had two concepts — sale's ``date_planned`` is a derived, unstored
       estimate. The appendix also spells out where ``date_planned`` survives
       and still means something else (sale's estimate, stock.move /
       stock.picking scheduling, the procurement ``values`` dicts, the
       replenishment wizard), because a blind rename across those would be
       wrong.
   * - 5.6
     - 2026-08-09
     - **§2.4 gains the cache lifecycle verbs.** ``invalidate_`` /
       ``clear_`` / ``reset_`` were used interchangeably across 20 methods in
       9 classes of the core with nothing stating what separated them —
       ``Transaction.clear()`` and ``Transaction.invalidate_field_data()``
       dropping overlapping-but-different sets, ``FieldCache`` carrying both
       ``invalidate_all()`` and ``clear()``. Each verb now has one meaning and
       the failure it prevents: invalidate = drop what may be stale w.r.t. the
       database (correctness), clear = drop everything unconditionally
       (lifecycle), reset = rebuild derived state from its source. Documented
       rather than mechanically renamed: the existing names are addon-facing,
       so the contract lands first and the renames follow it.
   * - 5.5
     - 2026-08-08
     - **§1.2 names the right requirements file, and states when NOT to
       declare.** External dependencies are pinned in the file of the repo that
       owns the module — the new ``odoo/requirements-addons.txt``, not
       ``odoo/requirements.txt``, which now carries only what the framework and
       the always-loaded addons import. Seventeen packages moved out of the
       server file, where they had been installed on every deployment for
       modules it would never load; ``pyserial``, ``pyusb`` and ``pywin32`` moved
       further, to ``addons/iot_box_image/configuration/requirements.txt``, since
       every import of them is under an ``iot_handlers/`` tree that never runs in
       a server process and ``iot_drivers`` is ``installable: False``. Added the
       three rules the split depends on: use the PyPI distribution name, declare
       only imports the module cannot start without (a guarded import declared
       turns a degrading feature into a refused install), and an ``auto_install``
       module's declaration never fires because ``odoo/modules/db.py`` marks that
       closure in raw SQL.
   * - 5.4
     - 2026-08-07
     - **Cyclomatic complexity is gated**, as a ninth ratchet (``c901``, floor 46,
       scope ``odoo/``, threshold ``[lint.mccabe] max-complexity = 20``, enforced
       in ``ruff.yml``). It was not gated before, and the configuration read as
       though it were: ``ruff.toml`` selected the ``C90`` family, ignored
       ``C901`` — the family's *only* rule — and set ``max-complexity``, three
       settings that cancel out, while the two branch-complexity rules each
       justified their suppression by naming the other (``C901``: "see
       PLR0912"; ``PLR0912``: "redundant with C90"). Kept out of the ``ruff``
       aggregate on purpose, so a complexity fix cannot be masked by an
       unrelated new finding. Ratchets table and floor count updated to nine;
       ``gates.md`` said "four tool counts" against a list of eight, and its
       assertion now re-derives the number as well as the names.
   * - 5.3
     - 2026-08-07
     - **``test_lint`` runs in CI**, correcting the claim that it is not wired in:
       ``test_lint.yml`` runs ``/test_lint`` on ``base`` + ``test_lint`` for every
       PR without a ``paths:`` filter, and ``asset_lint.yml`` runs the
       registry-dependent classes against a wider install set.
       ``integration_tests.yml`` installs only ``base`` and runs neither.
       **Ratchets table completed** to the eight floors in
       ``tooling/ratchet/baselines/``: added ``naming``, ``jsfunclen``,
       ``jsprivate`` and ``jsserviceshape``, and named the baselines directory as
       the authoritative list. ``test_lint``'s ratchets are counted inside the
       module and are not baselined there. Five workflows invoke ``ratchet.py``
       without ``--mode``, not four.
   * - 5.2
     - 2026-08-06
     - Expanded §2.4 with a **verb vocabulary**: one canonical verb per operation
       (``_prepare_`` / ``_get_`` / ``_check_`` / ``_is_`` / ``_update_`` /
       ``_add_`` / ``_remove_``) and an abolished list (``_build_``, ``_make_``,
       ``_fetch_``, ``_retrieve_``, ``_validate_``, ``_verify_``, ``_ensure_``,
       ``_do_``, ``_run_``, ``_perform_``, ``_assign_``, ``_append_``, ``_delete_``
       and their kin), each with the discriminator that decides which applies.
       Derived from an AST census of 45,312 non-test model methods across ``odoo``,
       ``enterprise`` and ``agromarin``: 141 stems carry two or more same-family
       verbs, 146 method groups share a byte-identical body under different names,
       and ``_get_`` alone is 17.6 % of all methods. **Resolved an ambiguity this
       guide created**: §2.4 previously offered ``_check_`` and ``_validate_`` as
       interchangeable, which was generating collisions on its own; ``_check_`` is
       now canonical and ``_validate_`` is marked legacy in both placement tables.
       Flagged ``_post_`` as carrying three unrelated meanings across 242
       definitions. The EXEC-verb and ``_set_``/``_update_`` rules ship marked
       *provisional*. **Corrected by the first measurement**: the draft abolished
       ``_drop_``, ``_insert_``, ``_push_`` and ``_discard_``, and running the gate
       showed all four are terms of art from below the ORM — SQL DDL and DML, a
       stack push, and the ``set.discard`` contract. They are now *reserved* with
       stated meanings rather than abolished, and the vocabulary is scoped to model
       classes, the framework packages being legitimately entitled to that
       vocabulary. Enforced as a count by
       ``tooling/architecture/naming_vocabulary.py`` over the ``naming`` ratchet
       baseline (floor 274 in this repo; ``enterprise`` measures 230 and
       ``agromarin`` 54, each needing its own). The rules the gate cannot decide
       mechanically stay ``[review]``.
   * - 5.1
     - 2026-07-30
     - Corrected five claims that execution disproved. **``force_company`` does
       not raise** (§2.6, Appendix C): it emits a ``DeprecationWarning``, keeps the
       key in the context and is read by nothing, so surviving call sites silently
       scope to the wrong company — the opposite of the failure mode the old text
       implied. **``<group>`` does carry attributes in search views** (§3.3): only
       ``string`` and ``expand`` are rejected; ``name``, ``invisible``, ``groups``,
       ``colspan`` and ``col`` validate, and the old blanket claim contradicted the
       same section's rule about ``name=`` targets. **Ratchets fail in both
       directions** (*The ratchets*): ``ratchet.py`` defaults to ``exact`` mode, so
       an improvement fails the build too and the floor must be moved with
       ``--update`` — measured live at 539 against a floor of 541. **The
       ``at_install``/``post_install`` XOR is not enforced** (§6.2), only warned.
       **E8507 has no escalation mechanism** (*The ``test_lint`` module*):
       ``_BATCH_FAIL_MODULES`` exists in a docstring only. Also fixed the
       Quick Reference's float-comparison cross-reference (§2.9.13 → §2.9.12),
       and sharpened two claims that were true but imprecise: a currency-less
       ``Monetary`` fails via an ``assert`` at registry build, not "at runtime"
       (§2.9.4), and migration scripts match on the stage prefix alone with a
       checked ``(cr, version)`` signature (§12.1).
   * - 5.0
     - 2026-07-30
     - Full fact-check and rewrite. **Enforcement model corrected**: the 🔧/👁
       markers claimed ``ruff check`` blocks CI on any violation, which was never
       true — the countable gates (ruff, mypy, ESLint, ``tsc``) are *ratchets* over
       committed floors and the ruff one measures ``odoo/`` only, while layer
       boundaries are drift-zero. Replaced the markers with ``[ruff CODE]`` /
       ``[test_lint CODE]`` / ``[fixer NAME]`` / ``[review]``. **Documented the
       ``test_lint`` layer**, previously mentioned only for the XML fixers, and the
       ~20 rules it enforces that appeared nowhere in the guide: gettext placeholder
       and ``%r`` rules, raw literals in user-facing exceptions, One2many inverse
       indexing, domains returned from onchanges, ``ids``/``context`` parameters,
       override-signature compatibility, the ``odoo.orm`` façade boundary, manifest
       key order, test-file import completeness, docstring/signature agreement,
       redundant route attributes, l10n tagging, and the mandatory ``# noqa``
       rationale. **Corrected claims**: the translation rule is *not* covered by
       ``ruff INT`` for the mandated ``self.env._()`` form (only ``test_lint`` sees
       it); ``RUF069`` covers ``==``/``!=`` only, not ordering comparisons; f-strings
       in logging *are* linted (``G004``) and were listed as review-only; the
       complexity section told readers to "correct" a suppression ``ruff.toml``
       deliberately defends; ``§6.6`` omitted ``RUF069`` from the test relaxations.
       **Removed non-existent references**: the ``_sort_model_methods.py`` fixer
       (never existed), ``odoo.tools.sql.rename_column``, and the
       ``web.dark_color_scheme`` bundle (dark mode is ``*.dark.scss`` globbed into
       ``web.assets_backend_dark``). Fixed the ``esm_graph.py`` path. Dropped the
       "Golden Rules" name for *Quick Reference*, folded four duplicated rule sets
       into single sources, condensed the review checklist to what tooling cannot
       check, and cut roughly a quarter of the length.
   * - 4.2
     - 2026-06-30
     - Reversed the XML-ID convention from suffix back to prefix to match core;
       documented the ``test_lint`` XML fixers, the single-line ``domain``/``context``
       rule, and the sorter-then-formatter order.
   * - 4.1
     - 2026-06-23
     - Expanded §2.4 method naming: mail and framework-hook rows, the
       naming-determines-section mapping, the field-wiring authority rule, and the
       class-eval ``default=`` note.
   * - 4.0
     - 2026-06-22
     - Reconciled the linter claims with ``ruff.toml``; fixed broken examples
       (``force_company``, ``_commit_progress``, ``_read_group`` unpack, ``Form``
       import); introduced the 🔧/👁 markers, a TL;DR and a glossary; added rules for
       ``Command``, ``models.Constraint``, ``@api.model_create_multi``, multi-company,
       float comparison and modern typing.
   * - 3.0
     - 2026-04-20
     - Prior canonical revision (suffix XML IDs, 16-section model layout, Sphinx
       docstrings, unified 13-tag commit catalog).

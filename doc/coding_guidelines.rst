.. _coding_guidelines:

=============================
AgroMarin Coding Guidelines
=============================

:Version: 4.1
:Date: 2026-06-23
:Language: English
:Base: `Odoo 19.0 Coding Guidelines <https://www.odoo.com/documentation/19.0/contributing/development/coding_guidelines.html>`_ + `OCA CONTRIBUTING.rst <https://github.com/OCA/odoo-community.org/blob/master/website/Contribution/CONTRIBUTING.rst>`_

This is AgroMarin's single coding standard for the fork. For Odoo 19 API
changes, see ``odoo-19-development-context.md`` in the knowledge repository
(``knowledge/agromarin-knowledge/reference/``). A per-revision changelog lives
in *Appendix D — Document History*.

**Enforcement markers.** Every rule is one of:

* 🔧 — **machine-enforced** by ``ruff`` (or another tool); the cited code (e.g.
  ``B904``) blocks CI. If a rule says 🔧, ``ruff check`` will fail on a violation.
* 👁 — **review-enforced**; a human reviewer confirms it (see the §9 checklist).
  The linter does *not* catch it.
* 🔧👁 — partially linted, partially review (e.g. a linted rule with carve-outs,
  or a tool gate plus a manual PR step).

Where a section predates these markers, the enforcement is stated inline instead.
**Do not assume a rule is linted unless it is marked 🔧** — several rules that
*read* like lint rules are deliberately review-only because the corresponding
``ruff`` code is disabled (see §2.7, §2.9.7, §10.3, §10.4).

.. contents::
   :local:
   :depth: 2

Golden Rules (TL;DR)
--------------------

The one-screen cheat-sheet. Each links to the full rule. When in doubt, read the
section; when really in doubt, read the Odoo 19 source in ``core/``.

**Python**

* Double quotes everywhere; line length 88; ``ruff format`` is authoritative (§2.1). 🔧
* One model per file; file name = model ``_name`` (§1.3). 👁
* Every model declares ``_name`` **and** ``_description`` (§2.2, §M-rules). 👁
* Override ``create`` as ``@api.model_create_multi def create(self, vals_list)`` (§2.6). 👁
* Always ``super()`` in ``create``/``write``/``unlink``/``copy_data``/``default_get`` (§2.6). 👁
* Name new buttons ``action_*`` — but **never rename an inherited core method** (§2.4). 👁
* Use ``odoo.fields.Command`` for x2many writes, not raw ``(0, 0, {})`` tuples (§2.6). 👁
* Never compare money/floats with ``==``/``<`` — use ``float_compare``/``float_is_zero`` (§2.6). 🔧 ``RUF069``
* User-facing text goes through ``self.env._(...)`` with ``%s`` args, never f-strings (§2.7). 🔧 ``INT``
* ``raise X from Y`` inside ``except`` (§2.7). 🔧 ``B904``
* No ``cr.commit()`` in business code; the framework owns transactions (§2.6). 👁
* ``datetime.now(UTC)``; ``datetime.utcnow()`` is banned (§2.9.6). 🔧 ``DTZ003``

**Performance**

* ``search_count()`` not ``len(search())``; ``_read_group()`` not Python ``sum()`` (§11.2). 👁
* No ``search``/``search_count``/``_read_group`` inside a loop over a recordset (§11.1). 👁

**XML / JS**

* ``<list>`` not ``<tree>``; ``invisible=``/``readonly=`` not ``attrs=`` (§3.3). 👁
* XML IDs use the **prefix** style: ``view_sale_order_form``, ``action_sale_order`` —
  matching Odoo Community core; ``ref=`` a record by its real id (§3.2). 👁
* Frontend changes ship with a Hoot test or a tour (§4.4). 👁

**Process**

* Commit: ``[TAG] module: summary`` (≤ 50 char subject) + ``Solution:`` + ``Task ID`` (§7.1). 👁
* Branch: ``19.0-t<task>-<user>``; every commit references a Task ID (§7.2, §7.3). 👁
* Raw SQL in a PR ships ``EXPLAIN ANALYZE`` output (§11.8). 👁

Glossary
^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Term
     - Meaning
   * - ``$ACTIVE_REPOS``
     - The repositories in scope for these rules — the *Reach* table below
       (``agromarin``, ``core``, ``enterprise``, ``design-themes``).
   * - ``$DOMAIN``
     - The AgroMarin Odoo host (the internal project/task server used in PR links).
   * - TI
     - *Tecnología de la Información* — the systems/IT team that reviews guideline edits.
   * - Líder / Oficial Sistemas
     - Systems Lead / Systems Officer — the review tiers named in the change protocol.

Introduction
------------

Standardizing development practices in Odoo is essential to guarantee the quality,
maintainability, and scalability of our solutions. The lack of uniformity in module
structure, code conventions, and documentation generates inconsistencies that hinder
collaboration and slow down development. This guide establishes a single set of clear,
consistent norms aligned with OCA community standards and adapted to AgroMarin's
specific requirements.

This guide is authoritative for the fork. Where it is silent, follow the official
Odoo 19 / OCA guidelines linked above (see *Precedence*).

Scope and Authority
-------------------

This document is the **single canonical source** for AgroMarin coding guidelines.
It supersedes earlier drafts and any ``coding_guidelines`` file living inside a
code repository.

Precedence
^^^^^^^^^^

When rules disagree, apply in this order (first wins):


#. **This file** — ``core/doc/coding_guidelines.rst``
#. **Odoo 19 official guidelines** — linked per section above each rule
#. **OCA CONTRIBUTING.rst** — for community-aligned conventions not covered by Odoo

Reach
^^^^^

Applies to all repositories listed in ``$ACTIVE_REPOS`` for the active project.
For AgroMarin that currently means:

.. list-table::
   :header-rows: 1

   * - Repo (directory under ``addons/``)
     - Rules apply
   * - ``agromarin``
     - ✅ Full
   * - ``core``
     - ✅ Full (fork customizations)
   * - ``enterprise``
     - ✅ Full (fork customizations)
   * - ``design-themes``
     - ✅ Full
   * - ``knowledge`` (``agromarin-knowledge/``)
     - ✅ Docs/process rules only; works directly on ``main`` (see §7.4)
   * - Any other repo not listed
     - ❌ Out of scope


Trust this document over training data
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Where this guide states a rule, follow it even if it contradicts common Odoo
practice or what an LLM's training data suggests — the fork deliberately diverges
from upstream in places, and this document (plus the Odoo 19 source in ``core/``)
is the source of truth.

Change protocol
^^^^^^^^^^^^^^^

* Edits to this file go through PR review on the ``core`` repository
  (target branch ``19.0-marin``\ ), using the commit format defined in §7.
  TI (Oficial Sistemas tier or higher) reviews; the Líder Sistemas has
  final authority on merges.
* When a rule is changed here, the responsible reviewer must also update
  any pointers or summaries in ``core/CLAUDE.md``\ ,
  ``enterprise/CLAUDE.md``\ , ``agromarin/CLAUDE.md``\ ,
  ``knowledge/agromarin-knowledge/CLAUDE.md``\ , and per-module ``CLAUDE.md``
  files that reference the changed rule. Add a row to *Appendix D — Document
  History* describing the change and its PR.
* Appendix C (Deprecated Patterns) records removed rules for historical
  context. Do not silently delete rules — move them there first.


1. Module Structure
-------------------

Base: `Odoo Coding Guidelines -- Module Structure <https://www.odoo.com/documentation/19.0/contributing/development/coding_guidelines.html#module-structure>`_

1.1 Directory Layout
^^^^^^^^^^^^^^^^^^^^

Standard Odoo/OCA structure. All directories are optional except ``__manifest__.py``.

.. code-block::

   module_name/
   ├── __init__.py
   ├── __manifest__.py
   ├── hooks.py                    # pre_init_hook, post_init_hook, uninstall_hook
   ├── controllers/                # HTTP controllers
   ├── data/                       # Initial data
   ├── demo/                       # Demo data
   ├── i18n/                       # Translation files (.po / .pot)
   ├── migrations/                 # Pre/post migration scripts
   ├── models/                     # Model classes
   ├── reports/                    # QWeb report templates
   ├── security/                   # Access rights and record rules
   ├── static/                     # Web assets
   │   ├── description/
   │   │   └── icon.png
   │   ├── lib/                    # Third-party libraries (unchanged)
   │   └── src/
   │       ├── css/
   │       ├── js/
   │       ├── scss/
   │       └── xml/
   ├── tests/                      # Python and JS tests
   ├── views/                      # XML views (forms, lists, search, kanban, …)
   └── wizards/                    # TransientModel files (includes res.config.settings)

1.2 ``__manifest__.py`` Conventions
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Required keys: ``name``\ , ``version``\ , ``author``\ , ``category``\ , ``depends``\ , ``data``\ , ``license``.

.. code-block:: python

   {
       "name": "Module Name",
       "version": "19.0.1.0.0",       # OCA numbering
       "author": "AgroMarin",
       "category": "Sales",
       "depends": ["sale"],
       "data": [
           "security/ir.model.access.csv",
           "views/sale_order_views.xml",
       ],
       "license": "LGPL-3",
   }

Key rules:

* **Version format**: ``{odoo_version}.x.y.z`` — *x* major (breaking), *y* minor
  (new feature), *z* patch (bug fix).
* **Remove empty keys** rather than including them with empty values.
* **No** ``auto_install: True`` unless the module is a bridge between two
  independent modules (e.g. ``sale_crm`` bridges ``sale`` and ``crm``).
* **Demo data** goes in the ``demo`` key, not ``data``.
* **Minimal** ``depends`` — list only direct dependencies, not transitive ones.
* **External dependencies** must be declared AND pinned in a ``requirements.txt``
  at the addon root:

.. code-block:: python

   "external_dependencies": {
       "python": ["requests"],
       "bin": ["wkhtmltopdf"],
   },

1.3 File Naming
^^^^^^^^^^^^^^^^^^^^

**One model per file** (mandatory). File names derive from the model's ``_name``.

.. list-table::
   :header-rows: 1

   * - Type
     - Pattern
     - Example
   * - Python model
     - ``{model_name}.py``
     - ``sale_order.py`` for ``sale.order``
   * - Views
     - ``{model_name}_views.xml``
     - ``sale_order_views.xml``
   * - Data
     - ``{model_name}_data.xml``
     - ``sale_order_data.xml``
   * - Menus
     - ``ir_ui_menu_views.xml``
     - Single file, all menuitems
   * - Access rights
     - ``ir.model.access.csv``
     - Always CSV
   * - Groups
     - ``res_groups.xml``
     - Group definitions
   * - Record rules
     - ``ir_rule.xml``
     - All ``ir.rule`` records in one file
   * - Wizards
     - ``wizards/{model_name}.py`` + ``_views.xml``
     - Includes ``res.config.settings``


**Example module layout:**

.. code-block::

   sale_custom/
     models/
       sale_order.py                    # sale.order
       sale_order_line.py               # sale.order.line
       res_partner.py                   # res.partner (extension)
     views/
       sale_order_views.xml             # sale.order views
       sale_order_line_views.xml        # sale.order.line views
       ir_ui_menu_views.xml             # all menuitems
     wizards/
       res_config_settings.py           # settings (TransientModel)
       res_config_settings_views.xml
     security/
       ir.model.access.csv
       res_groups.xml                   # groups
       ir_rule.xml                      # record rules (ir.rule)

----

2. Python
---------

Base: `Odoo Coding Guidelines -- Python <https://www.odoo.com/documentation/19.0/contributing/development/coding_guidelines.html#python>`_

2.1 PEP 8 and Imports
^^^^^^^^^^^^^^^^^^^^^


* PEP 8 compliance, **line length = 88** (enforced by ``ruff format``\ )
* Break long lines at logical points; the formatter handles the mechanics
* Import order: stdlib, third-party, odoo, odoo.addons (alphabetical within each group — enforced by isort via ``ruff``\ )
* **Double quotes everywhere**: strings, field attributes, docstrings (enforced by ``ruff format`` with ``quote-style = "double"``\ )

.. code-block:: python

   import logging

   from odoo import api, fields, models
   from odoo.exceptions import UserError, ValidationError
   from odoo.fields import Domain
   from odoo.tools import LazyTranslate

   from odoo.addons.sale.models.sale_order import SaleOrder

2.2 Model Class Organization
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Private attributes first, then section-organized code.

.. code-block:: python

   class SaleOrder(models.Model):
       _name = "sale.order"
       _description = "Sales Order"
       _inherit = ["mail.thread", "mail.activity.mixin"]
       _order = "date_order desc, id desc"

**Section comments** use ``# UPPERCASE``. Standard order:

.. list-table::
   :header-rows: 1

   * - #
     - Section
     - Contains
   * - 1
     - ``# FIELDS``
     - All field declarations
   * - 2
     - ``# INDEXES``
     - ``models.Index()`` declarations
   * - 3
     - ``# CONSTRAINTS``
     - ``models.Constraint()`` declarations
   * - 4
     - ``# CONSTRAINT METHODS``
     - ``_check_*``\ , ``_validate_*`` methods
   * - 5
     - ``# CRUD METHODS``
     - ``create``\ , ``write``\ , ``unlink``\ , ``copy``\ , ``copy_data``
   * - 6
     - ``# COMPUTE METHODS``
     - ``_compute_*`` methods
   * - 7
     - ``# SEARCH METHODS``
     - ``_search_*`` methods
   * - 8
     - ``# INVERSE METHODS``
     - ``_inverse_*`` methods
   * - 9
     - ``# ONCHANGE METHODS``
     - ``_onchange_*`` methods
   * - 10
     - ``# ACTION METHODS``
     - ``action_*`` methods (UI-triggered)
   * - 11
     - ``# MAIL METHODS``
     - ``_message_*``\ , ``_notify_*``\ , ``_track_*``
   * - 12
     - ``# [DOMAIN] METHODS``
     - e.g. ``# INVOICING METHODS``\ , ``# PAYMENT METHODS``
   * - 13
     - ``# HELPER METHODS``
     - ``_prepare_*``\ , ``_get_*`` internals
   * - 14
     - ``# TOOLING``
     - Reusable utilities without object dependency
   * - 15
     - ``# VALIDATIONS``
     - ``_can_confirm_*`` framework methods
   * - 16
     - ``# HOOKS``
     - ``_auto_init``\ , ``init``\ , pre/post hooks


**Rules** 👁: Not all sections required — omit empty ones. Use ``# UPPERCASE``
banners; the dashed-banner variant used by Odoo core (``# ----`` above/below the
title, as in ``sale_order.py``) is also acceptable — be consistent within a file.
Sections 14–15 (``# TOOLING``, ``# VALIDATIONS``) are optional refinements of
``# HELPER METHODS``; use them only when the distinction is real. Domain-specific
sections (12) go after ACTION METHODS.

**Method ordering within COMPUTE and ONCHANGE sections** 👁: order for
readability — a compute that consumes another compute's output is defined
*after* it (define before use). Beyond that, group related methods together; no
strict numeric ordering is mandated (Odoo core does not follow one, and no tool
can verify it).

**Anti-pattern — wrong section placement:**

.. code-block:: python

   # ❌ Wrong: _check_date placed inside COMPUTE METHODS
   class ExampleModel(models.Model):

       # COMPUTE METHODS
       @api.depends("line_ids.price")
       def _compute_total(self):
           ...

       @api.constrains("date_end")          # ← belongs in CONSTRAINT METHODS
       def _check_date(self):
           ...

   # ✅ Correct: each method in its section
   class ExampleModel(models.Model):

       # COMPUTE METHODS
       @api.depends("line_ids.price")
       def _compute_total(self):
           ...

       # CONSTRAINT METHODS
       @api.constrains("date_end")
       def _check_date(self):
           ...

2.3 Field Conventions
^^^^^^^^^^^^^^^^^^^^^

**Ordering: semantic/functional grouping** (NOT by type) 👁.

Group related fields and label each group with a ``# <Noun> block`` (or
``# <Noun>``) comment; each model defines its own blocks based on its domain.
Semantic grouping is **strongly recommended** and is **expected on models with
~10+ fields**; small single-purpose models need not. (This is a house
convention, not a tooled rule — adoption in core and the fork is partial, so
reviewers apply judgement rather than rejecting every ungrouped field.)

..

   **Why not by type?** Grouping ``company_id`` (Many2one) after all ``Char/Boolean`` fields
   ignores that ``company_id`` is the primary context that determines the behavior of every
   other field. Semantic grouping reflects domain logic and makes models easier to understand.


**Example blocks** (from ``sale.order`` / ``order.mixin`` — not all apply to every model):

.. list-table::
   :header-rows: 1

   * - Comment
     - Fields
   * - ``# Financial block``
     - ``company_id``\ , ``currency_id``\ , ``currency_rate``\ , ``payment_term_id``\ , ``journal_id``
   * - ``# Partner block``
     - ``partner_id``\ , ``fiscal_position_id``
   * - ``# Responsible block``
     - ``user_id``\ , ``team_id``
   * - ``# Core identification``
     - ``name``\ , ``state``\ , ``priority``
   * - ``# Dates``
     - ``date_order``\ , ``date_validity``\ , ``date_confirmed``
   * - ``# Signature block``
     - ``require_signature``\ , ``signature``\ , ``signed_by``
   * - ``# Payment block``
     - ``require_payment``\ , ``prepayment_percent``
   * - ``# Order line block``
     - ``line_ids``\ , ``amount_untaxed``\ , ``amount_total``
   * - ``# Invoice block``
     - ``invoice_ids``\ , ``invoice_state``
   * - ``# Transaction block``
     - ``transaction_ids``\ , ``authorized_transaction_ids``
   * - ``# Transfer block``
     - ``picking_ids``\ , transfer-related fields
   * - ``# References``
     - ``origin``\ , ``notes``\ , ``tags``
   * - ``# UI block``
     - ``is_expired``\ , ``type_name``\ , ``show_*``\ , warnings


**Rules**\ :


* Models use only the blocks relevant to their domain and may define their own (e.g. ``# GPS block``\ , ``# Harvest block``\ )
* Relational fields (M2O, O2M, M2M) mix freely within block
* Line models open with ``related=`` fields from parent (\ ``order_id`` first)
* ``order.mixin`` defines canonical base ordering for order-type models

**Anti-pattern — ordering by field type:**

.. code-block:: python

   # ❌ Wrong: fields ordered by type, ignoring domain logic
   class SaleOrder(models.Model):
       # Char
       name = fields.Char()
       # Boolean
       is_locked = fields.Boolean()
       # Many2one                   ← company_id buried after primitives
       company_id = fields.Many2one("res.company")
       partner_id = fields.Many2one("res.partner")
       # One2many
       line_ids = fields.One2many("sale.order.line", "order_id")
       # Computed
       amount_total = fields.Float(compute="_compute_amounts")

   # ✅ Correct: fields grouped by functional domain
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
       amount_total = fields.Float(compute="_compute_amounts")

       # UI block
       is_locked = fields.Boolean()

**Naming patterns**:

.. list-table::
   :header-rows: 1

   * - Pattern
     - Convention
     - Example
   * - O2M/M2M
     - ``_ids`` suffix
     - ``order_line`` -> ``line_ids``
   * - M2O
     - ``_id`` suffix
     - ``partner`` -> ``partner_id``
   * - Dates
     - ``date_`` prefix
     - ``validity_date`` -> ``date_validity``
   * - Amounts
     - ``amount_`` prefix
     - ``total_amount`` -> ``amount_total``
   * - Counters
     - ``_count`` prefix
     - ``picking_count`` -> ``count_picking``
   * - Quantities
     - ``qty_`` prefix
     - ``delivered_qty`` -> ``qty_transferred`` (note: core also uses the
       ``product_qty`` / ``qty_done`` suffix forms — both coexist)
   * - Booleans
     - ``is_`` prefix
     - ``order_sent`` -> ``is_sent``
   * - State
     - ``_state`` suffix
     - ``invoice_status`` -> ``invoice_state``


Default functions: use ``lambda self:`` (allows inheritance).

.. code-block:: python

   user_id = fields.Many2one("res.users", default=lambda self: self.env.user)

2.4 Method Naming
^^^^^^^^^^^^^^^^^^^^^^

These naming rules are **review-only** 👁 — no ``ruff`` code enforces them. A
method's name is not just cosmetic: the prefix fixes the method's *role*, which
in turn fixes the §2.2 section it belongs to (see *Naming determines section*
below). Name and placement are two views of the same decision.

.. list-table::
   :header-rows: 1

   * - Pattern
     - Convention
     - Example
   * - Button actions
     - ``action_`` for **new** methods (not ``button_``\ )
     - new ``action_confirm`` (but keep inherited ``button_confirm`` — see below)
   * - View openers
     - ``action_view_`` for opening a view of records
     - ``action_view_invoices`` (``action_open_*`` stays valid for wizards/parent actions)
   * - Compute
     - ``_compute_`` (plurals when multi-field)
     - ``_compute_total`` -> ``_compute_amounts``
   * - Prepare vals
     - ``_prepare_*_vals`` (returns dict)
     - ``_get_invoice_vals`` -> ``_prepare_invoice_vals``
   * - Getters
     - ``_get_`` (replaces ``_find_``\ , ``_fetch_``\ )
     - ``_find_candidate`` -> ``_get_candidate``
   * - Onchange
     - ``_onchange_`` (always ``_`` prefix)
     - ``onchange_partner_id`` -> ``_onchange_partner_id``
   * - Constraints
     - ``_check_`` / ``_validate_``
     - ``verify_date`` -> ``_check_date``
   * - Extensible validation
     - ``_can_confirm_*``
     - ``_validate_before_confirm`` -> ``_can_confirm_order``
   * - Inverse
     - ``_inverse_``
     - ``set_quantity`` -> ``_inverse_quantity``
   * - Search
     - ``_search_``
     - ``_search_display_name(self, operator, value)`` (API hook, see below)
   * - Mail
     - ``_message_*`` / ``_notify_*`` / ``_track_*``
     - ``_track_subtype``, ``_notify_get_recipients``
   * - Default
     - ``_default_``
     - ``get_default_warehouse`` -> ``_default_warehouse_id``
   * - Framework hooks
     - ``_auto_init`` / ``init`` (raw schema/registry setup)
     - keep core signatures; rarely overridden


**Inheritance safety** 👁: these naming rules apply to **new** methods you
author. **Never rename an inherited Odoo core method** to fit them — Odoo core
ships 100+ ``button_*`` methods (with matching XML ``name="button_*"`` bindings)
and 140+ ``action_open_*`` methods (e.g. ``ir.cron.action_open_parent_action``).
Renaming one breaks the XML binding and every ``super().button_*()`` caller.
Override core methods under their **original** name.

``_search_display_name`` is not a cosmetic rename — it is the Odoo 19 **API hook**
(signature ``_search_display_name(self, operator, value)``) that backs
``name_search``; override it, not the removed ``_name_search``.

**Naming determines section** 👁: because the prefix fixes the method's role, it
also fixes which §2.2 section the method belongs to. Use this mapping both
ways — when naming a new method, and when deciding where to place it:

.. list-table::
   :header-rows: 1

   * - Name / decorator
     - §2.2 section
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
   * - ``_check_*`` / ``_validate_*``; ``@api.constrains``
     - ``# CONSTRAINT METHODS``
   * - ``action_*``
     - ``# ACTION METHODS``
   * - ``_message_*`` / ``_notify_*`` / ``_track_*``
     - ``# MAIL METHODS``
   * - ``_prepare_*`` / ``_get_*`` and other internals
     - ``# HELPER METHODS``
   * - ``_auto_init`` / ``init``
     - ``# HOOKS``

The **field wiring is authoritative** when it disagrees with the name: a method
referenced by ``inverse="..."`` *is* an inverse even if it is named ``_write_*``
or ``set_*``, and ``compute="..."`` / ``search="..."`` likewise pin their target's
section regardless of prefix.

A method used as a field ``default=`` (e.g. ``default=_default_category``) is
evaluated at **class-creation time**, so it must be defined *above* the field
block; it stays pinned there rather than moving into a method section.

This mapping is mechanized by the standalone fixer
``odoo/addons/test_lint/tests/_sort_model_methods.py``, which regroups a model's
methods under the correct ``# UPPERCASE`` banners (run ``ruff format`` after). It
is behaviour-preserving — it only moves methods and refuses any change that would
alter a method body — and is **not** a blocking lint, since upstream ``base``
predates this ordering.


2.5 Docstrings
^^^^^^^^^^^^^^

Mandatory on **models** and **complex methods** 👁. Simple getters/setters may
omit. Note: ``ruff``'s ``D`` (pydocstyle) is linter-enforced **only** in
``odoo/libs/`` and ``odoo/orm/components/`` (pure-Python packages); for all addon
code under ``addons/**`` it is suppressed in ``ruff.toml``, so this is a
**review-only** expectation there.

**Template** (Sphinx format):

.. code-block:: python

   class SaleOrder(models.Model):
       """Sales order management with multi-currency support."""

       def _prepare_invoice_vals(self, order_line):
           """Prepare values dictionary for invoice creation.

           :param recordset order_line: sale.order.line records to invoice
           :return: dictionary of invoice values
           :rtype: dict
           """

**Rules**\ :


* Model docstring: one line describing the entity's purpose
* Method docstring: brief description, then `:param`, `:return:`, `:rtype:` if non-trivial
* Use ``"""triple double quotes"""`` — never ``'''single'''``
* No verbose field listings inside model docstrings (keep them in field ``help=`` attributes)

**Accuracy and concision** 👁: a docstring or comment that contradicts the code
is worse than none — it misleads the reader and outlives the code it described.
When you change a signature, return type, or behavior, update its docstring in
the *same* edit.

* **Be correct.** Verify every claim — parameters, return type, raised
  exceptions, referenced methods/fields — against the actual code. Delete stale
  references to renamed or removed code instead of letting them rot.
* **Be direct.** Cut filler: ``Basically``, ``Essentially``, ``In other words``,
  ``Note that``, ``Obviously``, ``This method simply…``. Describe behavior in the
  imperative — "Return…", "Raise…", "Compute…".
* **Don't restate the obvious.** A docstring that only echoes the method name, or
  re-types the signature already on the ``def`` line, is noise — omit it or say
  something the signature cannot.
* **Comments explain why, not what.** The code already states what it does;
  reserve comments for non-obvious rationale, an invariant, or an edge case. A
  comment that merely narrates the next line has earned its deletion.

2.6 ORM Best Practices
^^^^^^^^^^^^^^^^^^^^^^

These rules apply to every model in ``$ACTIVE_REPOS``.

**Always call** ``super()`` in ``create``\ , ``write``\ , ``unlink``\ , ``copy_data``\ ,
``default_get``\ , and ``_compute_display_name`` 👁. Overriding without delegation is
a regression vector. (Prefer overriding ``copy_data`` over ``copy`` in 19.0 — it
is the values hook ``copy`` builds on.)

**Override** ``create`` **with** ``@api.model_create_multi`` 👁 and the batch
signature ``def create(self, vals_list)``. The single-dict ``create(self, vals)``
form is obsolete:

.. code-block:: python

   @api.model_create_multi
   def create(self, vals_list):
       for vals in vals_list:
           ...
       return super().create(vals_list)

**Every new model declares** ``_name`` **and** ``_description`` 👁 (Odoo logs a
warning when ``_description`` is missing). Set ``_order`` when the default
insertion order is wrong. For the record label, set ``_rec_name = "<field>"`` for
a simple field, or override ``_compute_display_name`` (calling ``super()``) for a
computed label — do not override the removed ``name_get``.

**Let the framework manage transactions.** Do not call ``self.env.cr.commit()`` or
``rollback()`` from business code. Only the framework, cron runner, and custom
cursors (\ ``self.env.registry.cursor()``\ ) are allowed to commit.

**Assign fields directly in compute methods** (\ ``self.field = value``\ ). Using
``write()`` in a compute causes infinite recursion.

**Use** ``ensure_one()`` at the top of methods that operate on a single record:

.. code-block:: python

   def action_confirm(self):
       self.ensure_one()
       ...

**Use ``@api.ondelete`` for deletion constraints** (preferred over ``unlink`` override):

.. code-block:: python

   @api.ondelete(at_uninstall=False)
   def _unlink_if_draft(self):
       if any(r.state != "draft" for r in self):
           raise UserError(self.env._("Cannot delete a confirmed order."))

**Propagate context with** ``with_context`` — ``self.env.context`` is a frozen dict.
For **company scoping use** ``with_company`` — the ``force_company`` context key
was **removed in 19.0 and now raises** (``odoo/orm/models/mixins/env.py``):

.. code-block:: python

   order.with_context(tracking_disable=True).action_confirm()
   order.with_company(company).action_confirm()  # NOT with_context(force_company=...)

**Prefer recordset methods** (\ ``filtered``\ , ``mapped``\ , ``sorted``\ ) over manual loops:

.. code-block:: python

   confirmed = orders.filtered(lambda o: o.state == "sale")
   totals = orders.mapped("amount_total")

**Use** ``odoo.tools.groupby`` instead of ``itertools.groupby`` — it handles
recordsets correctly and does not require pre-sorting.

**Think extendable.** Avoid hardcoded values that could be configuration. Design
methods so other modules can override specific pieces without copy-paste.

**Deprecate with** ``@api.deprecated``\ :

.. code-block:: python

   @api.deprecated("Since 19.0, use _prepare_invoice_vals instead")
   def _prepare_invoice(self):
       return self._prepare_invoice_vals()

**Computed-field dependency rule** 👁: every sub-field accessed in a compute
body must appear in ``@api.depends`` (``"partner_id.country_id"``, not just
``"partner_id"``) — incomplete chains cause silent stale data. Full statement,
including the initialization-only exception, is in **§11.6** (single source).

**Performance rules** (enforced by ``ruff`` where possible):

.. list-table::
   :header-rows: 1

   * - Rule
     - Do
     - Don't
   * - Counts
     - ``search_count(domain)``
     - ``len(search(domain))``
   * - Existence
     - ``bool(search(domain, limit=1))``
     - ``search_count(domain) > 0``
   * - Aggregation
     - ``_read_group(domain, aggregates=["x:sum"])``
     - Python ``sum(r.x for r in search(...))``
   * - Batched create
     - ``create([vals1, vals2, ...])``
     - ``create(vals)`` inside a loop
   * - N+1 inside loops
     - Aggregate once with ``_read_group``\ , then dict-lookup
     - ``search()`` / ``search_count()`` inside ``for record in recs``
   * - Load + fetch
     - ``search_fetch(domain, fields, limit=...)``
     - ``search(...)`` then accessing fields


**``ormcache``**: use ``@ormcache`` for read-heavy, rarely-changing data; cached
methods **must not return recordsets** (return plain Python types). Full rule and
invalidation in **§11.5**.

**Indexing**\ : add ``index=True`` on fields used in ``search()`` domains, ``ORDER BY``\ ,
or ``GROUP BY``. Use ``models.Index()`` for composite/partial/BRIN/expression indexes.
Partial indexes are preferred when queries filter on a specific state.

**Locking**\ : use ``FOR UPDATE NOWAIT`` for critical sections, ``FOR UPDATE SKIP LOCKED``
for job queues. Always handle ``OperationalError`` when using ``NOWAIT``. Minimize
lock duration: lock → operate → commit as fast as possible.

**Raw SQL review rule**: any raw ``cr.execute()`` added to a PR must include
``EXPLAIN ANALYZE`` output in the PR description, demonstrating index use. This
is a review gate.

**Cron batch processing**: process large recordsets in batches with
``itertools.batched`` and ``self.env["ir.cron"]._commit_progress``. Do **not**
call ``cr.commit()`` directly. ``_commit_progress`` returns the **remaining cron
time in seconds** (not a record count), and its ``remaining`` argument is
keyword-only — full corrected pattern in **§11.10**. (``split_every`` is
deprecated since 19.0.)

2.7 Error Handling
^^^^^^^^^^^^^^^^^^

Use the most specific exception for the situation:

.. list-table::
   :header-rows: 1

   * - Exception
     - Use for
   * - ``UserError``
     - Business-logic violations visible to the user (invalid state, missing prerequisite)
   * - ``ValidationError``
     - Data-constraint failures inside ``@api.constrains``
   * - ``AccessError``
     - Permission or security violations (HTTP 403)
   * - ``RedirectWarning``
     - Errors the user can resolve by navigating to another view
   * - ``MissingError``
     - Record has been deleted or is inaccessible
   * - ``ValueError``
     - Invalid arguments in internal/private methods (not user-facing)


**All user-facing messages go through** ``self.env._()`` 🔧 ``INT`` (preferred over
the legacy ``_()`` — it takes the language from the environment instead of
walking the call stack, and works with lazy translations; ~4× faster for
``en_US`` per Odoo's benchmark):

.. code-block:: python

   raise UserError(self.env._("Order %s cannot be confirmed.", order.name))
   raise RedirectWarning(
       self.env._("Please configure a default warehouse."),
       action_id,
       self.env._("Go to Settings"),
   )

**Never leak internals**\ :

.. code-block:: python

   # ❌ Wrong — exposes stack internals, SQL fragments, paths
   except Exception as e:
       raise UserError(str(e))

   # ✅ Correct — generic user message, full traceback in log
   except Exception:
       _logger.error("Payment processing failed", exc_info=True)
       raise UserError(self.env._("Payment could not be processed. Contact support."))

**Fail-closed discipline**: exception handlers in state-mutation code must
leave the system in a consistent state. Wrap each iteration in a savepoint:

.. code-block:: python

   for order in orders:
       try:
           with self.env.cr.savepoint():
               order._process_payment()
               order.action_confirm()
       except UserError:
           order.state = "error"
           _logger.error("Failed to process order %s", order.name, exc_info=True)

``except Exception`` is a **review-only** rule 👁 — ``BLE001`` is intentionally
**disabled** in ``ruff.toml`` (Odoo legitimately catches ``Exception`` from
external/ORM calls), so the linter does *not* flag it. Use it only for
catch-log-reraise or integration adapters. In financial or state-mutation code,
log-and-continue is a violation — each failure must roll back or transition to
an explicit error state.

**Exception chaining** 🔧 ``B904``: always use ``raise X from Y`` (or
``from None``) so the original traceback is preserved. ``B904`` is **enforced**
in ``ruff.toml`` — both new and touched code must chain; a bare ``raise`` inside
``except`` fails ``ruff check``.

2.8 Controllers
^^^^^^^^^^^^^^^

HTTP controllers inherit from ``http.Controller`` and use the ``@route()`` decorator:

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

Key ``@route()`` parameters:

.. list-table::
   :header-rows: 1

   * - Parameter
     - Values
   * - ``type``
     - ``"http"`` (HTML/binary) or ``"jsonrpc"`` (JSON-RPC)
   * - ``auth``
     - ``"user"`` (default), ``"public"``\ , ``"bearer"`` (API token), ``"none"`` (no DB)
   * - ``methods``
     - ``["GET"]``\ , ``["POST"]``\ , etc.
   * - ``csrf``
     - Default ``True`` for ``http``\ , ``False`` for ``jsonrpc``


**Security rules**\ :


* ``auth="public"`` runs as Public user — unauthenticated visitors can call it. Validate and sanitize every parameter.
* Default all controller methods to private and expose only the ones the frontend actually calls.
* Use ``Markup()`` (from ``markupsafe``\ ) for intentional HTML; never format user input with f-strings inside ``Markup()`` — that is an XSS vulnerability.
* Route overrides: re-declare the route in the inheriting controller with ``@route()`` on the overriding method.

Response helpers: ``request.render(template, values)``\ , ``request.make_response(data, headers)``\ ,
``request.redirect(url)``.

2.9 Common Patterns
^^^^^^^^^^^^^^^^^^^

2.9.1 Domain class
~~~~~~~~~~~~~~~~~~

Odoo 19.0 ships a ``Domain`` class for programmatic domain construction:

.. code-block:: python

   from odoo.fields import Domain

   # Single condition
   domain = Domain("state", "=", "draft")

   # Boolean composition
   combined = Domain("state", "=", "draft") & Domain("partner_id", "!=", False)
   either = Domain("type", "=", "out_invoice") | Domain("type", "=", "out_refund")
   negated = ~Domain("active", "=", False)

   # Aggregate
   Domain.AND([dom1, dom2, dom3])
   Domain.OR([dom1, dom2])

   # Constants
   Domain.TRUE     # matches everything
   Domain.FALSE    # matches nothing

Use ``Domain`` for dynamic construction in Python. The list-of-tuples format
``[("field", "op", value)]`` remains valid for static domains in XML and data files.

2.9.2 Recordset safety
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   # Filter out records deleted by another transaction
   records = records.exists()

   # Empty recordset check
   partner = self.env["res.partner"].search([...], limit=1)
   if not partner:
       return

   # Verify a browsed record still exists
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
     - ``False`` → include archived records in searches (default ``True``\ )
   * - ``lang``
     - Force a language for translations
   * - ``tz``
     - Force a timezone for datetime display
   * - ``default_<field>``
     - Default value for ``<field>`` on new records
   * - ``active_ids``
     - List of record IDs from the source view (wizards/server actions)
   * - ``active_model``
     - Model name of the source records
   * - ``tracking_disable``
     - Disable mail tracking on ``write()`` — for bulk imports


Fields may declare a default context for relational access:

.. code-block:: python

   child_ids = fields.One2many(
       "res.partner", "parent_id", context={"active_test": False}
   )

2.9.4 Monetary fields
~~~~~~~~~~~~~~~~~~~~~

``fields.Monetary`` requires a companion currency:

.. code-block:: python

   currency_id = fields.Many2one("res.currency", required=True)
   amount_total = fields.Monetary()  # auto-picks currency_id

   # Custom currency field
   base_currency_id = fields.Many2one("res.currency")
   amount_in_base = fields.Monetary(currency_field="base_currency_id")

Omitting the currency field raises at runtime.

2.9.5 String formatting
~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Context
     - Use
     - Never
   * - General code
     - f-strings: ``f"{name} ({code})"``
     - —
   * - Exception messages
     - f-strings: ``raise ValueError(f"Invalid mode: {mode!r}")``
     - —
   * - Translations
     - ``%s`` format: ``self.env._("Order %s", order.name)``
     - f-strings inside ``_()`` (silently breaks extraction)
   * - Logging
     - ``%s`` format: ``_logger.info("Processing %s", count)``
     - f-strings (loses deferred formatting)
   * - SQL parameters
     - ``%s`` placeholder: ``cr.execute("... WHERE id = %s", (rid,))``
     - f-strings (SQL injection)
   * - HTML in errors
     - ``%``\ -style or ``.format()`` inside ``Markup()``
     - f-strings (XSS)


2.9.6 Datetime handling
~~~~~~~~~~~~~~~~~~~~~~~

``datetime.utcnow()`` is banned 🔧 — by **two** mechanisms: ``DTZ003`` (kept
enforced; most other ``DTZ`` rules are disabled because the ORM uses naive
datetimes) **and** ``flake8-tidy-imports`` ``banned-api``. Use ``datetime.now(UTC)``\ :

.. code-block:: python

   from datetime import UTC, datetime

   # Aware (external APIs, comparisons with aware datetimes)
   now_aware = datetime.now(UTC)

   # Naive (ORM Datetime fields — Odoo stores UTC without tzinfo)
   now_naive = datetime.now(UTC).replace(tzinfo=None)

**Common pitfall**\ : comparing aware ``datetime.now(UTC)`` with a naive ORM field
raises ``TypeError``. Strip ``tzinfo`` before comparing with ORM values.

2.9.7 Code hygiene (linter-enforced)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Rule
     - Enforcement
   * - No ``print()`` in production code
     - 🔧 ``T20`` (allowed in tests / CLI)
   * - No ``breakpoint()`` / ``pdb.set_trace()``
     - 🔧 ``T10``
   * - No mutable default arguments
     - 🔧 ``B006`` (use the ``None`` sentinel)
   * - Prefer ``pathlib.Path`` over ``os.path``
     - 🔧 ``PTH`` (relaxed in migrations)
   * - No ``optparse`` (use ``argparse``\ )
     - 🔧 ``banned-api``
   * - No commented-out code
     - 👁 review only — ``ERA001`` is **disabled** in ``ruff.toml`` (too many
       false positives in this doc-dense codebase). Delete dead code; rely on git.


**Cyclomatic complexity**: ``max-complexity = 20`` is configured for ``C90``, but
note ``C901`` (the message code) is currently in the ``ruff.toml`` ignore list,
so complexity is **not** actually blocking today — treat it as a review rule 👁
until the config is corrected (drop ``C901``/``PLR0912`` from ``ignore`` to make
it enforce). Method bodies above ~40 lines should be split regardless (the linter
cannot measure lines — review rule).

2.9.8 Logging levels
~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Level
     - Use for
   * - ``debug``
     - Development diagnostics — off in production by default
   * - ``info``
     - Normal business events (imports finished, cron ran)
   * - ``warning``
     - Recoverable issues (deprecated usage, fallback paths)
   * - ``error``
     - Unhandled exceptions, data corruption — include ``exc_info=True``


For cross-model operations (invoicing, EDI, payments), include a correlation
identifier in every log line so a business transaction can be traced end-to-end:

.. code-block:: python

   _logger.info("[order:%s] Starting invoice creation", order.name)
   _logger.info("[order:%s] PAC stamping completed, UUID: %s", order.name, uuid)

2.9.9 Type hints
~~~~~~~~~~~~~~~~

Optional but encouraged 👁 for public API, framework-level code, and complex
return types (``ANN`` is linter-enforced only in ``odoo/libs/`` and
``odoo/orm/components/``; review-only elsewhere). Python 3.14's PEP 649 deferred
annotations mean forward references work without string-quoting.

**Use modern generics** 🔧 ``banned-api``: ``list[X]``, ``dict[K, V]``,
``tuple[X, ...]``, ``X | None``. The legacy ``typing.Optional``\ /\ ``List``\ /\
``Dict``\ /\ ``Tuple``\ /\ ``Set``\ /\ ``Union`` are banned in ``ruff.toml``.

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

**Recommended** (not mandatory) 👁: apply ``@typing.override`` (Python 3.12+) to
``create``\ , ``write``\ , ``unlink``\ , ``copy_data``\ , and other overridden parent
methods — it catches silent breakage when a parent is renamed. It is not
linter-enforced (``ruff``'s ``TC``/type-checking group is deliberately disabled
for PEP-649 reasons), so the §9 checklist treats it as "should," not "must."

2.9.10 ``Command`` for x2many writes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use ``odoo.fields.Command`` for One2many/Many2many writes 👁 — never the raw
magic-tuples (``(0, 0, {...})``\ , ``(6, 0, [...])``\ , ``(4, id)``\ ), which are
unreadable and error-prone:

.. code-block:: python

   from odoo.fields import Command

   order.write({
       "line_ids": [
           Command.create({"product_id": p.id, "qty": 1}),  # was (0, 0, {...})
           Command.link(existing_line.id),                   # was (4, id)
           Command.set(new_line_ids),                        # was (6, 0, [...])
           Command.clear(),                                  # was (5, 0, 0)
       ],
   })

2.9.11 SQL constraints
~~~~~~~~~~~~~~~~~~~~~~~

Declare SQL constraints with ``models.Constraint`` (Odoo 19) 👁 in the
``# CONSTRAINTS`` section. The legacy ``_sql_constraints = [...]`` list is
deprecated — do not use it in new code:

.. code-block:: python

   # CONSTRAINTS
   _amount_positive = models.Constraint(
       "CHECK(amount >= 0)",
       "The amount must be positive.",
   )
   _code_unique = models.Constraint("UNIQUE(code, company_id)", "Code must be unique per company.")

2.9.12 Multi-company
~~~~~~~~~~~~~~~~~~~~

Multi-company correctness is a fork-wide requirement 👁:

* Relational fields that must stay within the record's company use
  ``check_company=True`` (the model needs a ``company_id``). The ORM then
  enforces company consistency on write.
* Per-company scalar configuration uses ``company_dependent=True``.
* Read the active company via ``self.env.company`` and scope work with
  ``with_company(company)`` — never hard-code or guess ``company_id``.
* Company record rules use ``[("company_id", "in", company_ids + [False])]`` so
  shared (company-less) records remain visible — see §10.x Access Control.

.. code-block:: python

   company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
   warehouse_id = fields.Many2one("stock.warehouse", check_company=True)
   default_journal_id = fields.Many2one("account.journal", company_dependent=True)

2.9.13 Float and currency comparison
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Never compare floats or Monetary values with** ``==``\ /\ ``!=``\ /\ ``<``\ /\ ``>``
directly 🔧 ``RUF069`` — binary float representation makes them unreliable. Use the
ORM helpers from ``odoo.tools``\ :

.. code-block:: python

   from odoo.tools import float_compare, float_is_zero, float_round

   rounding = order.currency_id.rounding
   if float_is_zero(line.price_subtotal, precision_rounding=rounding):
       ...
   if float_compare(paid, total, precision_rounding=rounding) >= 0:   # paid >= total
       order.state = "paid"
   amount = float_round(raw_amount, precision_rounding=rounding)

Pass ``precision_rounding=<currency>.rounding`` (or
``precision_digits=<n>``\ ) — do not invent epsilons.

2.9.14 Background jobs (``ir.job``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For deferred one-off work, use the framework job queue — **not** ad-hoc
threads, ``cr.commit()`` loops, or the legacy OCA ``queue_job`` module
(being phased out; its jobrunner/HTTP transport is superseded). Crons remain
the tool for *recurring* work; ``ir.job`` is for "run this call later,
in the background, with retries" 👁:

.. code-block:: python

   class StockPicking(models.Model):
       _inherit = "stock.picking"

       @api.job(channel="wms", max_retries=3)
       def _sync_to_wms(self, batch_size=100):
           ...

   # call site — enqueued in the current transaction, executed after commit
   picking.delayed(priority=5, eta=60)._sync_to_wms(batch_size=50)

Rules 👁:

* Job methods are **private** (``_``\ -prefixed; the ``@api.job`` decorator
  enforces it) and only decorated methods can be enqueued or executed —
  never widen a public method into a job.
* Arguments must be **JSON-serializable** (no recordsets or datetimes in
  ``args``\ /\ ``kwargs`` — pass ids and let the job re-browse; records the
  job targets go through ``delayed()``\ 's recordset itself).
* Write job bodies **idempotent or transactional-safe**: a job whose
  transaction rolled back may be retried; completion is atomic with the
  job's own writes, so partial effects never survive a crash — but external
  side effects (HTTP calls, mails) need their own guards.
* Transient conditions raise ``RetryableJobError(seconds=...)``
  (``odoo.exceptions``); any other exception also consumes a retry from
  ``max_retries`` before the job fails permanently.
* Concurrency is bounded per **channel** (``ir.job.channel`` capacity,
  implicit 1) — give heavy integrations their own channel instead of
  tuning priorities.
* Chain or fan-in with ``delayed(after=job_or_union)``; dedup bursts with
  ``identity_key``.
* Ops surface: Settings → Technical → Automation → Background Jobs
  (requeue / cancel / run manually); smoke-test a deployment with
  ``env["ir.job"].delayed()._job_ping()``.

2.10 Lazy imports
^^^^^^^^^^^^^^^^^

**All imports must be at module level unless there is a documented reason.**
Placing imports inside functions hides dependencies, duplicates code across
methods, and prevents tools from analyzing the module graph. ``PLC0415``
(import-outside-top-level) is globally suppressed in ``ruff.toml`` because Odoo's
architecture requires frequent lazy imports. When a lazy import is necessary,
include a **brief comment** explaining why.

**Acceptable reasons for lazy imports:**

#. **Circular dependency** that cannot be resolved by restructuring (e.g.
   ``odoo.tools`` importing from ``odoo.fields``)\ :

   .. code-block:: python

      def json_default(obj):
          from odoo import fields  # circular: tools→fields
          ...

#. **Optional external dependency** (guarded with ``try`` / ``except ImportError``\ ).
#. **Startup performance** in CLI entry points — deferring heavy Odoo imports so
   that ``--help`` stays fast.
#. **Namespace package** ``import odoo.addons`` — its ``__path__`` is populated
   dynamically by ``initialize_sys_path()``.
#. **Addon model imports from framework code** — model classes are not registered
   at framework import time.

**Not acceptable reasons:** "just in case", precautionary laziness, or the same
import repeated in multiple functions of the same file (a strong signal it should
be at module level).

**Detection rule:** if an import appears in two or more functions in the same
file, investigate whether it can be promoted. If the dependency direction allows
it, move it to the top.

----

3. XML
------

Base: `Odoo Coding Guidelines -- XML Files <https://www.odoo.com/documentation/19.0/contributing/development/coding_guidelines.html#xml-files>`_

3.1 Format and Indentation
^^^^^^^^^^^^^^^^^^^^^^^^^^


* **4 spaces** indentation
* Root element: ``<odoo>`` (not ``<data>``\ )
* Attribute order on records: ``id``\ , ``model``\ ; on fields: ``name`` first
* **Double-quoted** attribute values; self-closing empty elements (\ ``<field … />``\ )
* One blank line between top-level records; blank line after ``<odoo>`` and before ``</odoo>``
* **88-column** lines: a tag longer than 88 chars wraps **one attribute per line**
  (a lone attribute that is itself longer than 88 — a big ``domain``/``context`` —
  stays on its own line, since it cannot be split)
* Write multi-line ``domain``/``context``/``options`` values on a **single line**:
  XML normalises an attribute value's newlines to spaces, so the multi-line form
  is only cosmetic and the formatter cannot preserve it
* This is enforced, not aspirational — two canonical fixers in ``test_lint`` own
  it: ``_pretty_xml.py`` (formatting/wrapping) and ``_sort_xml_records.py``
  (``<field>`` child order + element attribute order). Run the sorter first, the
  formatter last (the formatter preserves order; the sorter does not preserve
  formatting). 🔧

3.2 XML IDs and Naming
^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Prefix style** — the role comes first, the model/entity follows. This matches
**Odoo Community core** (the codebase this repo forks), so new records sit next
to the core records they relate to, and inheriting or referencing a core record
needs no mental translation — you ``ref`` ids written in the same style you
author them in. The records in a typical data file are overwhelmingly views and
actions, and the leading ``view_`` / ``action_`` keyword groups them by role at
a glance.

.. list-table::
   :header-rows: 1

   * - Type
     - Pattern
     - Example
   * - Views
     - ``view_{model}_{type}``
     - ``view_sale_order_form``
   * - Actions
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
   * - Reports (action)
     - ``action_report_{name}``
     - ``action_report_saleorder``
   * - Report templates
     - ``report_{name}_document``
     - ``report_saleorder_document``
   * - Inherited views
     - ``view_{model}_{type}_inherit_{context}``
     - ``view_sale_order_form_inherit_custom``
   * - Server actions
     - ``action_{name}``
     - ``action_sale_order_cancel``
   * - Email templates
     - ``mail_template_{name}``
     - ``mail_template_sale_confirmation``


..

   **Note**\ : a few legacy core ids carry a model-first form
   (\ ``sale_order_menu``\ , ``sale_menu_root``\ ); leave those untouched and keep
   ``ref``\ -ing their real id. Multi-company record rules keep the core
   ``{model}_comp_rule`` form. See Appendix C for the retired suffix experiment.


3.3 View Structure Patterns
^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Form view:**

.. code-block:: xml

   <form>
     <header>
       <button string="Confirm" name="action_confirm" type="object"
               invisible="state != 'draft'" class="oe_highlight"/>
       <field name="state" widget="statusbar"/>
     </header>
     <!-- div.alert for warnings -->
     <sheet>
       <div name="button_box"><!-- stat buttons --></div>
       <div class="oe_title"><h1><field name="name"/></h1></div>
       <group name="main">
         <group name="left_col"><!-- fields --></group>
         <group name="right_col"><!-- fields --></group>
       </group>
       <notebook>
         <page string="Lines" name="lines"><!-- content --></page>
       </notebook>
     </sheet>
     <chatter/>
   </form>

**List view:**

.. code-block:: xml

   <list multi_edit="1">
     <header><!-- mass action buttons --></header>
     <field name="name"/>
     <field name="partner_id"/>
     <field name="amount_total" sum="Total"/>
     <field name="state" decoration-success="state == 'done'"/>
     <field name="technical_field" column_invisible="True"/>
     <field name="optional_field" optional="hide"/>
   </list>


* Use ``<list>`` (NEVER ``<tree>``\ )
* ``multi_edit="1"`` for inline editing
* ``column_invisible`` for always-hidden columns
* ``optional="show|hide"`` for user-toggleable columns
* ``decoration-*`` for conditional row styling

**Search view:**

.. code-block:: xml

   <search>
     <field name="name"/>
     <field name="partner_id"/>
     <filter string="Draft" name="draft" domain="[('state', '=', 'draft')]"/>
     <separator/>
     <filter string="My Orders" name="my_orders" domain="[('user_id', '=', uid)]"/>
     <group>
       <filter string="Partner" name="group_partner" context="{'group_by': 'partner_id'}"/>
     </group>
   </search>


* ``<group>`` without attributes (Odoo 19 — no ``expand``\ , no ``string``\ )
* Every filter **must** have ``name=""`` (for XPath inheritance)

**Kanban view:**

.. code-block:: xml

   <kanban default_group_by="state">
     <templates>
       <t t-name="card">
         <div class="card">
           <field name="name"/>
           <field name="partner_id"/>
         </div>
       </t>
     </templates>
   </kanban>


* CSS classes: ``card`` (not ``kanban-card``\ ), ``menu`` (not ``kanban-menu``\ )

**Calendar view:**

.. code-block:: xml

   <calendar date_start="date_order" date_stop="date_end" color="user_id">
     <field name="name"/>
     <field name="partner_id"/>
   </calendar>

**Graph / Pivot view:**

.. code-block:: xml

   <graph type="bar">
     <field name="date_order" type="row"/>
     <field name="amount_total" type="measure"/>
   </graph>

.. code-block:: xml

   <pivot>
     <field name="partner_id" type="row"/>
     <field name="state" type="col"/>
     <field name="amount_total" type="measure"/>
   </pivot>

**All views:** Use ``name=""`` on groups, pages, divs (enables clean XPath). Use Python
expressions directly (\ ``invisible=``\ , ``readonly=``\ ), NEVER ``attrs=``. Invisible fields for
expressions are auto-injected (18.0+).

3.4 Wizard Forms
^^^^^^^^^^^^^^^^^^^^^

TransientModel views go in ``wizards/`` directory (Python + XML).

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


* No ``<sheet>``\ , no ``<header>``\ , no ``<chatter/>``
* ``<footer>`` for action buttons (renders at dialog bottom)
* ``<separator/>`` for visual grouping
* ``nolabel="1"`` on full-width fields
* ``res.config.settings`` goes in ``wizards/``

3.5 View Inheritance
^^^^^^^^^^^^^^^^^^^^

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


* Prefer ``name=`` targets over positional XPath
* Positions: ``inside``\ , ``after``\ , ``before``\ , ``replace``\ , ``attributes``
* Template inheritance: ``priority="99"``
* ``hasclass()`` in XPath for CSS class targeting
* ``position="replace"`` with empty content to delete elements

3.6 Report Templates (QWeb)
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Three-part structure:

.. code-block:: xml

   <!-- 1. Document template -->
   <template id="report_sale_order_document">
     <t t-call="web.external_layout">
       <div class="page"><!-- content --></div>
     </t>
   </template>
   <!-- 2. Wrapper template -->
   <template id="report_sale_order">
     <t t-call="web.html_container">
       <t t-foreach="docs" t-as="doc">
         <t t-call="module.report_sale_order_document"/>
       </t>
     </t>
   </template>
   <!-- 3. Report action -->
   <record id="action_report_sale_order" model="ir.actions.report">
     <field name="name">Sales Order</field>
     <field name="model">sale.order</field>
     <field name="report_type">qweb-pdf</field>
     <field name="report_name">module.report_sale_order</field>
     <field name="report_file">module.report_sale_order</field>
     <field name="binding_model_id" ref="sale.model_sale_order"/>
     <field name="binding_type">report</field>
     <field name="binding_view_types">list,form</field>
   </record>


* ``report_name`` = ``module.template_id`` (required, points at the QWeb template).
  ``report_file`` is **optional** and may differ (it is a PDF base-filename hint);
  in core it is frequently omitted or set to a different template.
* ``binding_model_id`` for Print menu binding
* `binding_type`: `"report"` (Print) or `"action"` (Action); `binding_view_types`
  is order-significant — the common value is ``"list,kanban"`` (or
  ``"list,kanban,form"``\ ), not ``"list,form"``
* ``t-lang=`` at ``t-call`` level for localization

3.6.1 PDF rendering — WeasyPrint, not wkhtmltopdf 👁
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This fork renders ``qweb-pdf`` reports with **WeasyPrint** (real CSS Paged
Media). wkhtmltopdf is gone; forget its workarounds and its folklore. The
authoritative engine code is ``base/models/ir_actions_report.py``
(``WeasyPrintEngine``); the paged-media CSS lives in
``web/static/src/webclient/actions/reports/report_paged_media.css`` and
``report_pdf_layout.css`` — both have thorough header comments.

**Layout rules**

* Bootstrap **5** class names only: ``text-end``/``text-start``
  (``text-right``/``text-left`` no longer exist and silently do nothing),
  ``float-end``, ``ms-*``/``me-*``.
* Bootstrap responsive breakpoints (``col-md-*``, ``d-md-*``) are meaningless
  in paged media. Core layouts branch on ``report_type == 'pdf'`` and use CSS
  Grid there (``o_report_header_*``, ``o_report_footer_grid``) — follow that
  pattern; don't use ``<table>`` for pure layout.
* Put report CSS in an SCSS file added to ``web.report_assets_common`` (it
  benefits from the process-wide parsed-CSS cache), not in inline
  ``<style>`` blocks or ``style=`` attributes. Use the per-company design
  tokens (``--co-primary``, ``--co-font``, ``--rp-*``) instead of hardcoded
  colors.

**Paperformat**

* Live fields: ``format``/``page_width``/``page_height``, ``margin_*`` (mm),
  ``orientation``, ``header_line``, ``css_margins``.
* Dead wkhtmltopdf-era fields — do **not** set them on new paperformats:
  ``dpi``, ``header_spacing``, ``disable_shrinking``. Header/footer size is
  controlled by ``margin_top``/``margin_bottom``; the ``.header``/``.footer``
  divs become CSS running elements placed in the page margin boxes.

**Paged-media toolbox** (all supported, use instead of hacks)

* Page numbers: ``<span class="page"/>`` / ``<span class="topage"/>``
  (CSS counters — never JS).
* Break control: ``o_page_break_before`` / ``o_page_break_after`` classes,
  ``break-inside: avoid``; ``o_thead_no_repeat`` to stop ``<thead>``
  repetition on long tables.
* PDF outline: ``bookmark-level`` is set on ``h2[name="document_title"]`` /
  ``h3[name]`` — use real headings and multi-record batches get a navigable
  outline for free.
* Advanced (available, adopt where they fit): ``string-set`` running headers
  ("Invoice X — continued"), ``target-counter()`` + ``leader('.')`` for
  TOC/cross-references, named ``@page`` rules for landscape annexes,
  ``float: footnote`` for legal boilerplate.
* PDF/A-3 + Factur-X and XMP metadata are supported natively — see
  ``_build_pdf_options``.

**Testing note**: in test mode ``_render_qweb_pdf`` returns raw HTML unless
``force_report_rendering`` is set; render-path tests live in
``base/tests/test_reports.py``.

3.7 Action Windows
^^^^^^^^^^^^^^^^^^

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


* ``view_mode`` ordering: kanban-first (UX), list-first (admin/reports)
* ``path`` field for readable URLs (18.0+)
* ``context`` for ``search_default_{filter_name}``
* ``domain``\ : use ``uid`` for current user (no quotes)
* ``help type="html"`` with ``o_view_nocontent_smiling_face``

3.8 Settings Views (18.0+)
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: xml

   <!-- wizards/res_config_settings_views.xml -->
   <record id="res_config_settings_view_form_inherit" model="ir.ui.view">
     <field name="name">res.config.settings.form.inherit.module</field>
     <field name="model">res.config.settings</field>
     <field name="inherit_id" ref="base.res_config_settings_view_form"/>
     <field name="arch" type="xml">
       <xpath expr="//form" position="inside">
         <app string="My Module" name="my_module">
           <block title="Features">
             <setting string="Feature X" help="Enable feature X">
               <field name="enable_feature_x"/>
             </setting>
           </block>
         </app>
       </xpath>
     </field>
   </record>


* New structure: ``<app>`` -> ``<block>`` -> ``<setting>``
* File: ``wizards/res_config_settings_views.xml``

3.9 Menu Files
^^^^^^^^^^^^^^^^^^^

Single file per module: ``views/ir_ui_menu_views.xml``.

.. code-block:: xml

   <odoo>
     <menuitem id="menu_sale_root" name="Sales" sequence="10"/>
     <menuitem id="menu_sale_order" name="Orders"
               parent="menu_sale_root" action="action_sale_order" sequence="1"/>
   </odoo>

All menuitems in one file (not scattered across view files).

3.10 Domains
^^^^^^^^^^^^

Use lists ``[]`` not tuples ``()`` in XML domains.

.. code-block:: xml

   <!-- Correct -->
   domain="[('company_id', 'in', [False, company_id])]"
   <!-- Wrong -->
   domain="[('company_id', 'in', (False, company_id))]"

----

4. JavaScript
-------------

Base: `Odoo Coding Guidelines -- JavaScript <https://www.odoo.com/documentation/19.0/contributing/development/coding_guidelines.html#javascript>`_

4.1 File Organization
^^^^^^^^^^^^^^^^^^^^^


* **Colocate** each component's ``.js`` and ``.xml`` template in a feature folder
  (``static/src/<feature>/<component>.js`` + ``<component>.xml``) — the modern core
  layout. The flat ``static/src/js/`` + ``static/src/xml/`` split is legacy.
* ES6 imports, no ``require()``

.. code-block:: javascript

   import { Component } from "@odoo/owl";
   import { registry } from "@web/core/registry";
   import { _t } from "@web/core/l10n/translation";


* ``/** @odoo-module **/`` is a **header directive for the asset bundler** (parsed
  in ``odoo/libs/esm_graph.py``), not a cosmetic comment. Files under
  ``static/src`` / ``static/tests`` are routed through the ESM pipeline by **path**,
  so the bare header is **optional** there. Use it explicitly when you need a
  modifier, or for a file outside those paths:

  * ``@odoo-module ignore`` — keep the file **out** of the ESM pipeline (plain
    classic script / vendored lib).
  * ``@odoo-module native`` — treat as a true native ES module.
  * ``@odoo-module alias=<specifier>`` — register under an additional import path.
  * ``@odoo-module default=<name>`` — control default-export bridging.

4.2 Naming
^^^^^^^^^^


* **When JS calls a Python method, the string must match exactly**: an ORM call
  or button ``name`` that targets ``action_view_invoices`` must use that exact name.
  Frontend-only handlers stay camelCase (next bullets) — this rule is about the
  call target, not all JS methods.
* Portal template ``t-name`` values follow field naming conventions (e.g. ``invoice_state``\ , not ``invoice_status``\ )
* Component names: PascalCase (\ ``MyComponent``\ )
* Methods/variables: camelCase (\ ``onButtonClick``\ )

4.3 OWL Framework
^^^^^^^^^^^^^^^^^

OWL is the component framework behind Odoo's web client. These rules apply to
every ``.js`` file that declares or patches a component.

4.3.1 Critical rules
~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Rule
     - Detail
   * - **``@odoo-module`` is a bundler routing flag**
     - Optional under ``static/src`` (path auto-routes); required outside it and for
       the ``ignore`` / ``native`` / ``alias=`` / ``default=`` modifiers (see §4.1)
   * - **Always ``super.setup()`` first**
     - When patching, call ``super.setup()`` before anything else
   * - **Use ``useState`` for reactive state**
     - Plain object assignments do not trigger re-render
   * - **Verify import paths before using**
     - Odoo moves components between releases — assume training data is stale
   * - **POS: ``t-inherit`` for markup, ``patch`` for behavior**
     - Prefer template inheritance (``t-inherit``) and ``patch()`` (both standard in
       core POS). Reserve ``onMounted`` DOM access for measurement/focus — not as a
       substitute for templating (raw DOM injection breaks on re-render)


4.3.2 Patch template
~~~~~~~~~~~~~~~~~~~~

.. code-block:: javascript

   import { patch } from "@web/core/utils/patch";
   import { ProductCard } from "@point_of_sale/app/components/product_card/product_card";
   import { useService } from "@web/core/utils/hooks";
   import { useState, onWillStart, onMounted } from "@odoo/owl";

   patch(ProductCard.prototype, {
       setup() {
           super.setup();  // ALWAYS first
           this.orm = useService("orm");
           this.customState = useState({ data: null });
           onWillStart(async () => {
               this.customState.data = await this.orm.call(
                   "product.product", "custom_read", [],
               );
           });
           onMounted(() => {
               // DOM manipulation that runs after the component is in the DOM
           });
       },
   });

4.3.3 Decision tree for frontend work
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block::

   Need frontend modification?
   ├─ Change markup of an existing component? → t-inherit template
   ├─ Change behavior of an existing component? → patch(Component.prototype, { ... })
   ├─ Brand new UI element?          → New OWL component + register in registry
   │   └─ Needs popup?               → Register in the pos_popups registry
   └─ Unsure?                        → Read reference/owl/ before guessing

4.3.4 Common POS import paths
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: javascript

   import { ProductCard } from "@point_of_sale/app/components/product_card/product_card";
   import { Orderline } from "@point_of_sale/app/components/orderline/orderline";
   import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
   import { patch } from "@web/core/utils/patch";
   import { useService } from "@web/core/utils/hooks";
   import { useState, onWillStart, onMounted } from "@odoo/owl";

Full OWL reference (hooks, stores, lifecycle) lives in
``knowledge/agromarin-knowledge/reference/owl/``.

4.4 JavaScript tests
^^^^^^^^^^^^^^^^^^^^

Frontend changes ship with a test 👁. Odoo 19 uses two layers (QUnit is removed —
do not write QUnit):

* **Unit / component tests — Hoot.** Files live in ``static/tests/**/*.test.js``
  and import from ``@odoo/hoot`` / ``@odoo/hoot-dom``. Use the mock server for ORM
  calls. This is the default for component logic and pure functions.

  .. code-block:: javascript

     import { expect, test } from "@odoo/hoot";
     import { click } from "@odoo/hoot-dom";

     test("counter increments on click", async () => {
         // mount component, then:
         await click("button.increment");
         expect("span.value").toHaveText("1");
     });

* **Integration / E2E — tours.** Register a tour in the ``web_tour.tours`` registry
  and drive it from a Python ``HttpCase`` (tagged ``@tagged("post_install", "-at_install")``\ )
  via ``self.start_tour(url, "tour_name", login=...)``. Use tours for flows that
  span the backend and UI.

----

5. CSS / SCSS
-------------

Base: `Odoo Coding Guidelines -- CSS and SCSS <https://www.odoo.com/documentation/19.0/contributing/development/coding_guidelines.html#css-and-scss>`_

5.1 Naming Conventions
^^^^^^^^^^^^^^^^^^^^^^


* Module-prefixed classes to avoid collisions: ``.o_module_name_element``
* Follow BEM-style or Odoo conventions as documented in the official guidelines

5.2 Organization
^^^^^^^^^^^^^^^^


* Files in ``static/src/css/`` or ``static/src/scss/``
* Declare in ``__manifest__.py`` under ``assets``\ , in the **correct bundle**:

.. code-block:: python

   "assets": {"web.assets_backend": ["module_name/static/src/scss/style.scss"]}

5.3 Asset bundles
^^^^^^^^^^^^^^^^^

Put each asset in the bundle that actually loads where it's needed — wrong-bundle
CSS either does nothing or bloats every page:

.. list-table::
   :header-rows: 1

   * - Bundle
     - Loads in
   * - ``web.assets_backend``
     - Backend web client (most module UI)
   * - ``web.assets_frontend``
     - Website / portal (public pages)
   * - ``point_of_sale._assets_pos``
     - Point of Sale client
   * - ``web.report_assets_common``
     - QWeb PDF reports (print styling)
   * - ``web._assets_primary_variables``
     - SCSS variable **overrides** (loaded before everything; no rules emitted)


5.4 Theming
^^^^^^^^^^^

* **Bootstrap-first.** Odoo's UI is Bootstrap 5 — reuse its utilities and
  components before writing custom SCSS.
* **Override variables, not values.** Customize via Odoo/Bootstrap SCSS variables
  (``$o-*``\ ) injected into ``web._assets_primary_variables`` (or
  ``..._secondary_variables``\ ) — never hard-code colors/spacing that a variable
  already controls.
* **Dark mode.** Drive colors from CSS variables / Odoo's color-scheme system
  (``web.dark_color_scheme``\ ); do not hard-code light-only hex values.
* **RTL.** Use logical properties (``margin-inline-start``, etc.) and Odoo's
  RTL-aware mixins instead of hard ``left``/``right`` — Odoo auto-generates RTL.

----

6. Tests
--------

Base: `Odoo Testing Reference <https://www.odoo.com/documentation/19.0/developer/reference/backend/testing.html>`_ | `OCA Guidelines -- Tests <https://github.com/OCA/odoo-community.org/blob/master/website/Contribution/CONTRIBUTING.rst>`_

6.0 Test infrastructure tiers
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The framework ships **three tiers** of test infrastructure. Pick the lightest
tier that can express the test. §6.1–§6.12 below concern Tier 3 (the integration
framework), which is what most addon tests use.

.. list-table::
   :header-rows: 1
   :widths: 16 38 46

   * - Tier
     - Entry point
     - Use when
   * - **1 — Component**
     - Component unit tests (``odoo/orm/components/tests/`` — ``FieldCache``,
       ``ComputeEngine``, ``ModelGraph``, ``UnitOfWork``)
     - Exercising ORM *algorithms* in isolation — cache, compute scheduling,
       flush convergence, trigger graph — directly against the real component
       objects. No real fields, no ``@api.depends``, zero ``odoo`` imports. ~3 ms.
   * - **2 — ORM, DB-free**
     - ``model_test_env`` / ``ModelRegistry`` (``odoo/orm/model_test_env.py``)
     - Testing real model methods, real ``@api.depends`` computes and real
       ``Field`` descriptors against an in-memory ``DictBackend`` — no PostgreSQL.
   * - **3 — Integration**
     - ``TransactionCase`` / ``HttpCase`` (``odoo/tests/``)
     - Anything needing SQL, ACL, multi-module, or web/tours. Seconds. Run via
       ``odoo-bin --test-enable`` (see §6.12).

Tiers 1 and 2 are plain ``pytest`` suites with **no database**. Tier 1's
hand-rolled dependency graph is the *subject under test* — it deliberately does
**not** reuse Tier 2's real ORM, so the component layer can be validated
standalone (this is intentional, not duplication to be "fixed").

Running the standalone (Tier 1 / Tier 2) suites takes **two** invocations:

.. code-block:: bash

   cd addons/odoo

   # Tier 1 component suite + standalone unit suites (config: addons/odoo/pytest.ini)
   pytest

   # Tier 2 real-ORM model suites + service tests — SEPARATE invocation.
   # The Tier 1 suites register process-global sys.modules stubs for odoo.*,
   # which would shadow these suites' real ``import odoo.*`` if run together.
   pytest odoo/orm/tests tests/service

The ``sys.modules`` stub bootstrap shared by the standalone suites lives in
``odoo/_testing_bootstrap.py``; each suite's ``conftest.py`` is a thin wrapper
around it.

6.1 Test Classes
^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Base Class
     - Use Case
   * - ``TransactionCase``
     - Standard ORM tests. Each method runs in its own rolled-back transaction.
   * - ``SingleTransactionCase``
     - Tests sharing state across methods (same transaction).
   * - ``HttpCase``
     - Controllers, web UI, Chrome headless. Tag with
       ``@tagged("post_install", "-at_install")``.

File layout:

.. code-block::

   tests/
     __init__.py
     test_sale_order.py
     test_sale_order_line.py

6.2 Test Isolation
^^^^^^^^^^^^^^^^^^

* **Create all test records** in ``setUpClass()`` or the test method.
* **Freeze time** — ``datetime.now()`` creates flaky tests. Use
  ``odoo.tests.freeze_time`` (Odoo-aware freezegun wrapper) or
  ``freezegun.freeze_time``.
* **Mock external services** — tests must run offline (``unittest.mock.patch``\ ).
* **Test with minimal permissions** — create a user with only the group being
  tested to catch access rule issues early.
* **Never call** ``cr.commit()`` **in tests** — all test data lives in the test
  transaction and is rolled back; a commit permanently pollutes the test DB. The
  **only** exception is a dedicated concurrency/cron test that deliberately opens a
  separate cursor (``self.registry.cursor()``\ ).
* A test class is **either** ``at_install`` **or** ``post_install`` — never both,
  never neither (the framework enforces this XOR). Use ``at_install`` for pure-ORM
  unit tests, ``post_install`` for anything touching other modules, web, or tours.

6.3 ``setUpClass`` Convention
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``@classmethod def setUpClass(cls)`` for creating test records shared across
test methods in a class — this runs once per class, not once per method:

.. code-block:: python

   @classmethod
   def setUpClass(cls):
       super().setUpClass()
       cls.partner = cls.env["res.partner"].create({"name": "Test Partner"})
       cls.product = cls.env["product.product"].create({"name": "Test Product"})

Use ``setUp(self)`` only when per-method state reset is required (e.g. mutable
state that one test method may alter in a way that affects another).

6.4 ``BaseCommon`` Test Mixin
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``odoo.addons.base.tests.common.BaseCommon`` provides a standard test environment
with mail/tracking disabled and convenience helpers. Use it when you want a quiet
(no-mail) setup; it is **not** the default base class (most tests still use
``TransactionCase``\ ). Note it does **not** create an independent user/company by
default — ``setup_independent_user``/``setup_independent_company`` return ``None``
unless a subclass overrides them.

.. code-block:: python

   from odoo.addons.base.tests.common import BaseCommon

   class TestSaleOrder(BaseCommon):
       @classmethod
       def setUpClass(cls):
           super().setUpClass()
           # cls.company, cls.currency, cls.partner already available
           cls.order = cls.env["sale.order"].create({...})

Key features:

* ``DISABLED_MAIL_CONTEXT`` — disables tracking, mail notifications, and password
  resets during test setup for performance.
* Pre-created ``cls.company``\ , ``cls.currency``\ , ``cls.partner``\ , and the groups
  ``cls.group_user``\ , ``cls.group_portal``\ , ``cls.group_system``.
* Helpers: ``quick_ref(xmlid)``\ , ``_create_partner()``\ , ``_create_new_internal_user()``\ ,
  ``_create_new_portal_user()``.

6.5 Flush Before Raw SQL in Tests
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When asserting on database state after ORM operations, call ``flush_model()`` or
``flush_recordset()`` before raw SQL queries:

.. code-block:: python

   def test_write_updates_database(self):
       self.order.write({"state": "sale"})
       self.order.flush_recordset(["state"])
       self.env.cr.execute(
           "SELECT state FROM sale_order WHERE id = %s", (self.order.id,)
       )
       self.assertEqual(self.env.cr.fetchone()[0], "sale")

Without flushing, the ORM may not have written pending values to the database yet.

6.6 Lint Relaxations in Tests
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

These rules are **suppressed** for test files (``**/tests/**``\ ) via
per-file-ignores in ``ruff.toml`` (the full set — keep this list in sync):

* ``print()`` (\ ``T201``\ ) and HTTP without ``timeout`` (\ ``S113``\ ).
* Broad ``assertRaises`` context managers (\ ``B017``\ ).
* ``global`` statements for test fixtures (\ ``PLW0603``\ ).
* Literal membership tests (\ ``PLR6201``\ ) and self-comparisons (\ ``PLR0124``\ ).
* First-element access via ``list(x)[0]`` (\ ``RUF015``\ ).
* ``try``/``except``/``pass`` cleanup (\ ``S110``\ ).
* Bare ``raise Exception()`` / useless try-except in fixtures (\ ``TRY002``\ ,
  ``TRY203``\ ); string literals in exceptions (\ ``EM101``\ ).
* Builtin shadowing in helpers (\ ``A001``\ , ``A002``\ ).

6.7 Test Naming
^^^^^^^^^^^^^^^

* Files: ``tests/test_<feature>.py``
* Classes: ``class TestFeatureName(TransactionCase):``
* Methods: ``def test_<specific_scenario>(self):``
* Use specific assertions (\ ``assertEqual``\ , ``assertIn``\ , ``assertRaises``\ )
  rather than bare ``assertTrue`` / ``assertFalse``.

6.8 Test Completeness
^^^^^^^^^^^^^^^^^^^^^

**Negative tests are mandatory.** Every test class must include at least one
test for an expected failure path:

* For constraints: verify that invalid input raises ``ValidationError``.
* For access rules: verify that unauthorized users get ``AccessError``.
* For workflows: verify that invalid state transitions fail.

**Parameterized tests** — use ``subTest()`` to cover multiple inputs in a single
method:

.. code-block:: python

   def test_tax_calculation(self):
       cases = [
           (100.0, 0.16, 16.0),
           (200.0, 0.08, 16.0),
           (0.0, 0.16, 0.0),
       ]
       for amount, rate, expected in cases:
           with self.subTest(amount=amount, rate=rate):
               result = self.env["account.tax"]._compute_amount(amount, rate)
               self.assertAlmostEqual(result, expected, places=2)

6.9 Test Structure
^^^^^^^^^^^^^^^^^^

Structure tests as **setup → action → assertion**, separated by blank lines (the
``# Arrange``/``# Act``/``# Assert`` comments below are illustrative, not required):

.. code-block:: python

   def test_order_confirmation_sets_date(self):
       # Arrange
       order = self.env["sale.order"].create({
           "partner_id": self.partner.id,
           "order_line": [Command.create({"product_id": self.product.id})],
       })

       # Act
       order.action_confirm()

       # Assert
       self.assertEqual(order.state, "sale")
       self.assertTrue(order.date_order)

6.10 Tagging
^^^^^^^^^^^^

* Default: ``standard`` + ``at_install``.
* For ``HttpCase``\ : ``@tagged("post_install", "-at_install")``.
* For slow/integration tests excluded from the standard run: ``@tagged("-standard")``
  (optionally with a real selector tag such as ``external`` or ``nightly`` that you
  then pass to ``--test-tags``). There is no ``heavy`` tag in core — don't invent one.

6.11 Coverage
^^^^^^^^^^^^^^^^^^

* Target **>80%** on custom modules (aspirational — not gated in CI today; see
  *Running tests* below for how to measure it locally).
* Test edge cases, constraints, and validations.
* Every ``action_*`` method should have at least one test.
* ``Form`` simulator (\ ``from odoo.tests import Form``\ ) for onchange testing
  without HTTP — **not** ``odoo.tests.common.Form`` (it is not exported there).
* Lock hot paths against N+1 regressions with ``with self.assertQueryCount(n):``
  (optionally ``@warmup`` to prime caches) — a query-count increase is a regression.
* ``@users("demo")`` decorator for multi-user permission testing.

6.12 Running tests
^^^^^^^^^^^^^^^^^^

.. code-block:: bash

   # All tests for a module (install + run its tagged tests)
   ./odoo-bin -d <db> -i <module> --test-enable --test-tags /<module> --stop-after-init

   # A single class or method
   ./odoo-bin -d <db> --test-enable --test-tags /<module>:TestClass.test_method --stop-after-init

   # The post_install (HttpCase / tour) phase
   ./odoo-bin -d <db> -i <module> --test-enable --test-tags post_install --stop-after-init

   # Coverage (the >80% target in §6.11)
   coverage run ./odoo-bin -d <db> -i <module> --test-enable --test-tags /<module> --stop-after-init
   coverage report

----

7. Git
------

Base: `OCA CONTRIBUTING.rst -- Git <https://github.com/OCA/odoo-community.org/blob/master/website/Contribution/CONTRIBUTING.rst>`_

7.1 Commit Messages
^^^^^^^^^^^^^^^^^^^

First line: ``[TAG] module: description`` — aim for ≤ 50 chars (Odoo's
recommendation), hard cap 72. Keep it shorter than the PR title (§7.4).

The ``module`` part is one of: a single module (snake_case, optionally with
``/`` or ``.`` sub-path separators, e.g. ``account_cfdi`` or ``stock/routes``);
a comma-separated list when the change spans several modules, following the
upstream Odoo convention (``[FIX] sale,purchase: ...`` — whitespace after the
comma is optional); or the standalone wildcard ``*`` for a tree-wide or generic
change (``[IMP] *: ...``). Prefer ``*`` over an unreadable module list (§7.4).

**Unified tag catalog** (13 tags — no other tags allowed). The first seven
(``FIX``, ``IMP``, ``ADD``, ``REM``, ``REF``, ``MOV``, ``REV``) are the upstream
Odoo set; the rest (``REL``, ``MERGE``, ``I18N``, ``PERF``, ``CLN``, ``LINT``) are
AgroMarin additions:

.. list-table::
   :header-rows: 1

   * - Tag
     - When to use
   * - ``FIX``
     - Bug fix
   * - ``IMP``
     - Improvement / enhancement to existing functionality
   * - ``ADD``
     - New module or feature
   * - ``REM``
     - Removal of code, files, or resources
   * - ``REF``
     - Refactor (no behavior change)
   * - ``MOV``
     - File relocation (preserve history with ``git mv``\ )
   * - ``REV``
     - Revert a previous commit
   * - ``REL``
     - Release / version-bump commit
   * - ``MERGE``
     - Merge commit
   * - ``I18N``
     - Translation update
   * - ``PERF``
     - Performance optimization
   * - ``CLN``
     - Code cleanup (no functional change) — stricter than ``REF``
   * - ``LINT``
     - Linting / formatting fix only


..

   **Deprecated tags**\ : ``[MIG]``\ , ``[CLA]``. ``MIG`` is covered by ``ADD``\ /\ ``REF`` on
   the migration script; ``CLA`` is covered by ``REF`` on the license/copyright
   change. See Appendix C.


**Tag choice rules**\ :


* One primary tag per commit (the dominant intent)
* If the change spans two intents, split the commit
* ``LINT`` and ``CLN`` must not contain any behavior change — if they do, use ``REF``

Body structure (mandatory):

.. code-block::

   [TAG] module: short summary (≤ 50 chars)

   Problem / context sentence explaining why this change was needed.

   Solution:
   - Point 1
   - Point 2

   Task ID: XXXXX

Example:

.. code-block::

   [IMP] product_asset: filter Fleet views by fuel card

   Fleet and Fleet Service Logs were showing all assets regardless
   of fuel card assignment, making the views noisy for operators.

   Solution:
   - Add domain filter on fuel_card_id to Fleet list view
   - Apply same filter to Fleet Service Logs list view

   Task ID: 17012

7.2 Branch Naming
^^^^^^^^^^^^^^^^^^^^^^

Format: ``<odoo_version>-t<task_id>-<github_username>``

.. code-block::

   19.0-t17352-suniagajose

7.3 Task ID Requirement
^^^^^^^^^^^^^^^^^^^^^^^^^^^^


* Every commit MUST reference an Odoo task ID
* Every branch MUST include the task ID
* Traceability: code change -> task -> business requirement

7.4 Pull Requests
^^^^^^^^^^^^^^^^^^^^^^

All code changes in ``$ACTIVE_REPOS`` (except the ``knowledge/`` repo, which works
directly on ``main``\ ) go through a pull request.

**Title**\ : ``[TAG] module: short description`` (OCA-style, matching the commit
convention). Keep it ``< 70 characters`` where possible. For a single-commit PR
the title mirrors the commit subject; for a change spanning several modules, use
the dominant functional scope (e.g. ``views``) rather than an unreadable module
list.

**Body template**\ :

.. code-block:: markdown

   # [Task ID: XXXXX](https://$DOMAIN/odoo/project.task/XXXXX)

   ## Problem

   One to three sentences on what the user/system was experiencing, or the
   business need driving this change.

   ## Solution

   - Bullet list of the changes actually applied
   - One bullet per logical unit, not per file

   ## Verification

   - Commands run, manual test steps, or a checklist
   - Include `EXPLAIN ANALYZE` output for any new raw SQL (§2.6 Performance)
   - Screenshot/GIF for UI changes

**Mandatory**\ :


* Task ID in the title line as a hyperlink (not plain text)
* At least one commit per logical unit — do not squash unrelated changes
* No merge commits from ``main`` in the PR history — rebase instead
* No force push to **shared** branches (\ ``main``\ , ``19.0``\ , ``19.0-marin``\ ,
  ``19.0-dev``\ ). Force-push **is** expected on your personal
  ``19.0-t<task>-<user>`` feature branch (rebasing it requires it).

----

8. Translations
---------------

Base: `Odoo Translations Reference <https://www.odoo.com/documentation/19.0/developer/reference/backend/module.html#translations>`_

8.1 Python
^^^^^^^^^^

Preferred: ``self.env._()`` (faster than the legacy ``_()`` — it reads the language
from the environment instead of walking the call stack; ~4× for ``en_US`` per
Odoo's benchmark — and resolves user language automatically).

.. code-block:: python

   message = self.env._("Order confirmed successfully")

For constants outside method context, use ``LazyTranslate``\ :

.. code-block:: python

   from odoo.tools import LazyTranslate
   _lt = LazyTranslate(__name__)

   STATES = [("draft", _lt("Draft")), ("done", _lt("Done"))]

8.2 JavaScript
^^^^^^^^^^^^^^

.. code-block:: javascript

   import { _t } from "@web/core/l10n/translation";

   const message = _t("Operation completed");

8.3 Frontend Module Registration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Required if your module has JS translations:

.. code-block:: python

   # models/ir_http.py
   class IrHttp(models.AbstractModel):
       _inherit = "ir.http"
       @classmethod
       def _get_translation_frontend_modules_name(cls):
           return super()._get_translation_frontend_modules_name() + ["my_module"]

8.4 ``.pot`` / ``.po`` workflow
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

* Keep a translation **template** at ``i18n/<module>.pot`` and language files at
  ``i18n/<lang>.po``. Export the template after changing user-facing strings:

  .. code-block:: bash

     ./odoo-bin -d <db> --i18n-export=i18n/<module>.pot --modules=<module> --stop-after-init

* Never hand-edit ``msgid`` values to "fix" English — change the source string and
  re-export. Translations are synced through **Weblate** (see ``core/.weblate.json``);
  do not commit machine-merged ``.po`` churn that fights the Weblate round-trip.

----

9. Code Review Checklist
------------------------

Use this 44-item checklist for every PR review. The reviewer confirms each
applicable item before approving. Non-applicable items (e.g. no raw SQL in the
diff) may be skipped with a note. The "Linter-enforced" group is what
``ruff check`` already blocks in **production** code — verify it still passes
(tests, CLI and migrations have documented relaxations); the other groups are
the human's job.

Security (8)
^^^^^^^^^^^^


#. ``cr.execute`` uses ``%s`` parameters or the ``SQL()`` wrapper — no f-strings / ``%`` / ``.format()``
#. ``sudo()`` calls whitelist the fields allowed when writing user-submitted payloads
#. Related fields pointing to sensitive models (\ ``ir.attachment``\ , ``hr.payslip``\ ) have explicit access controls
#. Public methods (no underscore prefix) are intentionally exposed as RPC endpoints
#. ``assert`` is not used for security validation — uses ``if ... raise`` instead
#. Exception handlers never expose raw tracebacks or SQL fragments to users
#. Error handling is fail-closed — partial operations wrapped in ``cr.savepoint()``
#. No hardcoded URLs, credentials, or service endpoints in Python code

Correctness (9)
^^^^^^^^^^^^^^^


#. ``search()`` / ``search_count()`` called outside loops (no N+1)
#. Compute methods assign fields directly (\ ``self.x = y``\ ), never ``write()``
#. CRUD overrides (\ ``create``\ , ``write``\ , ``unlink``\ , ``copy_data``\ ) call ``super()``; ``create`` uses ``@api.model_create_multi``
#. ``@api.depends`` lists every sub-field accessed in the method body
#. ``fields.Monetary`` has a matching currency field on the same model
#. Error types match intent: ``UserError`` for business, ``ValidationError`` for constraints, ``MissingError`` for deleted records
#. ``.exists()`` is called when records may have been deleted by another transaction
#. No mutable default arguments — uses the ``None`` sentinel pattern
#. Overridden framework methods *should* carry ``@typing.override`` (recommended, not gated)

Performance (7)
^^^^^^^^^^^^^^^


#. ``search_count()`` used for counts — not ``len(search())``
#. ``_read_group()`` used for aggregation — not Python-side ``sum()`` / ``len()`` over a recordset
#. Transactions managed by the framework — no ``cr.commit()`` outside ``_commit_progress()``
#. Cron jobs process in batches with ``itertools.batched`` and ``self.env["ir.cron"]._commit_progress()``
#. Locking uses ``NOWAIT`` or ``SKIP LOCKED`` — no unbounded waits
#. Raw SQL in the PR includes ``EXPLAIN ANALYZE`` output in the description
#. State-filtered tables use partial or expression indexes where appropriate

Testing (3)
^^^^^^^^^^^


#. Every test class includes at least one negative test (expected failure path)
#. Tests never call ``cr.commit()``
#. Parameterized scenarios use ``subTest()``

Style — human-reviewed (7)
^^^^^^^^^^^^^^^^^^^^^^^^^^


#. External HTTP requests (\ ``requests``\ , ``httpx``\ ) include a ``timeout`` parameter
#. Logging uses ``_logger`` with lazy ``%s`` formatting (no f-strings, no ``print()``\ )
#. ``_()`` / ``self.env._()`` receive literal strings with ``%s`` placeholders — no f-strings inside ``_()``
#. Company/user references use ``self.env.company`` / ``self.env.user``
#. Context reads use ``self.env.context.get()`` — not direct dict access
#. Methods stay under ~40 lines — extract sub-methods for longer logic
#. Comprehensions use at most one ``for`` and one ``if`` clause

Linter-enforced — verify ``ruff check`` passes, production code (10)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^


#. No ``print()`` or debugger statements in production code (\ ``T10`` / ``T20``\ )
#. No mutable default arguments (\ ``B006``\ ); no legacy ``typing.List``/``Optional`` (\ ``banned-api``\ )
#. ``pathlib.Path`` used instead of ``os.path`` (\ ``PTH``\ )
#. New exception re-raises use ``raise X from Y`` chaining (\ ``B904``\ )
#. No ``datetime.utcnow()`` — uses ``datetime.now(UTC)`` (\ ``DTZ003`` / ``DTZ004``\ )
#. ``ruff format`` has been run (consistent whitespace, double quotes, trailing commas)
#. External HTTP requests include a ``timeout`` parameter (\ ``S113``\ )
#. No ``verify=False`` in ``requests`` / ``httpx`` calls (\ ``S501``\ )
#. Regex patterns use raw strings ``r"..."`` — no unescaped backslashes (\ ``RUF039``\ )
#. No float equality in financial code — use ``float_compare()`` (\ ``RUF069``\ )

----

10. Security
------------

10.1 Method Visibility
^^^^^^^^^^^^^^^^^^^^^^

Public methods (no underscore prefix) are callable via XML-RPC/JSON-RPC by any
authenticated user. ACL checks only happen during CRUD operations — custom
public methods do **not** automatically enforce access rules.

* **Default all methods to private** (prefix with ``_``\ ). Remove the
  underscore only after deliberate review.
* Odoo 19 also provides ``@api.private`` to block RPC on a method that must keep a
  public **name** (e.g. an already-public method becoming internal). It is enforced
  at the RPC boundary across the MRO — a subclass cannot re-expose it. Use the
  ``_`` prefix for new code; ``@api.private`` to retrofit existing public methods.

10.2 ``sudo()`` Discipline
^^^^^^^^^^^^^^^^^^^^^^^^^^

* **Prefer narrower escalation.** ``with_user(user)`` / ``with_company(company)``
  keep ACL and record rules **enforced** under a specific identity — use them when
  you only need a different user/company, not a full bypass. Reserve ``sudo()`` for
  genuine cross-tenant/system operations.
* Whitelist which fields are allowed when writing user-submitted payloads under
  ``sudo()`` (a sudo *read* of one field is low-risk; ``sudo().write(payload)`` is
  the dangerous case).
* Minimize scope — apply ``sudo()`` to the smallest recordset and fewest
  operations. Every ``sudo()`` call should be flagged for review.

.. code-block:: python

   def action_update(self, values):
       allowed = {"description", "tag_ids"}
       safe_vals = {k: v for k, v in values.items() if k in allowed}
       self.sudo().write(safe_vals)

10.3 Input Validation
^^^^^^^^^^^^^^^^^^^^^

``assert`` statements are stripped when Python runs with ``-O`` (optimized
mode). Any validation that guards security-sensitive logic **must** use
``if`` / ``raise`` instead:

.. code-block:: python

   # Validate security-sensitive input
   if access_mode not in ("read", "write", "create", "unlink"):
       raise ValueError(f"Invalid access mode: {access_mode!r}")

This is a **manual review gate** 👁 — ``ruff``'s ``S101`` (assert-used) is disabled
(Odoo uses ``assert`` for ORM invariants), so the linter will **not** catch a
security ``assert``.

10.4 SQL Injection Prevention
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**All** dynamic SQL **must** use parameterized queries or the ``SQL`` wrapper.
f-strings, ``.format()``\ , and ``%`` formatting on query strings are violations —
even when the values come from ORM metadata like ``_table`` or ``field.name``.
Use the ``SQL`` wrapper for defense-in-depth:

.. code-block:: python

   from odoo.tools import SQL

   # Parameterized values
   self.env.cr.execute("SELECT id FROM res_partner WHERE name = %s", (name,))

   # SQL wrapper for dynamic identifiers (tables, columns)
   self.env.cr.execute(SQL(
       "SELECT id FROM %s WHERE %s = %s",
       SQL.identifier(model._table),
       SQL.identifier(field.name),
       value,
   ))

This is a **manual review gate** 👁 — ``ruff``'s ``S608`` (hardcoded-SQL) is
disabled because the ORM builds SQL dynamically via the ``SQL()`` wrapper, so the
linter does not flag f-string SQL. Reviewers must catch it (§9, Security #1).

10.5 Related Fields and ACLs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Related fields default to** ``compute_sudo=True``\ , so a related field
traversing into a sensitive model (\ ``ir.attachment``\ , ``hr.payslip``\ ) is read
as superuser and **bypasses the reader's ACL/record rules**. (Plain computed
fields default to ``compute_sudo = store`` — sudo only when stored.) To avoid a
leak on a sensitive related field, do **not** rely on field type — instead:

* set ``compute_sudo=False`` explicitly on that field, **or**
* restrict it with ``groups="..."``\ , **or**
* replace the related field with an explicit, ACL-respecting compute.

10.6 Controller Security
^^^^^^^^^^^^^^^^^^^^^^^^

* ``auth="public"`` runs as the Public user, including unauthenticated visitors.
* ``auth="none"`` means no database access — mainly for framework use.
* Validate and sanitize all controller parameters.
* Use ``Markup()`` for intentional HTML output; escape user-generated content.
* Do **not** set ``csrf=False`` on a ``type="http"`` POST route without a written
  justification (``jsonrpc`` is CSRF-exempt by design).
* Rate-limit and strictly schema-validate ``auth="public"`` endpoints. Validate and
  scope ``auth="bearer"`` tokens; never log them.

10.7 Fail-closed handling & error disclosure
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

These are security-critical, but the full rules live in **§2.7 Error Handling**
(single source) — do not duplicate:

* **Fail-closed**: wrap each iteration of state-mutation code in
  ``with self.env.cr.savepoint():`` so a failure rolls back or transitions to an
  explicit error state. ``except Exception`` log-and-continue is a violation in
  financial/state-mutation code. (``BLE001`` is **disabled** — this is review-only.)
* **No information disclosure**: never ``raise UserError(str(e))``. Log the
  traceback (``exc_info=True``\ ) and show a generic ``self.env._(...)`` message.

10.9 Configuration and Secrets
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

* **No hardcoded URLs, credentials, or service endpoints** in Python code. Use
  ``ir.config_parameter``\ , environment variables, or ``odoo.conf`` for all
  external configuration.
* **Namespace** config keys as ``<module>.<setting>`` (e.g.
  ``sale.default_warehouse_id``\ ); read with
  ``self.env["ir.config_parameter"].sudo().get_param(key, default)``.
* ``ir.config_parameter`` values are readable by ``base.group_system`` — for true
  secrets (API keys, tokens) prefer environment variables / ``odoo.conf``, not the DB.
* **External dependencies** must be declared in ``__manifest__.py``
  ``external_dependencies`` AND in a ``requirements.txt`` at the addon root.
  Pin minimum versions.

10.10 Deployment Checklist
^^^^^^^^^^^^^^^^^^^^^^^^^^

Before production deployment, verify:

* ``--dev`` mode is disabled.
* ``list_db = False`` in configuration.
* ``admin_passwd`` (master password) is changed from the default.
* ``proxy_mode = True`` if behind a reverse proxy; ``http_interface`` bound to
  localhost so only the proxy is public.
* ``dbfilter`` is set to restrict database access.
* ``server_wide_modules`` is minimal (the 19.0 default is ``base,rpc,web``\ ).
* ``workers`` > 0 (prefork); tune ``limit_time_cpu`` / ``limit_time_real`` /
  ``limit_memory_soft`` / ``limit_memory_hard`` / ``limit_request``.
* ``db_sslmode = require`` (or ``verify-full``\ ) — the default ``prefer`` does
  **not** enforce TLS to PostgreSQL.
* ``gevent_port`` is set for websockets/longpolling (the old ``longpolling_port``
  was removed); ``x_sendfile = True`` when fronted by nginx/apache; ``data_dir`` on
  a persistent, backed-up volume.
* Python dependencies are pinned with hashes. Run ``pip-audit`` in CI.

10.11 Access control (ACL & record rules)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Every new model ships explicit access rules 👁 — a model with no
``ir.model.access`` line is inaccessible (or, worse, silently admin-only).

* **ACLs** (table-level) go in ``security/ir.model.access.csv``\ : one line per
  (model, group) with ``perm_read,perm_write,perm_create,perm_unlink`` flags.
  Grant the minimum — e.g. a user group as ``1,1,1,0`` (no delete) and a manager
  group as ``1,1,1,1``\ ; avoid group-less (global) lines.
* **Record rules** (``ir.rule``\ , row-level) restrict *which* records a group sees
  — use them when access depends on the record's data (owner, company, state),
  not just the model. A global rule (no groups) applies to everyone.
* **Multi-company**: company rules use the domain
  ``[("company_id", "in", company_ids + [False])]`` so shared (company-less)
  records stay visible. Pair with ``check_company=True`` on relational fields
  (see §2.9.12).
* Restrict sensitive **fields** with ``groups="module.group_xxx"`` — field-level
  access is enforced on read and write.

11. Performance
---------------

11.1 Avoiding N+1 Queries
^^^^^^^^^^^^^^^^^^^^^^^^^

Any ``search()``\ , ``search_count()``\ , or ``_read_group()`` call inside a
``for`` loop over a recordset is a violation. Aggregate **outside** the loop
with ``_read_group()``\ :

.. code-block:: python

   groups = self.env["child.model"]._read_group(
       [("parent_id", "in", records.ids)],
       groupby=["parent_id"],
       aggregates=["__count"],
   )
   count_map = {parent.id: count for parent, count in groups}
   for record in records:
       record.child_count = count_map.get(record.id, 0)

Use dictionary lookups to avoid nested loops:

.. code-block:: python

   lines_by_order = defaultdict(list)
   for line in all_lines:
       lines_by_order[line.order_id.id].append(line)
   for order in orders:
       for line in lines_by_order[order.id]:
           ...

11.2 Batch Operations
^^^^^^^^^^^^^^^^^^^^^

* Use ``create()`` with a list of dicts (leverages ``@api.model_create_multi``\ )
  instead of calling ``create()`` in a loop.
* Use ``write()`` on a full recordset rather than iterating and writing
  individually.
* Use ``search_read()`` when you only need specific fields — more efficient
  than ``search()`` + ``read()``.
* **Use** ``search_count()`` **for counts** — never ``len(search(domain))``.
  ``search()`` instantiates all matching records in Python; ``search_count()``
  executes ``SELECT COUNT(*)`` server-side:

.. code-block:: python

   # Wrong — loads all records into memory
   count = len(self.env["account.move.line"].search(domain))

   # Correct — server-side count
   count = self.env["account.move.line"].search_count(domain)

   # For existence checks, use limit=1
   exists = bool(self.env["account.move.line"].search(domain, limit=1))

* **Use** ``_read_group()`` **for aggregation** — never Python-side ``sum()``
  over recordsets. Push computation to PostgreSQL:

.. code-block:: python

   # Wrong — loads every record into Python
   total = sum(line.amount for line in self.env["account.move.line"].search(domain))

   # Correct — single SQL query. Note the double-unpack: a groupless _read_group
   # returns [(value,)], so [[total]] extracts the scalar (not [total], a tuple).
   [[total]] = self.env["account.move.line"]._read_group(
       domain, aggregates=["amount:sum"],
   )

11.3 ``search_fetch()``
^^^^^^^^^^^^^^^^^^^^^^^

Use ``search_fetch()`` when you need a recordset with specific fields
pre-loaded. It combines ``search()`` and field fetching in minimal queries —
more efficient than ``search()`` followed by field access, and returns a proper
recordset (unlike ``search_read()`` which returns dicts):

.. code-block:: python

   # Optimal — search + fetch specific fields in minimal queries
   orders = self.env["sale.order"].search_fetch(
       [("state", "=", "sale")],
       ["partner_id", "amount_total", "date_order"],
       limit=100,
   )

11.4 Prefetching
^^^^^^^^^^^^^^^^

Iterating a recordset triggers automatic prefetching for all records in the
set. This is efficient for standard iteration. Disable prefetching with
``with_prefetch([])`` for large single-record operations where you don't want
the ORM to fetch all sibling records:

.. code-block:: python

   for record in large_recordset.with_prefetch([]):
       record._heavy_processing()  # only fetches fields for this record

11.5 ``ormcache``
^^^^^^^^^^^^^^^^^

Use ``@ormcache`` for read-heavy, rarely-changing data: model metadata, view
parsing results, ACL lookups, configuration values.

.. code-block:: python

   from odoo.tools import ormcache

   @ormcache("self.env.uid", "model_name")
   def _get_access_rights(self, model_name):
       """Return access rights dict. Must NOT return recordsets."""
       ...
       return rights_dict

**Critical constraint:** cached methods must **never return recordsets**. The
database cursor used to create the recordset will be closed on subsequent
calls, causing ``InterfaceError``. Return plain Python types (dicts, lists,
sets, tuples, scalars).

Invalidation: ``self.env.registry.clear_cache()`` clears all ormcache entries.
The ORM invalidates automatically on model changes via ``modified()``.

11.6 Computed Fields
^^^^^^^^^^^^^^^^^^^^

* Prefer ``store=True`` only when the field is used in search domains,
  ordering, or grouping. Non-stored computed fields avoid recomputation
  overhead on writes.
* **Every sub-field accessed in the method body must appear in**
  ``@api.depends``. Incomplete chains cause silent stale data. If the method
  reads ``record.partner_id.country_id``\ , then ``"partner_id.country_id"``
  **must** be in the decorator — ``"partner_id"`` alone is not sufficient:

.. code-block:: python

   @api.depends("partner_id.country_id")
   def _compute_country(self):
       for rec in self:
           rec.country_id = rec.partner_id.country_id

* Verification rule: for every ``record.x_id.y`` read inside the method,
  confirm that ``"x_id.y"`` (not just ``"x_id"``\ ) is listed in
  ``@api.depends``.
* **Exception — initialization-only computes**: when a
  ``store=True, readonly=False`` computed field is designed to set an initial
  default (e.g. inheriting ``lang`` from parent on reparenting), a coarser
  dependency like ``"parent_id"`` is intentional. Using ``"parent_id.lang"``
  would recompute and overwrite user edits whenever the parent's lang changes.
  Similarly, fields with an ``inverse`` that writes back to the same path must
  use a coarser dependency to avoid circular triggers.
* Avoid long chains of stored computed fields depending on each other —
  flatten dependencies when possible.

11.7 Indexing
^^^^^^^^^^^^^

* Add ``index=True`` to fields used in ``search()`` domains, ``ORDER BY``\ ,
  or ``GROUP BY``.
* Each index adds overhead to ``write`` and ``create`` — index selectively.
* Use ``models.Index()`` for composite indexes.

**Partial indexes** — for tables where most queries filter on a specific
state, a partial index is 10–50× smaller and faster than a full index:

.. code-block:: python

   # Only index non-done orders (the rows actually queried)
   _state_date_idx = models.Index("(date_order) WHERE state != 'done'")

**BRIN indexes** — for append-only or time-series tables (\ ``mail.message``\ ,
``ir.logging``\ , ``bus.bus``\ ), BRIN indexes are 100–1000× smaller than B-tree:

.. code-block:: python

   _create_date_brin = models.Index(
       "USING brin (create_date) WITH (pages_per_range=128)"
   )

**Expression indexes** — for case-insensitive search on fields commonly
queried with ``ilike``, add an expression index to avoid full table scans:

.. code-block:: python

   _name_upper_idx = models.Index("(UPPER(name))")

11.8 Raw SQL Review
^^^^^^^^^^^^^^^^^^^

Any raw SQL added via ``cr.execute()`` **must** include an ``EXPLAIN ANALYZE``
output in the pull request description, demonstrating that the query plan uses
indexes appropriately. This makes performance a code review gate.

11.9 Database Flush and Cache
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The ORM delays database writes for performance. Before executing raw SQL,
ensure consistency:

.. code-block:: python

   self.flush_model()         # write pending values to DB
   self.env.cr.execute(...)   # now raw SQL sees current data
   self.invalidate_model()    # refresh cache after direct SQL changes

11.10 Cron Jobs and Batch Processing
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Scheduled actions processing large recordsets **must** use batch processing
with progress tracking. Call ``self.env["ir.cron"]._commit_progress()`` to
commit each batch and report progress to the framework:

.. code-block:: python

   from itertools import batched

   def _cron_process_orders(self):
       orders = self.env["sale.order"].search([("state", "=", "pending")])
       commit_progress = self.env["ir.cron"]._commit_progress
       commit_progress(0, remaining=len(orders))  # set the total ONCE
       for batch_ids in batched(orders.ids, 100):
           batch = orders.browse(batch_ids)
           batch._process()
           # pass only `processed`; the framework decrements `remaining` for you
           time_left = commit_progress(processed=len(batch))
           if not time_left:        # 0 → cron time budget exhausted; it reschedules
               break

* Process in batches (100–1000 records) using ``itertools.batched()`` to limit
  memory and lock duration. (\ ``split_every`` is deprecated since 19.0.)
* ``_commit_progress(processed=0, *, remaining=None, deactivate=False)`` — note
  ``remaining`` is **keyword-only**. It commits internally and **returns the
  remaining cron time in seconds** (``inf`` outside a cron, ``0`` at the deadline)
  — *not* a record count. Set ``remaining`` once to the total; thereafter pass only
  ``processed`` and the framework decrements it.
* Set ``deactivate=True`` on the final call for one-time cron jobs.
* **Do not** call ``cr.commit()`` directly — the framework manages it through
  ``_commit_progress()`` and the cron runner.

11.11 Concurrency and Locking
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

PostgreSQL row-level locking prevents concurrent modifications:

.. code-block:: python

   # Fail immediately if another transaction holds the lock
   self.env.cr.execute(SQL(
       "SELECT id FROM %s WHERE id = %s FOR UPDATE NOWAIT",
       SQL.identifier(self._table), self.id,
   ))

   # Skip locked rows (job queues, cron dispatching)
   self.env.cr.execute(SQL(
       "SELECT id FROM %s WHERE state = %s FOR UPDATE SKIP LOCKED",
       SQL.identifier(self._table), "pending",
   ))

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Lock Mode
     - Use Case
   * - ``FOR UPDATE NOWAIT``
     - Critical sections (sequences, payment processing). Raises
       ``OperationalError`` if locked.
   * - ``FOR UPDATE SKIP LOCKED``
     - Job queues and cron dispatching. Silently skips locked rows.
   * - ``FOR NO KEY UPDATE``
     - When foreign key relationships are not affected by the update.

* Always handle ``OperationalError`` / ``LockError`` when using ``NOWAIT``.
* Minimize lock duration: lock → operate → commit as fast as possible.
* Prefer ORM-level ``search()`` with domain filters over table-level locks.

----

12. Migration Scripts
---------------------

12.1 Directory Structure
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block::

   migrations/
     19.0.1.1.0/
       pre-migrate.py
       post-migrate.py

The version directory matches the module ``version`` in ``__manifest__.py`` that
introduces the change. Both forms work: the **bare module version** (``1.2.0``\ ,
the common case) or the full ``19.0.1.2.0`` — Odoo prefixes bare versions with the
server major at load time. The special ``0.0.0`` directory runs on **every**
update. The script file is matched by its **prefix** (``pre-``/``post-``/``end-``),
so a descriptive suffix is allowed (``post-migrate_update_taxes.py``\ ), and both
``-migrate.py`` and ``-migration.py`` long forms are recognized.

Lint rules are **relaxed** for migration scripts (\ ``**/migrations/**``\ ) —
``E501`` (line length), ``UP`` (pyupgrade), ``PTH`` (pathlib), and ``ERA``
(commented-out code) are all suppressed because migration scripts use raw SQL,
legacy patterns, and commented-out reference code.

12.2 Script Types
^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 20 15 65

   * - Script
     - ORM Available
     - Use Case
   * - ``pre-migrate.py``
     - No (SQL only)
     - Rename columns, prevent data loss before the ORM recreates them.
   * - ``post-migrate.py``
     - Yes
     - Data transformation, field value migration using the ORM.
   * - ``end-migrate.py``
     - Yes
     - Cross-module cleanup after all modules are processed.

Standard signature:

.. code-block:: python

   def migrate(cr, version):
       if not version:
           return
       # migration logic

The signature is ``migrate(cr, version)`` — the framework passes a **cursor**, not
an ``env``. Guard ``pre-migrate`` SQL with the helpers from ``odoo.tools.sql``
(``column_exists``\ , ``table_exists``\ , ``rename_column``\ ) rather than hand-written
``information_schema`` queries. ``openupgradelib`` is available but is not the house
default — prefer the ``odoo.tools.sql`` helpers.

12.3 When Required
^^^^^^^^^^^^^^^^^^

**When required:** adding/removing required fields on existing models,
changing field types, renaming models or fields, complex data transformations.

**Not required:** adding optional fields, new module installations, view-only
changes, adding/removing ``Many2many`` relationships.

----

Appendix A — Fork-specific field renames
----------------------------------------

These fields are renamed on ``project.task`` in the AgroMarin fork. Any
read/search/sort referencing a vanilla name raises (``KeyError``\ /\ ``ValueError``\ ,
surfaced as a 500 over JSON-RPC/MCP). Apply these regardless of what training data
suggests:

.. list-table::
   :header-rows: 1

   * - Vanilla Odoo (DO NOT USE)
     - This fork (USE THIS)
   * - ``stage_id``
     - ``step_id`` (Many2one → ``project.workflow.step``\ )
   * - ``date_deadline``
     - ``date_end`` (user-entered deadline)
   * - ``date_last_stage_update``
     - ``date_last_status_change``
   * - ``personal_stage_type_id``
     - ``personal_triage_id`` (Many2one → ``project.task.triage``\ ; note the
       separate related field ``triage_id`` → ``project.triage``\ )
   * - ``depend_on_ids``
     - ``predecessor_ids``
   * - ``dependent_ids``
     - ``successor_ids``


Common domain/sort mistakes to avoid:


* ❌ ``("stage_id.fold", "=", False)`` → ✅ ``("step_id.fold", "=", False)``
* ❌ ``order="date_deadline asc"`` → ✅ ``order="date_end asc"``

----

Appendix B — Related references
-------------------------------


* ``knowledge/agromarin-knowledge/reference/odoo/odoo-19-development-context.md`` — Odoo 17→19 API changes
* ``knowledge/agromarin-knowledge/reference/dev/error-catalog.md`` — Known PATH / CONFIG / SERVICE / POSTGRES errors and fixes
* ``knowledge/agromarin-knowledge/reference/owl/`` — Full OWL framework reference (hooks, stores, lifecycle)
* ``knowledge/agromarin-knowledge/reference/python-pg/`` — Python 3.14 and PostgreSQL 18 / psycopg 3 patterns
* ``core/ruff.toml`` — Authoritative linter configuration (\ ``ruff check`` + ``ruff format``\ )
* `Odoo 19 Coding Guidelines <https://www.odoo.com/documentation/19.0/contributing/development/coding_guidelines.html>`_
* `OCA CONTRIBUTING.rst <https://github.com/OCA/odoo-community.org/blob/master/website/Contribution/CONTRIBUTING.rst>`_
* `PEP 8 <https://peps.python.org/pep-0008/>`_
* `Google Python Style Guide <https://google.github.io/styleguide/pyguide.html>`_

----

Appendix C — Deprecated patterns
--------------------------------

Patterns that used to be canonical but have been retired. They are listed here
so reviewers can flag them on sight and existing code can be migrated
opportunistically.

C.1 XML IDs — suffix style
^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Retired**\ : ``sale_order_view_form``\ , ``sale_order_action``\ , ``sale_order_menu``
(the short-lived model-first "suffix" experiment).

**Replaced by**\ : the prefix style in §3.2 (\ ``view_sale_order_form``\ ,
``action_sale_order``\ , ``menu_sale_order``\ ).

**Why**\ : the prefix style matches Odoo Community core — the codebase this repo
forks — so new records read the same as the core records they reference, and the
leading ``view_``/``action_`` keyword groups a data file by role. Maintaining a
second style on top of a prefix-style core only added translation friction every
time a core id was inherited or ``ref``\ -ed.

**Migration**\ : no rename of existing core ids — they are already prefix-style.
Any record created under the retired suffix convention is renamed back to prefix
when its surrounding file is next edited (\ ``[REF] module: rename XML IDs to
prefix style``\ ).

C.2 Commit tags — ``[MIG]`` and ``[CLA]``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Retired**\ : ``[MIG]`` (migration scripts), ``[CLA]`` (license/copyright updates).

**Replaced by**\ : ``[ADD]`` or ``[REF]`` on the migration script itself; ``[REF]`` on
the license change.

**Why**\ : both tags described the *subject* of the change, not the *intent*.
The intent (adding a script, refactoring a license block) is already covered
by the remaining 13 tags.

C.3 Python — field ordering by type
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Retired**\ : "Declare fields in the order Char → Integer → Float → Boolean →
Date → Datetime → Binary → Image → Selection → Html → Text → Many2one →
One2many → Many2many → Monetary → Related → Computed → Reference".

**Replaced by**\ : §2.3 — semantic blocks (\ ``# Financial block``\ , ``# Partner block``\ ,
etc.) declared per-model based on the domain.

**Why**\ : ordering ``company_id`` (Many2one) after every ``Char``\ /\ ``Boolean`` ignores
that ``company_id`` is the primary context for every other field. Semantic
grouping reflects domain logic and reads top-down like an invariant list.

C.4 Python — method ordering by Spanish category
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Retired**\ : "Order methods as Constructors → Computed → Onchange →
Validations → Actions → Business logic → Integrations".

**Replaced by**\ : §2.2 — 16 UPPERCASE section headers (\ ``# FIELDS``\ , ``# CRUD METHODS``\ ,
``# COMPUTE METHODS``\ , ``# ONCHANGE METHODS``\ , ...). Within a section, group
related methods and define a method before the ones that consume its output.

**Why**\ : the old ordering was a flat 7-bucket list that did not scale — there
was no home for ``# SEARCH METHODS``\ , ``# INVERSE METHODS``\ , or ``# MAIL METHODS``\ ,
and it did not specify the order within each bucket.

C.5 Docstrings — Google style
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Retired**\ : Google-style docstrings (\ ``Args:``\ , ``Returns:``\ , ``Raises:`` blocks).

**Replaced by**\ : §2.5 — Sphinx format (\ ``:param name: ...``\ , ``:return: ...``\ ,
``:rtype: type``\ ).

**Why**\ : Sphinx format matches what the Odoo codebase and upstream coding
guidelines use. Mixing styles inside the same repo defeats tooling that parses
docstrings (IDE tooltips, generated API docs).

C.6 XML — ``<tree>`` element
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Retired**\ : ``<tree>`` views and ``view_mode`` value ``tree``.

**Replaced by**\ : ``<list>`` and ``view_mode`` ``list`` (§3.3). Flag any ``<tree>``
on sight — Odoo 19 core is fully migrated.

C.7 XML — ``attrs=`` / ``states=``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Retired**\ : ``attrs="{...}"`` and ``states="..."`` on view nodes.

**Replaced by**\ : direct Python expressions ``invisible=``\ , ``readonly=``\ ,
``required=`` (§3.3). Removed in 17.0; invisible fields needed by expressions are
auto-injected.

C.8 Python — method renames that break inheritance
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Retired**\ : renaming inherited core methods to fit naming rules — e.g.
``button_confirm`` → ``action_confirm``\ , or treating ``action_open_*`` as forbidden.

**Replaced by**\ : §2.4 — apply naming rules to **new** methods only; override core
methods under their original name. ``action_open_*`` is a valid core convention.

C.9 Deprecated APIs flagged on sight
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

* ``split_every`` → ``itertools.batched`` (deprecated 19.0; §11.10).
* ``with_context(force_company=...)`` → ``with_company()`` (removed 19.0; §2.6).
* ``_sql_constraints = [...]`` → ``models.Constraint`` (§2.9.11).
* ``def create(self, vals)`` → ``@api.model_create_multi def create(self, vals_list)`` (§2.6).
* Magic x2many tuples ``(0, 0, {})`` → ``Command.*`` (§2.9.10).

----

Appendix D — Document History
-----------------------------

.. list-table::
   :header-rows: 1

   * - Version
     - Date
     - Summary
   * - 4.2
     - 2026-06-30
     - Reversed the XML-ID convention from **suffix** back to **prefix**
       (\ ``view_sale_order_form``\ , ``action_sale_order``\ ) to match Odoo Community
       core — rewrote §3.2 and flipped Appendix C.1 (now retiring the suffix
       experiment). Expanded §3.1 to document the canonical ``test_lint`` fixers
       (\ ``_pretty_xml.py`` formatting/88-col wrapping, ``_sort_xml_records.py``
       ordering), the single-line ``domain``/``context`` rule, and the sorter-then-
       formatter run order.
   * - 4.1
     - 2026-06-23
     - Expanded §2.4 (Method Naming): added Mail and Framework-hooks rows; added a
       *Naming determines section* mapping tying each prefix/decorator to its §2.2
       section; documented the field-wiring authority rule
       (``inverse=``/``compute=``/``search=`` override the method name) and the
       class-eval ``default=`` pinning note; referenced the new
       ``test_lint/_sort_model_methods.py`` method-grouping fixer.
   * - 4.0
     - 2026-06-22
     - Reconciled every "linter-enforced" claim with ``ruff.toml`` (B904, ERA001,
       BLE001, B006, S101/S608 manual gates); fixed broken examples
       (``force_company``\ , ``_commit_progress``\ , ``_read_group`` unpack, ``Form``
       import, ``heavy`` tag); added enforcement markers (🔧/👁), a Golden-Rules
       TL;DR and a glossary; added rules for ``Command``\ , ``models.Constraint``\ ,
       ``@api.model_create_multi``\ , multi-company, float comparison, modern typing;
       expanded §5 (asset bundles / theming) and added §4.4 JS testing, §6.12
       running tests, §10.11 access control; corrected §3.2 XML-ID rationale, §3.6
       reports, §4 ``@odoo-module`` semantics; fixed Appendix A
       (``personal_triage_id``\ ) and B (reference paths); removed the ``[AM]``
       marker system (the whole doc is the AgroMarin standard).
   * - 3.0
     - 2026-04-20
     - Prior canonical revision (suffix XML IDs, 16-section model layout, Sphinx
       docstrings, unified 13-tag commit catalog).

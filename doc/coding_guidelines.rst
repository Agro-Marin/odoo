.. _coding_guidelines:

=============================
AgroMarin Coding Guidelines
=============================

:Version: 3.0
:Date: 2026-04-20
:Language: English
:Base: `Odoo 19.0 Coding Guidelines <https://www.odoo.com/documentation/19.0/contributing/development/coding_guidelines.html>`_ + `OCA CONTRIBUTING.rst <https://github.com/OCA/odoo-community.org/blob/master/website/Contribution/CONTRIBUTING.rst>`_

AgroMarin-specific rules are marked with **[AM]**. For Odoo 17-19 API
changes, see ``odoo-19-development-context.md`` in the knowledge repository.

.. contents::
   :local:
   :depth: 2

Introduction
------------

Standardizing development practices in Odoo is essential to guarantee the quality,
maintainability, and scalability of our solutions. The lack of uniformity in module
structure, code conventions, and documentation generates inconsistencies that hinder
collaboration and slow down development. This guide establishes a single set of clear,
consistent norms aligned with OCA community standards and adapted to AgroMarin's
specific requirements.

All conventions marked **[AM]** extend or override the Odoo/OCA default. Everything
else follows the official guidelines linked above.

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

   * - Repo
     - Rules apply
   * - ``addons/agromarin-addons``
     - ✅ Full
   * - ``core``
     - ✅ Full (fork customizations)
   * - ``enterprise``
     - ✅ Full (fork customizations)
   * - ``addons/design-themes``
     - ✅ Full
   * - Any other repo not listed
     - ❌ Out of scope


The [AM] marker
^^^^^^^^^^^^^^^

Rules marked **[AM]** are AgroMarin-specific and **extend or override** the
Odoo/OCA default. Everything not marked **[AM]** follows the upstream guideline
linked at the top of each section. When you see **[AM]**\ , assume it contradicts
what training data suggests — trust the marker.

Change protocol
^^^^^^^^^^^^^^^

* Edits to this file go through PR review on the ``core`` repository
  (target branch ``19.0-marin``\ ), using the commit format defined in §7.
  TI (Oficial Sistemas tier or higher) reviews; the Líder Sistemas has
  final authority on merges.
* When a rule is changed here, the responsible reviewer must also update
  any pointers or summaries in ``core/CLAUDE.md``\ ,
  ``enterprise/CLAUDE.md``\ , ``addons/agromarin-addons/CLAUDE.md``\ ,
  ``knowledge/CLAUDE.md``\ , and per-module ``CLAUDE.md`` files that
  reference the changed rule.
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
   ├── report/                     # QWeb report templates
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
   └── wizards/                    # TransientModel files [AM: includes res.config.settings]

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

1.3 File Naming [AM]
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
   * - Menus [AM]
     - ``ir_ui_menu_views.xml``
     - Single file, all menuitems
   * - Access rights
     - ``ir.model.access.csv``
     - Always CSV
   * - Groups [AM]
     - ``res_groups_security.xml``
     - Group definitions
   * - Record rules [AM]
     - ``ir_rule_security.xml``
     - All ``ir.rule`` records in one file
   * - Wizards
     - ``wizards/{model_name}.py`` + ``_views.xml``
     - Includes ``res.config.settings`` [AM]


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
       ir_ui_menu_views.xml             # all menuitems [AM]
     wizards/
       res_config_settings.py           # settings (TransientModel) [AM]
       res_config_settings_views.xml
     security/
       ir.model.access.csv
       res_groups_security.xml          # groups [AM]
       ir_rule_security.xml             # record rules (ir.rule) [AM]

----

2. Python
---------

Base: `Odoo Coding Guidelines -- Python <https://www.odoo.com/documentation/19.0/contributing/development/coding_guidelines.html#python>`_

2.1 PEP 8 and Imports
^^^^^^^^^^^^^^^^^^^^^


* PEP 8 compliance, **line length = 88** (enforced by ``ruff format``\ )
* Break long lines at logical points; the formatter handles the mechanics
* Import order: stdlib, third-party, odoo, odoo.addons (alphabetical within each group — enforced by isort via ``ruff``\ )
* **Double quotes everywhere** [AM]: strings, field attributes, docstrings (enforced by ``ruff format`` with ``quote-style = "double"``\ )

.. code-block:: python

   import logging

   from odoo import api, fields, models
   from odoo.exceptions import UserError, ValidationError
   from odoo.fields import Domain
   from odoo.tools import LazyTranslate

   from odoo.addons.sale.models.sale_order import SaleOrder

2.2 Model Class Organization [AM]
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
     - ``# CRUD METHODS``
     - ``create``\ , ``write``\ , ``unlink``\ , ``copy``\ , ``copy_data``
   * - 5
     - ``# COMPUTE METHODS``
     - ``_compute_*`` methods
   * - 6
     - ``# SEARCH METHODS``
     - ``_search_*`` methods
   * - 7
     - ``# INVERSE METHODS``
     - ``_inverse_*`` methods
   * - 8
     - ``# ONCHANGE METHODS``
     - ``_onchange_*`` methods
   * - 9
     - ``# CONSTRAINT METHODS``
     - ``_check_*``\ , ``_validate_*`` methods
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


**Rules**\ : Not all sections required. ALL CAPS mandatory. Domain-specific sections (12)
go after ACTION METHODS.

**Method ordering within COMPUTE and ONCHANGE sections:**


#. **Rule 1 (base)**\ : Ascending by ``@api.depends`` dependency count (0 deps first, N deps last)
#. **Rule 2 (tiebreaker)**\ : Context field relevance: ``company_id`` > ``partner_id`` > ``state`` > ``currency_id`` > ``user_id`` > other
#. **Rule 3 (override)**\ : Semantic dependency chains preserved — methods consuming output of earlier computes go AFTER, regardless of count

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

**Ordering: semantic/functional grouping** (NOT by type) [AM].

Every field must belong to a named ``# block``. No orphan fields allowed. Each model
defines its own blocks based on its domain. The ``# Noun block`` or ``# Noun`` comment
pattern is mandatory.

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

**Naming patterns** [AM]:

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
     - ``count_`` prefix
     - ``picking_count`` -> ``count_picking_ids``
   * - Quantities
     - ``qty_`` prefix
     - ``delivered_qty`` -> ``qty_transferred``
   * - Booleans
     - ``is_`` prefix
     - ``order_sent`` -> ``is_sent``
   * - State
     - ``_state`` suffix
     - ``invoice_status`` -> ``invoice_state``


Default functions: use ``lambda self:`` (allows inheritance).

.. code-block:: python

   user_id = fields.Many2one("res.users", default=lambda self: self.env.user)

2.4 Method Naming [AM]
^^^^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - Pattern
     - Convention
     - Example
   * - Button actions
     - ``action_`` (NEVER ``button_``\ )
     - ``button_confirm`` -> ``action_confirm``
   * - View openers
     - ``action_view_`` (NEVER ``action_open_``\ )
     - ``action_open_invoices`` -> ``action_view_invoices``
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
     - ``_name_search`` -> ``_search_display_name``
   * - Default
     - ``_default_``
     - ``get_default_warehouse`` -> ``_default_warehouse_id``


2.5 Docstrings
^^^^^^^^^^^^^^

Mandatory on **models** and **complex methods**. Simple getters/setters may omit.

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

2.6 ORM Best Practices
^^^^^^^^^^^^^^^^^^^^^^

These rules apply to every model in ``$ACTIVE_REPOS``.

**Always call** ``super()`` in ``create``\ , ``write``\ , ``unlink``\ , ``copy``\ , ``default_get``\ ,
and ``_compute_display_name``. Overriding without delegation is a regression vector.

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

**Propagate context with** ``with_context`` — ``self.env.context`` is a frozen dict:

.. code-block:: python

   order.with_context(force_company=company.id).action_confirm()

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

**Computed-field dependency rule** [AM]: every sub-field accessed in a compute
method body must appear in ``@api.depends``. If the method reads
``record.partner_id.country_id``\ , then ``"partner_id.country_id"`` must be listed —
``"partner_id"`` alone is insufficient and causes silent stale data.

**Exception — initialization-only computes**\ : when a ``store=True, readonly=False``
compute is designed to set an initial default (inheriting ``lang`` from parent on
reparenting), a coarser dependency like ``"parent_id"`` is intentional to avoid
overwriting user edits. Document the choice in a comment.

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


**\** ``ormcache``\ : use ``@ormcache`` for read-heavy, rarely-changing data (metadata,
view parsing, ACL lookups). Cached methods **must not return recordsets** — the
cursor used to build the recordset is closed on subsequent calls and will raise
``InterfaceError``. Return plain Python types.

**Indexing**\ : add ``index=True`` on fields used in ``search()`` domains, ``ORDER BY``\ ,
or ``GROUP BY``. Use ``models.Index()`` for composite/partial/BRIN/expression indexes.
Partial indexes are preferred when queries filter on a specific state.

**Locking**\ : use ``FOR UPDATE NOWAIT`` for critical sections, ``FOR UPDATE SKIP LOCKED``
for job queues. Always handle ``OperationalError`` when using ``NOWAIT``. Minimize
lock duration: lock → operate → commit as fast as possible.

**Raw SQL review rule** [AM]: any raw ``cr.execute()`` added to a PR must include
``EXPLAIN ANALYZE`` output in the PR description, demonstrating index use. This
is a review gate.

**Cron batch processing** [AM]:

.. code-block:: python

   from itertools import batched

   def _cron_process_orders(self):
       orders = self.env["sale.order"].search([("state", "=", "pending")])
       commit_progress = self.env["ir.cron"]._commit_progress
       for batch_ids in batched(orders.ids, 100):
           batch = orders.browse(batch_ids)
           batch._process()
           remaining = commit_progress(
               processed=len(batch),
               remaining=len(orders) - len(batch),
           )
           if remaining <= 0:
               break

Do **not** call ``cr.commit()`` directly. ``_commit_progress`` handles the commit
and returns remaining execution time. ``split_every`` is deprecated since 19.0 —
use ``itertools.batched``.

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


**All user-facing messages go through** ``self.env._()`` (10x faster than ``_()``\ ):

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

**Fail-closed discipline** [AM]: exception handlers in state-mutation code must
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

``except Exception`` is flagged by the linter (\ ``BLE001``\ ). Use only for
catch-log-reraise or integration adapters. In financial or state-mutation code,
log-and-continue is a violation — each failure must roll back or transition to
an explicit error state.

**Exception chaining**\ : always use ``raise X from Y`` so the original traceback
is preserved. New code must chain; legacy code is allowed to omit (\ ``B904`` is
suppressed) but should be upgraded when touched.

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

``datetime.utcnow()`` is banned (DTZ003 via ``banned-api``\ ). Use ``datetime.now(UTC)``\ :

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
     - ``T20`` (allowed in tests)
   * - No ``breakpoint()`` / ``pdb.set_trace()``
     - ``T10``
   * - No commented-out code
     - ``ERA001`` (warn — delete, rely on git history)
   * - Prefer ``pathlib.Path`` over ``os.path``
     - ``PTH``
   * - No mutable default arguments
     - — (review rule; use ``None`` sentinel)


**Cyclomatic complexity** is capped at ``max-complexity = 20`` (\ ``C90``\ ). Method
bodies above ~40 lines should be split — the linter cannot measure lines, so
this is a review rule.

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

Optional but encouraged for public API, framework-level code, and complex return
types. Python 3.14's PEP 649 deferred annotations means forward references work
without string-quoting.

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

Apply ``@typing.override`` (Python 3.12+) to ``create``\ , ``write``\ , ``unlink``\ ,
``_compute_*``\ , and any overridden parent method. This catches silent breakage
when the parent is renamed.

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

3.2 XML IDs and Naming [AM]
^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Suffix style** — the model/entity comes first, the role comes last. This
matches the Odoo 19 core convention and keeps related records alphabetically
grouped in the manifest and in search:

.. list-table::
   :header-rows: 1

   * - Type
     - Pattern [AM]
     - Example
   * - Views
     - ``{model}_view_{type}``
     - ``sale_order_view_form``
   * - Actions
     - ``{model}_action``
     - ``sale_order_action``
   * - Menus
     - ``{model}_menu``
     - ``sale_order_menu``
   * - Groups
     - ``{module}_group_{name}``
     - ``sale_group_manager``
   * - Record rules
     - ``{model}_rule_{group}``
     - ``sale_order_rule_user``
   * - Reports
     - ``{name}_report_action``
     - ``sale_order_report_action``
   * - Report templates
     - ``{name}_report_document``
     - ``sale_order_report_document``
   * - Inherited views
     - ``{model}_view_{type}_inherit_{context}``
     - ``sale_order_view_form_inherit_custom``
   * - Server actions
     - ``{model}_action_server_{action}``
     - ``sale_order_action_server_cancel``
   * - Email templates
     - ``{model}_mail_template_{purpose}``
     - ``sale_order_mail_template_confirmation``


..

   **Migration note**\ : the prior AgroMarin convention used the inverted prefix
   (\ ``view_sale_order_form``\ ). All new XML IDs follow the suffix style; existing
   records are migrated opportunistically when their surrounding file is edited.
   See Appendix C for the retired pattern.


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

3.4 Wizard Forms [AM]
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
* ``res.config.settings`` goes in ``wizards/`` [AM]

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


* ``report_name`` and ``report_file`` both = ``module.template_id``
* ``binding_model_id`` for Print menu binding
* `binding_type`: `"report"` (Print) or `"action"` (Action); `binding_view_types`: ``"list,form"`` (default)
* ``t-lang=`` at ``t-call`` level for localization

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

   <!-- wizards/res_config_settings_views.xml [AM] -->
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
* File: ``wizards/res_config_settings_views.xml`` [AM]

3.9 Menu Files [AM]
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


* Source files in ``static/src/js/``\ , templates in ``static/src/xml/``
* ES6 imports, no ``require()``

.. code-block:: javascript

   import { Component } from "@odoo/owl";
   import { registry } from "@web/core/registry";
   import { _t } from "@web/core/l10n/translation";


* ``/** @odoo-module **/`` header is optional (18.0+)

4.2 Naming
^^^^^^^^^^


* **Method names must match Python exactly** [AM]: if Python uses ``action_view_invoices``\ , JS must use the same name
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
   * - **No `/** @odoo-module **/` header**
     - Auto-handled since 18.0 — do not add it
   * - **Always ``super.setup()`` first**
     - When patching, call ``super.setup()`` before anything else
   * - **Use ``useState`` for reactive state**
     - Plain object assignments do not trigger re-render
   * - **Verify import paths before using**
     - Odoo moves components between releases — assume training data is stale
   * - **POS customizations prefer DOM manipulation**
     - Template inheritance in POS is fragile; patch + ``onMounted`` is more stable


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
   ├─ Extend existing component?     → patch(Component.prototype, { ... })
   │   └─ POS component?             → Prefer DOM manipulation in onMounted
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

Full OWL reference (hooks, stores, lifecycle) lives in ``reference/owl/``.

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
* Declare in ``__manifest__.py`` under ``assets``\ :

.. code-block:: python

   "assets": {"web.assets_backend": ["module_name/static/src/scss/style.scss"]}

----

6. Tests
--------

Base: `Odoo Testing Reference <https://www.odoo.com/documentation/19.0/developer/reference/backend/testing.html>`_ | `OCA Guidelines -- Tests <https://github.com/OCA/odoo-community.org/blob/master/website/Contribution/CONTRIBUTING.rst>`_

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
* **Use fixed dates** — ``datetime.now()`` creates flaky tests.
* **Mock external services** — tests must run offline.
* **Test with minimal permissions** — create a user with only the group being
  tested to catch access rule issues early.
* **Never call** ``cr.commit()`` **in tests**. All test data must be created
  within the test transaction and automatically rolled back. A committed
  transaction permanently pollutes the test database and causes cascading
  failures.

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
with mail/tracking disabled, independent users and companies, and convenience
helpers:

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
* Pre-created ``cls.company``\ , ``cls.currency``\ , ``cls.partner``\ , ``cls.group_*``.
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

The following rules are **suppressed** for test files (``**/tests/**``\ ) via
per-file-ignores in ``ruff.toml``\ :

* ``print()`` is allowed (\ ``T201``\ ).
* Broad ``assertRaises`` context managers are allowed (\ ``B017``\ ).
* ``global`` statements for test fixtures are allowed (\ ``PLW0603``\ ).
* Literal membership tests (\ ``x in [1, 2, 3]``\ ) prefer readability over
  performance (\ ``PLR6201``\ ).
* First-element access via ``list(x)[0]`` instead of ``next(iter(x))`` is
  allowed (\ ``RUF015``\ ).

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

Use the **Arrange / Act / Assert** pattern. Separate sections with blank lines:

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
* For slow or integration tests: ``@tagged("-standard", "heavy")``.

6.11 Coverage [AM]
^^^^^^^^^^^^^^^^^^

* Target **>80%** on custom modules.
* Test edge cases, constraints, and validations.
* Every ``action_*`` method should have at least one test.
* ``Form`` simulator (\ ``odoo.tests.common.Form``\ ) for onchange testing without HTTP.
* ``@users("demo")`` decorator for multi-user permission testing.

----

7. Git
------

Base: `OCA CONTRIBUTING.rst -- Git <https://github.com/OCA/odoo-community.org/blob/master/website/Contribution/CONTRIBUTING.rst>`_

7.1 Commit Messages
^^^^^^^^^^^^^^^^^^^

First line: ``[TAG] module: description`` (max 80 chars)

**Unified tag catalog** (13 tags — no other tags allowed):

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

Body structure (mandatory) [AM]:

.. code-block::

   [TAG] module: short summary (max 80 chars)

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

7.2 Branch Naming [AM]
^^^^^^^^^^^^^^^^^^^^^^

Format: ``<odoo_version>-t<task_id>-<github_username>``

.. code-block::

   19.0-t17352-suniagajose

7.3 Task ID Requirement [AM]
^^^^^^^^^^^^^^^^^^^^^^^^^^^^


* Every commit MUST reference an Odoo task ID
* Every branch MUST include the task ID
* Traceability: code change -> task -> business requirement

7.4 Pull Requests [AM]
^^^^^^^^^^^^^^^^^^^^^^

All code changes in ``$ACTIVE_REPOS`` (except the ``knowledge/`` repo, which works
directly on ``main``\ ) go through a pull request.

**Title**\ : ``< 70 characters``. No tag prefix — the PR title describes the
change, the commits inside carry the ``[TAG]`` prefix.

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
* No force push to shared branches (\ ``main``\ , ``19.0``\ , ``19.0-marin``\ , ``19.0-dev``\ )

----

8. Translations
---------------

Base: `Odoo Translations Reference <https://www.odoo.com/documentation/19.0/developer/reference/backend/module.html#translations>`_

8.1 Python
^^^^^^^^^^

Preferred: ``self.env._()`` (10x faster than ``_()``\ , resolves user language automatically).

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

----

9. Code Review Checklist
------------------------

Use this 44-item checklist for every PR review. The reviewer confirms each
applicable item before approving. Non-applicable items (e.g. no raw SQL in the
diff) may be skipped with a note.

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
#. CRUD overrides (\ ``create``\ , ``write``\ , ``unlink``\ , ``copy``\ ) call ``super()``
#. ``@api.depends`` lists every sub-field accessed in the method body
#. ``fields.Monetary`` has a matching currency field on the same model
#. Error types match intent: ``UserError`` for business, ``ValidationError`` for constraints, ``MissingError`` for deleted records
#. ``.exists()`` is called when records may have been deleted by another transaction
#. No mutable default arguments — uses the ``None`` sentinel pattern
#. Method overrides use the ``@typing.override`` decorator

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

Linter-enforced — verify ``ruff check`` passes (10)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^


#. No ``print()`` or debugger statements in production code (\ ``T10`` / ``T20``\ )
#. No commented-out code blocks (\ ``ERA001``\ )
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

10.2 ``sudo()`` Discipline
^^^^^^^^^^^^^^^^^^^^^^^^^^

* Whitelist which fields are allowed when writing user-submitted payloads.
* Minimize scope — apply ``sudo()`` to the smallest recordset and fewest
  operations.
* Every ``sudo()`` call should be flagged for review.

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

10.5 Related Fields and ACLs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Related fields are computed in ``sudo`` mode, bypassing access control. A
related field pointing to a sensitive model (\ ``ir.attachment``\ ,
``hr.payslip``\ ) can leak data. Prefer ``fields.Binary`` or controlled
``search()`` calls when accessing protected records.

10.6 Controller Security
^^^^^^^^^^^^^^^^^^^^^^^^

* ``auth="public"`` runs as the Public user, including unauthenticated visitors.
* ``auth="none"`` means no database access — mainly for framework use.
* Validate and sanitize all controller parameters.
* Use ``Markup()`` for intentional HTML output; escape user-generated content.

10.7 Fail-Closed Error Handling
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Exception handlers in state-mutation code **must** leave the system in a
consistent state. Use ``cr.savepoint()`` so partial operations roll back on
failure:

.. code-block:: python

   for order in orders:
       try:
           with self.env.cr.savepoint():
               order._process_payment()
               order.action_confirm()
       except UserError:
           order.state = "error"
           _logger.error("Failed to process order %s", order.name, exc_info=True)

``except Exception`` is flagged by the linter (\ ``BLE001``\ ). Use it only when
genuinely necessary (e.g. catch-log-reraise patterns, integration adapters).
Always re-raise or transition to an explicit error state — never silently
swallow exceptions.

Broad ``except Exception`` blocks that log-and-continue are a violation in
financial or state-mutation code. Each failure must either roll back its
changes or explicitly transition to an error state.

10.8 Error Information Disclosure
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Never expose raw exceptions to users.** Internal error details (SQL
fragments, Python tracebacks, file paths) aid attackers:

.. code-block:: python

   # Wrong — leaks internals
   except Exception as e:
       raise UserError(str(e))

   # Correct — generic user message, full details in server log
   except Exception:
       _logger.error("Payment processing failed", exc_info=True)
       raise UserError(_("Payment could not be processed. Contact support."))

10.9 Configuration and Secrets
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

* **No hardcoded URLs, credentials, or service endpoints** in Python code. Use
  ``ir.config_parameter``\ , environment variables, or ``odoo.conf`` for all
  external configuration.
* **External dependencies** must be declared in ``__manifest__.py``
  ``external_dependencies`` AND in a ``requirements.txt`` at the addon root.
  Pin minimum versions.

10.10 Deployment Checklist
^^^^^^^^^^^^^^^^^^^^^^^^^^

Before production deployment, verify:

* ``--dev`` mode is disabled.
* ``list_db = False`` in configuration.
* Default admin password is changed.
* ``proxy_mode = True`` if behind a reverse proxy.
* ``dbfilter`` is set to restrict database access.
* ``server_wide_modules`` is minimal.
* Python dependencies are pinned with hashes. Run ``pip-audit`` in CI.

----

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

   # Correct — single SQL query
   [total] = self.env["account.move.line"]._read_group(
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
       for batch_ids in batched(orders.ids, 100):
           batch = orders.browse(batch_ids)
           batch._process()
           remaining = commit_progress(
               processed=len(batch),
               remaining=len(orders) - len(batch),
           )
           if remaining <= 0:
               break  # time limit reached

* Process in batches (100–1000 records) using ``itertools.batched()`` to limit
  memory and lock duration. (\ ``split_every`` is deprecated since 19.0.)
* Use ``self.env["ir.cron"]._commit_progress(processed, remaining)`` — it
  calls ``cr.commit()`` internally and returns remaining execution time
  (seconds).
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

The version in the directory name must match the ``version`` in
``__manifest__.py`` that introduces the breaking change.

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

12.3 When Required
^^^^^^^^^^^^^^^^^^

**When required:** adding/removing required fields on existing models,
changing field types, renaming models or fields, complex data transformations.

**Not required:** adding optional fields, new module installations, view-only
changes, adding/removing ``Many2many`` relationships.

----

Appendix A — Fork-specific field renames
----------------------------------------

These fields are renamed on ``project.task`` in the AgroMarin fork. Using the
vanilla names causes Fault 500 on every MCP call. Apply these regardless of
what training data suggests:

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
     - ``triage_id``
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


* ``reference/odoo/odoo-19-development-context.md`` — Odoo 17→19 API changes
* ``reference/dev/error-catalog.md`` — Known PATH / CONFIG / SERVICE / POSTGRES errors and fixes
* ``reference/owl/`` — Full OWL framework reference (hooks, stores, lifecycle)
* ``reference/python-pg/`` — Python 3.14 and PostgreSQL 18 / psycopg 3 patterns
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

C.1 XML IDs — inverted prefix style
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Retired**\ : ``view_sale_order_form``\ , ``action_sale_order``\ , ``menu_sale_order``.

**Replaced by**\ : the suffix style in §3.2 (\ ``sale_order_view_form``\ ,
``sale_order_action``\ , ``sale_order_menu``\ ).

**Why**\ : the suffix style matches Odoo 19 core, keeps related records
alphabetically grouped, and reduces diff noise when renaming models.

**Migration**\ : existing records keep the old ID until the surrounding file is
edited. When editing a file that defines XML records, migrate every ID in that
file in the same commit (\ ``[REF] module: rename XML IDs to suffix style``\ ).

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
``# COMPUTE METHODS``\ , ``# ONCHANGE METHODS``\ , ...) with the method-ordering rules
inside each section (dependency count, context relevance, semantic chain).

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
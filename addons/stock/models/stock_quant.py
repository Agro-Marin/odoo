import heapq
import logging
import typing
from ast import literal_eval
from collections import defaultdict

from markupsafe import escape
from psycopg import Error

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools import SQL, float_compare, float_is_zero

_logger = logging.getLogger(__name__)


class _LeastPackagesPriorityQueue:
    """Min-heap frontier for the least_packages removal-strategy A* search.

    Module-level so it is defined once (not rebuilt per
    _run_least_packages_removal_strategy_astar() call) and is unit-testable.

    Entries are ``(priority, insertion_index, item)``. The monotonic
    ``insertion_index`` breaks priority ties by FIFO insertion order so the heap
    never compares the ``item`` nodes: a node's ``taken_packages`` mixes ``None``
    and ``int`` package keys, and ``None < int`` raises ``TypeError`` on Python 3.
    """

    def __init__(self):
        self.elements = []
        self._counter = 0

    def empty(self) -> bool:
        return not self.elements

    def put(self, item, priority):
        heapq.heappush(self.elements, (priority, self._counter, item))
        self._counter += 1

    def get(self):
        return heapq.heappop(self.elements)[2]


class _LeastPackagesNode(typing.NamedTuple):
    """A node of the least_packages A* search."""

    count_remaining: float
    taken_packages: tuple
    next_index: int


def _least_packages_search(qty_by_package, qty):
    """A* search for the fewest packages (each unpackaged unit counts as one)
    whose available quantity covers ``qty``.

    Pure and side-effect free, so it is unit-testable in isolation of the ORM.

    :param qty_by_package: list of ``(key, available_qty)`` where ``key`` is a
        ``stock.package`` id or ``None`` for a virtual single unit. Must be grouped
        by ``available_qty`` (singles last, as
        ``_run_least_packages_removal_strategy_astar`` builds it): the loop below
        dedups adjacent equal amounts, so the grouping is what makes "one branch per
        distinct amount" correct. Order is not relied on for heap safety --
        ``_LeastPackagesPriorityQueue``'s insertion-index tie-breaker avoids
        comparing nodes' ``None``/``int`` package keys.
    :param qty: quantity to cover.
    :return: the winning node's ``taken_packages`` tuple -- an exact cover if one
        exists, else the best partial/over cover found.
    """
    size = len(qty_by_package)

    def heuristic(node):
        if node.next_index < size:
            return (
                len(node.taken_packages)
                + node.count_remaining / qty_by_package[node.next_index][1]
            )
        return len(node.taken_packages)

    frontier = _LeastPackagesPriorityQueue()
    frontier.put(_LeastPackagesNode(qty, (), 0), 0)
    best_leaf = _LeastPackagesNode(qty, (), 0)

    while not frontier.empty():
        current = frontier.get()

        if current.count_remaining <= 0:
            return current.taken_packages

        last_count = None
        i = current.next_index
        while i < size:
            pkg = qty_by_package[i]
            i += 1
            if pkg[1] == last_count:
                continue
            last_count = pkg[1]

            count = current.count_remaining - pkg[1]
            taken = current.taken_packages + (pkg,)
            node = _LeastPackagesNode(count, taken, i)

            if count < 0:
                if (
                    best_leaf.count_remaining > 0
                    or len(node.taken_packages) < len(best_leaf.taken_packages)
                    or (
                        len(node.taken_packages) == len(best_leaf.taken_packages)
                        and node.count_remaining > best_leaf.count_remaining
                    )
                ):
                    best_leaf = node
                continue

            if i >= size and count != 0:
                if node.count_remaining < best_leaf.count_remaining:
                    best_leaf = node
                continue

            frontier.put(node, heuristic(node))

    return best_leaf.taken_packages


class _ReservationLedger:
    """Reservations decided during one ``_action_assign`` run but not yet written.

    ``_action_assign`` used to persist each move's reservation before it looked at the
    next move, so "how much is left" was a question the database answered. Batching
    those writes removes that: between the decision and the flush the database still
    shows the stock as free, and every later move in the same run would claim it
    again. This ledger is what carries the information instead -- a take is recorded
    the moment it is decided, and every availability question in the same run
    subtracts it.

    It also holds the move line values, and that pairing is the point: a take
    recorded without its line over-reserves, and a line kept without its take
    double-reserves. Keeping both on one object makes the two impossible to
    separate by accident, and lets the whole batch be created in a single call.

    Pure and DB-free, like :func:`_distribute_reservation` and
    :func:`_least_packages_search`: it holds numbers and opaque values, so the
    arithmetic that decides who gets the last unit is unit-testable without an ORM.
    """

    __slots__ = ("_pending", "move_line_vals")

    def __init__(self, move_line_vals=None):
        self._pending = defaultdict(float)
        self.move_line_vals = move_line_vals if move_line_vals is not None else []

    def pending(self, quant):
        """Quantity of `quant` already claimed in this run but not yet written."""
        return self._pending.get(quant.id, 0.0)

    def take(self, quant, quantity):
        """Record a decided-but-unwritten claim on `quant`."""
        self._pending[quant.id] += quantity

    def total_pending(self):
        """Everything claimed and not yet written -- for logging and assertions."""
        return sum(self._pending.values())


class _ReservationCandidate(typing.NamedTuple):
    """One candidate row offered to :func:`_distribute_reservation`."""

    handle: object
    on_hand: float
    reserved: float
    key: object


def _distribute_reservation(candidates, quantity, precision_digits):
    """Distribute a signed ``quantity`` across pre-ordered reservation ``candidates``.

    Pure and DB-free (like :func:`_least_packages_search`): operates on plain numbers
    and opaque ``handle`` values only, so this allocation arithmetic -- the trickiest
    in the model -- is unit-testable with hand-built inputs.

    :param candidates: list of :class:`_ReservationCandidate` already ordered by the
        removal strategy. ``handle`` is echoed back verbatim; ``key`` groups
        interchangeable candidates so stock already over-reserved into negative
        available is absorbed first, before the rest of that group over-reserves too.
    :param quantity: quantity to reserve, in the candidates' UoM. **Strictly
        positive**; a non-positive value returns no allocation. Reserving never takes
        more than is left, so the run converges to zero without crossing it.

        This used to accept a signed quantity and carry a second branch that
        released. Nothing ever called it: releases go through
        ``_update_reserved_quantity`` -> ``_update_available_quantity``, which locks a
        row and clamps there, and ``_get_reserve_quantity`` -- the only caller --
        returns early on ``quantity <= 0``. The branch was also wrong, which is how a
        second release algorithm nothing exercised stays wrong: against a candidate
        holding a *negative* ``reserved`` (a state ``_update_available_quantity``
        deliberately persists) ``min(cand.reserved, abs(quantity))`` went negative and
        it emitted a **positive** delta while releasing, then drove ``quantity``
        further from zero. Deleted rather than repaired, so there is one release path
        instead of two that disagree.

        ``quantity`` is the *only* bound on the run, and that is deliberate. Two
        clamps already make it sufficient: the caller caps it to real availability
        (``_get_reserve_quantity`` -> ``_sum_available_quantity``), and each
        allocation below is capped by that candidate's own post-absorption slack.
        A second "running budget" argument used to be threaded in as well, sized as
        ``sum(positive on_hand) - sum(all reserved)``. That total is *not* the
        availability ``quantity`` was capped to -- it nets a negative-available
        quant against unrelated keys instead of dropping it -- so on a set holding
        one over-reserved quant it came out smaller than the true availability and
        broke the loop early, silently reserving less than the caller had already
        established was there.
    :param precision_digits: 'Product Unit' decimal precision; every comparison rounds
        to it, matching ``uom.compare`` / ``uom.is_zero``.
    :return: list of ``(handle, amount)`` pairs with ``amount`` positive.
    """
    reserved = []
    if float_compare(quantity, 0, precision_digits=precision_digits) <= 0:
        return reserved

    negative_available = defaultdict(float)
    for cand in candidates:
        slack = cand.on_hand - cand.reserved
        if float_compare(slack, 0, precision_digits=precision_digits) < 0:
            negative_available[cand.key] += slack

    for cand in candidates:
        max_on_cand = cand.on_hand - cand.reserved
        if float_compare(max_on_cand, 0, precision_digits=precision_digits) <= 0:
            continue
        negative = negative_available[cand.key]
        if negative:
            to_absorb = min(abs(negative), max_on_cand)
            negative_available[cand.key] += to_absorb
            max_on_cand -= to_absorb
        if float_compare(max_on_cand, 0, precision_digits=precision_digits) <= 0:
            continue
        max_on_cand = min(max_on_cand, quantity)
        reserved.append((cand.handle, max_on_cand))
        quantity -= max_on_cand

        if float_is_zero(quantity, precision_digits=precision_digits):
            break
    return reserved


class _QuantsCache:
    """Keyed quant cache for the reservation gather path, with coverage tracking.

    It behaves like the ``defaultdict(recordset)`` it replaced for the keyed reads
    and writes that ``_gather`` and quant ``create`` perform (``cache[key]`` returns
    an empty recordset on a miss; ``cache[key] |= quant`` accumulates), but it also
    records which ``(product, location)`` subtree the build scan covered.

    That lets a strict ``_gather`` tell a *genuine* miss -- a product/location the
    scan never looked at, e.g. because the caller seeded an incomplete cache -- from a
    *covered-but-empty* result. On a genuine miss it must fall back to a DB search;
    without this, a miss silently returned an empty recordset, which reads as "no
    stock" and causes silent under-reservation.

    A build scan may also be *lot-filtered* (``_action_done`` seeds only the lots it is
    about to consume, plus untracked stock). Such a cache is authoritative only for
    those lots: a gather for any other lot must fall back to the search, since that
    lot's quants were never scanned and a miss would wrongly read as "no stock". Pass
    ``lot_scope`` to record the authoritative lot set (``None`` = unfiltered).
    """

    __slots__ = ("_data", "_empty", "_location_paths", "_lot_scope", "_product_ids")

    def __init__(self, empty, product_ids=(), location_paths=(), lot_scope=None):
        self._data = {}
        self._empty = empty
        self._product_ids = frozenset(product_ids)
        self._location_paths = tuple(p for p in location_paths if p)
        self._lot_scope = None if lot_scope is None else frozenset(lot_scope)

    def __getitem__(self, key):
        return self._data.get(key, self._empty)

    def __setitem__(self, key, value):
        self._data[key] = value

    def covers(self, product_id, location_id, lot_id=None):
        """Whether the build scan fully covered this product/location (and lot), so a
        missing key means genuinely no quant rather than an un-scanned pair."""
        if product_id.id not in self._product_ids:
            return False
        path = location_id.parent_path or ""
        if not any(path.startswith(root) for root in self._location_paths):
            return False
        return self._lot_scope is None or not lot_id or lot_id.id in self._lot_scope


class StockQuant(models.Model):
    _name = "stock.quant"
    _description = "Quants"
    _rec_name = "product_id"
    _rec_names_search = ["location_id", "lot_id", "package_id", "owner_id"]

    location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Location",
        required=True,
        bypass_search_access=True,
        domain=lambda self: self._domain_location_id(),
        ondelete="restrict",
        index=True,
    )
    company_id = fields.Many2one(
        related="location_id.company_id",
        string="Company",
        store=True,
        readonly=True,
    )
    warehouse_id = fields.Many2one(
        related="location_id.warehouse_id",
        comodel_name="stock.warehouse",
    )
    storage_category_id = fields.Many2one(
        related="location_id.storage_category_id",
    )
    cyclic_inventory_frequency = fields.Integer(
        related="location_id.cyclic_inventory_frequency"
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
        required=True,
        check_company=True,
        domain=lambda self: self._domain_product_id(),
        ondelete="restrict",
    )
    product_tmpl_id = fields.Many2one(
        related="product_id.product_tmpl_id",
        comodel_name="product.template",
        string="Product Template",
    )
    is_favorite = fields.Boolean(
        related="product_tmpl_id.is_favorite",
    )
    product_uom_id = fields.Many2one(
        related="product_id.uom_id",
        comodel_name="uom.uom",
        string="Unit",
        readonly=True,
    )
    tracking = fields.Selection(
        related="product_id.tracking",
        readonly=True,
    )
    product_categ_id = fields.Many2one(
        related="product_tmpl_id.categ_id",
    )
    lot_id = fields.Many2one(
        comodel_name="stock.lot",
        string="Lot/Serial Number",
        check_company=True,
        domain=lambda self: self._domain_lot_id(),
        ondelete="restrict",
        index=True,
    )
    lot_properties = fields.Properties(
        related="lot_id.lot_properties",
        definition="product_id.lot_properties_definition",
        readonly=True,
    )
    sn_duplicated = fields.Boolean(
        string="Duplicated Serial Number",
        compute="_compute_sn_duplicated",
        help="If the same SN is in another Quant",
    )
    package_id = fields.Many2one(
        comodel_name="stock.package",
        string="Package",
        check_company=True,
        domain="['|', ('location_id', '=', location_id), '&', ('location_id', '=', False), ('quant_ids', '=', False)]",
        ondelete="restrict",
        index=True,
        help="The package containing this quant",
    )
    owner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Owner",
        check_company=True,
        index="btree_not_null",
        help="This is the owner of the quant",
    )
    quantity = fields.Float(
        string="Quantity",
        digits="Product Unit",
        readonly=True,
        help="Quantity of products in this quant, in the default unit of measure of the product",
    )
    reserved_quantity = fields.Float(
        string="Reserved Quantity",
        digits="Product Unit",
        required=True,
        default=0.0,
        readonly=True,
        help="Quantity of reserved products in this quant, in the default unit of measure of the product",
    )
    available_quantity = fields.Float(
        string="Available Quantity",
        digits="Product Unit",
        compute="_compute_available_quantity",
        help="On hand quantity which hasn't been reserved on a transfer, in the default unit of measure of the product",
    )
    in_date = fields.Datetime(
        string="Incoming Date",
        required=True,
        default=fields.Datetime.now,
        readonly=True,
    )
    on_hand = fields.Boolean(
        string="On Hand",
        store=False,
        search="_search_on_hand",
    )

    inventory_quantity = fields.Float(
        string="Counted",
        digits="Product Unit",
        help="The product's counted quantity.",
    )
    inventory_quantity_auto_apply = fields.Float(
        string="Inventoried Quantity",
        digits="Product Unit",
        compute="_compute_inventory_quantity_auto_apply",
        inverse="_inverse_inventory_quantity",
        groups="stock.group_stock_manager",
    )
    inventory_diff_quantity = fields.Float(
        string="Difference",
        digits="Product Unit",
        compute="_compute_inventory_diff_quantity",
        store=True,
        readonly=True,
        help="Indicates the gap between the product's theoretical quantity and its counted quantity.",
    )
    inventory_date = fields.Date(
        string="Scheduled",
        compute="_compute_inventory_date",
        store=True,
        readonly=False,
        help="Next date the On Hand Quantity should be counted.",
    )
    last_count_date = fields.Date(
        compute="_compute_last_count_date",
        help="Last time the Quantity was Updated",
    )
    inventory_quantity_set = fields.Boolean(
        compute="_compute_inventory_quantity_set",
        store=True,
        readonly=False,
    )
    is_outdated = fields.Boolean(
        string="Quantity has been moved since last count",
        compute="_compute_is_outdated",
        search="_search_is_outdated",
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Assigned To",
        domain=lambda self: [
            ("all_group_ids", "in", self.env.ref("stock.group_stock_user").id)
        ],
        help="User assigned to do product count.",
    )

    # Serves _gather()'s lookups, _merge_quants()'s GROUP BY and
    # _get_quants_by_products_locations()'s _read_group. Column order matches the
    # common groupby: product, location, lot, package, owner. company_id is last
    # since the _read_group calls don't include it.
    #
    # There is deliberately no narrower (product_id, location_id) index beside it:
    # that pair is this index's own leading prefix, so Postgres serves a prefix
    # lookup from here and never chose the narrow one when both existed (measured
    # at 200k rows / 20k lots: 2400 _gather calls, 2400 scans here, 0 there). The
    # extra columns are a bonus, not a cost -- the strict gather's
    # lot/package/owner IS NULL predicates move out of a heap Filter and into the
    # Index Cond. Same reasoning as the standalone product_id index dropped below.
    _quant_merge_idx = models.Index(
        "(product_id, location_id, lot_id, package_id, owner_id, company_id)"
    )

    def init(self):
        super().init()
        # product_id and (product_id, location_id) both dropped their index: each is
        # a leading prefix of _quant_merge_idx, so a separate btree is pure write
        # overhead on this hot table. `_auto_init` no longer creates them, but the
        # ORM never drops indexes it once made, so remove the now-orphans here.
        # Idempotent, and runs after `_auto_init` so they won't be recreated
        # underneath us.
        self.env.cr.execute("DROP INDEX IF EXISTS stock_quant__product_id_index")
        self.env.cr.execute("DROP INDEX IF EXISTS stock_quant_product_location_idx")

    @api.constrains("location_id")
    def check_location_id(self):
        for quant in self:
            if quant.location_id.usage == "view":
                raise ValidationError(
                    _(
                        'You cannot take products from or deliver products to a location of type "view" (%s).',
                        quant.location_id.name,
                    )
                )

    @api.constrains("product_id")
    def check_product_id(self):
        non_storable = self.product_id.filtered(lambda p: not p.is_storable)
        if non_storable:
            raise ValidationError(
                _(
                    "Quants cannot be created for consumables or services: %s",
                    ", ".join(non_storable.mapped("display_name")),
                )
            )

    @api.constrains("lot_id")
    def check_lot_id(self):
        for quant in self:
            if quant.lot_id.product_id and quant.lot_id.product_id != quant.product_id:
                raise ValidationError(
                    _(
                        "The Lot/Serial number (%s) is linked to another product.",
                        quant.lot_id.name,
                    )
                )

    @api.model_create_multi
    def create(self, vals_list):
        """Override to handle "inventory mode": create/update the matching quant as
        superuser when the conditions are met.
        """

        def _add_to_cache(quant):
            if "quants_cache" in self.env.context:
                self.env.context["quants_cache"][
                    quant.product_id.id,
                    quant.location_id.id,
                    quant.lot_id.id,
                    quant.package_id.id,
                    quant.owner_id.id,
                ] |= quant

        is_inventory_mode = self._is_inventory_mode()
        allowed_fields = self._get_inventory_fields_create()
        results = [self.env["stock.quant"]] * len(vals_list)
        plain_vals = []
        for index, vals in enumerate(vals_list):
            if is_inventory_mode and any(
                f in vals
                for f in ["inventory_quantity", "inventory_quantity_auto_apply"]
            ):
                quant, created = self._create_inventory_quant(vals, allowed_fields)
                if created:
                    _add_to_cache(quant)
                results[index] = quant
            else:
                if "inventory_quantity" not in vals:
                    vals["inventory_quantity_set"] = vals.get(
                        "inventory_quantity_set", False
                    )
                plain_vals.append((index, vals))
        if plain_vals:
            plain_records = super().create([vals for _index, vals in plain_vals])
            for (index, _vals), quant in zip(plain_vals, plain_records, strict=True):
                _add_to_cache(quant)
                results[index] = quant
                if is_inventory_mode and quant.company_id:
                    quant._check_company()
        return self.env["stock.quant"].union(*results)

    def _create_inventory_quant(self, vals, allowed_fields):
        """Create or update the single quant an inventory-mode ``create`` row targets.

        Split out of :meth:`create` so its batch loop reads as a clean "inventory
        rows one at a time / plain rows batched" split. ``vals`` is consumed in place
        (inventory-quantity keys are popped). Returns ``(quant, created)`` where
        ``created`` is ``True`` only when a brand-new quant was inserted (so the
        caller knows whether to seed ``quants_cache``).
        """
        if any(
            not field.startswith("x_") and field not in allowed_fields for field in vals
        ):
            raise UserError(
                _("Quant's creation is restricted, you can't do this operation.")
            )
        if "inventory_quantity_auto_apply" in vals:
            auto_apply = True
            inventory_quantity = vals.pop("inventory_quantity_auto_apply") or 0
            vals.pop("inventory_quantity", None)
        else:
            auto_apply = False
            inventory_quantity = vals.pop("inventory_quantity", False) or 0
        product = self.env["product.product"].browse(vals["product_id"])
        location = self.env["stock.location"].browse(vals["location_id"])
        lot_id = self.env["stock.lot"].browse(vals.get("lot_id"))
        package_id = self.env["stock.package"].browse(vals.get("package_id"))
        owner_id = self.env["res.partner"].browse(vals.get("owner_id"))
        quant = self.env["stock.quant"]
        if not self.env.context.get("import_file"):
            quant = self._gather(
                product,
                location,
                lot_id=lot_id,
                package_id=package_id,
                owner_id=owner_id,
                strict=True,
            )
        if lot_id:
            if self.env.context.get("import_file") and lot_id.product_id != product:
                lot_name = lot_id.name
                lot_id = self.env["stock.lot"].search(
                    [("product_id", "=", product.id), ("name", "=", lot_name)],
                    limit=1,
                )
                if not lot_id:
                    company_id = location.company_id or self.env.company
                    lot_id = self.env["stock.lot"].create(
                        {
                            "name": lot_name,
                            "product_id": product.id,
                            "company_id": company_id.id,
                        }
                    )
                vals["lot_id"] = lot_id.id
            quant = quant.filtered(lambda q: q.lot_id)
        created = False
        if quant:
            quant = quant[0].sudo()
        else:
            quant = self.sudo().create(vals)
            created = True
        if auto_apply:
            quant.write({"inventory_quantity_auto_apply": inventory_quantity})
        else:
            quant.inventory_quantity = inventory_quantity
            quant.user_id = vals.get("user_id", self.env.user.id)
            quant.inventory_date = fields.Date.today()
        return quant, created

    def write(self, vals):
        """Override to handle the "inventory mode" and create the inventory move."""
        forbidden_fields = self._get_forbidden_fields_write()
        if self._is_inventory_mode() and any(
            field in vals for field in forbidden_fields
        ):
            if self.filtered(lambda quant: quant.location_id.usage != "inventory"):
                raise UserError(
                    _("Quant's editing is restricted, you can't do this operation.")
                )
            return True
        return super().write(vals)

    def copy(self, default=None):
        raise UserError(_("You cannot duplicate stock quants."))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_wrong_permission(self):
        if not self.env.is_superuser():
            if not self.env.user.has_group("stock.group_stock_manager"):
                raise UserError(
                    _(
                        "Quants are auto-deleted when appropriate. If you must manually delete them, please ask a stock manager to do it."
                    )
                )
            self = self.with_context(inventory_mode=True)
            self.inventory_quantity = 0
            self._apply_inventory()

    def _stock_user_domain(self, domain):
        """Return field-``domain`` expression ``domain`` for stock users, ``"[]"``
        otherwise.

        The three quant pickers below only constrain their choices for stock users
        in inventory mode; everyone else gets the unrestricted ``"[]"``. Factored so
        the ``has_group`` guard lives in one place instead of being re-spelled (and
        drifting) across each field.
        """
        return domain if self.env.user.has_group("stock.group_stock_user") else "[]"

    def _domain_location_id(self):
        return self._stock_user_domain(
            "[('usage', 'in', ['internal', 'transit'])] if context.get('inventory_mode') else []"
        )

    def _domain_lot_id(self):
        return self._stock_user_domain(
            "[] if not context.get('inventory_mode') else"
            " [('product_id', '=', context.get('active_id', False))] if context.get('active_model') == 'product.product' else"
            " [('product_id.product_tmpl_id', '=', context.get('active_id', False))] if context.get('active_model') == 'product.template' else"
            " [('product_id', '=', product_id)]"
        )

    def _domain_product_id(self):
        return self._stock_user_domain(
            "[] if not context.get('inventory_mode') else"
            " [('is_storable', '=', True), ('product_tmpl_id', 'in', context.get('product_tmpl_ids', []) + [context.get('product_tmpl_id', 0)])] if context.get('product_tmpl_ids') or context.get('product_tmpl_id') else"
            " [('is_storable', '=', True)]"
        )

    @api.depends("quantity", "reserved_quantity")
    def _compute_available_quantity(self):
        for quant in self:
            quant.available_quantity = quant.quantity - quant.reserved_quantity

    @api.depends("location_id")
    def _compute_inventory_date(self):
        quants = self.filtered(
            lambda q: (
                not q.inventory_date and q.location_id.usage in ["internal", "transit"]
            )
        )
        quants._update_next_inventory_date()

    @api.depends("product_id", "location_id", "lot_id", "package_id", "owner_id")
    def _compute_last_count_date(self):
        """We look at the stock move lines associated with every quant to get the last count date.

        The depends covers the characteristics this keys on. It cannot cover the
        move lines themselves -- the value comes from a `_read_group` over
        `stock.move.line`, not from a field path -- so a count booked later in the
        same transaction still needs an explicit invalidation to show up. Without any
        depends at all the value never refreshed, not even when the quant was
        re-pointed at another product or location.
        """
        self.last_count_date = False
        groups = self.env["stock.move.line"]._read_group(
            [
                ("state", "=", "done"),
                ("is_inventory", "=", True),
                ("product_id", "in", self.product_id.ids),
                "|",
                ("lot_id", "in", self.lot_id.ids),
                ("lot_id", "=", False),
                "|",
                ("owner_id", "in", self.owner_id.ids),
                ("owner_id", "=", False),
                "|",
                ("location_id", "in", self.location_id.ids),
                ("location_dest_id", "in", self.location_id.ids),
                "|",
                ("package_id", "=", False),
                "|",
                ("package_id", "in", self.package_id.ids),
                ("result_package_id", "in", self.package_id.ids),
            ],
            [
                "product_id",
                "lot_id",
                "package_id",
                "owner_id",
                "result_package_id",
                "location_id",
                "location_dest_id",
            ],
            ["date:max"],
        )

        date_by_quant = {}
        for (
            product,
            lot,
            package,
            owner,
            result_package,
            location,
            location_dest,
            move_line_date,
        ) in groups:
            for loc in (location, location_dest):
                for pkg in (package, result_package):
                    key = (loc.id, pkg.id, product.id, lot.id, owner.id)
                    current = date_by_quant.get(key)
                    if not current or move_line_date > current:
                        date_by_quant[key] = move_line_date
        for quant in self:
            quant.last_count_date = date_by_quant.get(
                (
                    quant.location_id.id,
                    quant.package_id.id,
                    quant.product_id.id,
                    quant.lot_id.id,
                    quant.owner_id.id,
                )
            )

    @api.depends("inventory_quantity", "inventory_quantity_set")
    def _compute_inventory_diff_quantity(self):
        for quant in self:
            if quant.inventory_quantity_set:
                quant.inventory_diff_quantity = (
                    quant.inventory_quantity - quant.quantity
                )
            else:
                quant.inventory_diff_quantity = 0

    @api.depends("inventory_quantity")
    def _compute_inventory_quantity_set(self):
        self.inventory_quantity_set = True

    @api.depends("inventory_quantity", "quantity", "product_id")
    def _compute_is_outdated(self):
        for quant in self:
            quant.is_outdated = quant._is_outdated()

    @api.depends("quantity")
    def _compute_inventory_quantity_auto_apply(self):
        for quant in self:
            quant.inventory_quantity_auto_apply = quant.quantity

    @api.depends("lot_id")
    def _compute_sn_duplicated(self):
        self.sn_duplicated = False
        domain = [
            ("tracking", "=", "serial"),
            ("lot_id", "in", self.lot_id.ids),
            ("quantity", ">", 0),
            ("location_id.usage", "in", ["internal", "transit"]),
        ]
        results = self._read_group(domain, ["lot_id"], having=[("__count", ">", 1)])
        duplicated_sn_ids = {lot.id for [lot] in results}
        self.filtered(lambda q: q.lot_id.id in duplicated_sn_ids).sn_duplicated = True

    @api.depends("location_id", "lot_id", "package_id", "owner_id")
    def _compute_display_name(self):
        """name that will be displayed in the detailed operation"""
        for record in self:
            if record.env.context.get("formatted_display_name"):
                name = f"{record.location_id.name}"
                if record.package_id:
                    name += f"\t--{record.package_id.display_name}--"
                if record.lot_id:
                    name += (
                        " " if record.package_id else "\t"
                    ) + f"--{record.lot_id.name}--"
                record.display_name = name
            else:
                if not record.ids:
                    record.display_name = ""
                    continue
                name = [record.location_id.display_name]
                if record.lot_id:
                    name.append(record.lot_id.name)
                if record.package_id:
                    name.append(record.package_id.display_name)
                if record.owner_id:
                    name.append(record.owner_id.name)
                record.display_name = " - ".join(name)

    def _inverse_inventory_quantity(self):
        """Inverse method to create stock move when `inventory_quantity` is set
        (`inventory_quantity` is only accessible in inventory mode).
        """
        if not self._is_inventory_mode():
            return
        quant_to_inventory = self.env["stock.quant"]
        for quant in self:
            if (
                quant.product_uom_id.compare(
                    quant.quantity, quant.inventory_quantity_auto_apply
                )
                == 0
            ):
                continue
            quant.inventory_quantity = quant.inventory_quantity_auto_apply
            quant_to_inventory |= quant
        quant_to_inventory.action_apply_inventory()

    def _search(self, domain, *args, **kwargs):
        domain = Domain(domain).map_conditions(
            lambda condition: (
                Domain("lot_id", "any", [condition])
                if condition.field_expr.startswith("lot_properties.")
                else condition
            )
        )
        return super()._search(domain, *args, **kwargs)

    def _search_is_outdated(self, operator, value):
        if operator != "in":
            return NotImplemented
        self.env["stock.quant"].flush_model(
            [
                "inventory_quantity_set",
                "inventory_quantity",
                "inventory_diff_quantity",
                "quantity",
            ]
        )
        digits = self.env["decimal.precision"].precision_get("Product Unit")
        rows = self.env.execute_query(
            SQL(
                """SELECT id FROM stock_quant
                    WHERE inventory_quantity_set = TRUE
                      AND round((COALESCE(inventory_quantity, 0)
                                 - COALESCE(inventory_diff_quantity, 0))::numeric, %s)
                          != round(COALESCE(quantity, 0)::numeric, %s)""",
                digits,
                digits,
            )
        )
        return [("id", "in", [row[0] for row in rows])]

    def _search_on_hand(self, operator, value):
        """Handle the "on_hand" filter, indirectly calling `_get_domain_locations`."""
        if operator != "in":
            return NotImplemented
        return self.env["product.product"]._get_domain_locations()[0]

    @api.onchange("location_id", "product_id", "lot_id", "package_id", "owner_id")
    def _onchange_location_or_product_id(self):
        vals = {}

        if self.product_id and self.location_id:
            if self.lot_id:
                if self.tracking == "none" or self.product_id != self.lot_id.product_id:
                    vals["lot_id"] = None

            quant = self._gather(
                self.product_id,
                self.location_id,
                lot_id=self.lot_id,
                package_id=self.package_id,
                owner_id=self.owner_id,
                strict=True,
            )
            self.quantity = sum(
                quant.filtered(lambda q: q.lot_id == self.lot_id).mapped("quantity")
            )

            if self.lot_id and self.tracking == "serial":
                vals["inventory_quantity"] = 1
                vals["inventory_quantity_auto_apply"] = 1

        if vals:
            self.update(vals)

    @api.onchange("inventory_quantity")
    def _onchange_inventory_quantity(self):
        if self.location_id and self.location_id.usage == "inventory":
            warning = {
                "title": _("You cannot modify inventory loss quantity"),
                "message": _(
                    "Editing quantities in an Inventory Adjustment location is forbidden,"
                    "those locations are used as counterpart when correcting the quantities."
                ),
            }
            return {"warning": warning}
        return None

    @api.onchange("lot_id")
    def _onchange_serial_number(self):
        if self.lot_id and self.product_id.tracking == "serial":
            message, _recommended_location = (
                self.env["stock.quant"]
                .sudo()
                ._check_serial_number(self.product_id, self.lot_id, self.company_id)
            )
            if message:
                return {"warning": {"title": _("Warning"), "message": message}}
        return None

    @api.onchange("product_id", "company_id")
    def _onchange_product_id(self):
        if self.location_id:
            return
        if self.product_id.tracking in ["lot", "serial"]:
            previous_quants = self.env["stock.quant"].search(
                [
                    ("product_id", "=", self.product_id.id),
                    ("location_id.usage", "in", ["internal", "transit"]),
                ],
                limit=1,
                order="create_date desc",
            )
            if previous_quants:
                self.location_id = previous_quants.location_id
        if not self.location_id:
            company_id = (self.company_id and self.company_id.id) or self.env.company.id
            self.location_id = (
                self.env["stock.warehouse"]
                .search([("company_id", "=", company_id)], limit=1)
                .lot_stock_id
            )

    def action_view_stock_moves(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "stock.stock_move_line_action"
        )
        domain = (
            Domain("location_id", "=", self.location_id.id)
            | Domain("location_dest_id", "=", self.location_id.id)
        ) & Domain("lot_id", "=", self.lot_id.id)
        if self.package_id:
            domain &= Domain("package_id", "=", self.package_id.id) | Domain(
                "result_package_id", "=", self.package_id.id
            )
        action["domain"] = domain
        # `or "{}"`: an action with no context stores "" / None, which literal_eval
        # rejects with SyntaxError rather than returning an empty dict.
        action["context"] = literal_eval(action.get("context") or "{}")
        action["context"]["search_default_product_id"] = self.product_id.id
        return action

    def action_view_orderpoints(self):
        action = self.env["product.product"].action_view_orderpoints()
        action["domain"] = [("product_id", "=", self.product_id.id)]
        return action

    @api.model
    def action_view_quants(self):
        self = self.with_context(search_default_internal_loc=1)
        self = self._set_view_context()
        return self._get_quants_action(extend=True)

    @api.model
    def action_view_inventory(self):
        """Similar to _get_quants_action except specific for inventory adjustments (i.e. inventory counts)."""
        self = self._set_view_context()
        if (
            not self.env["ir.config_parameter"]
            .sudo()
            .get_param("stock.skip_quant_tasks")
        ):
            self._quant_tasks()

        ctx = dict(self.env.context or {})
        ctx["no_at_date"] = True
        if self.env.user.has_group(
            "stock.group_stock_user"
        ) and not self.env.user.has_group("stock.group_stock_manager"):
            ctx["search_default_my_count"] = True
        view_id = self.env.ref("stock.view_stock_quant_list_inventory_editable").id
        return {
            "name": _("Physical Inventory"),
            "view_mode": "list",
            "res_model": "stock.quant",
            "type": "ir.actions.act_window",
            "context": ctx,
            "domain": [("location_id.usage", "in", ["internal", "transit"])],
            "views": [(view_id, "list")],
            "help": """
                <p class="o_view_nocontent_smiling_face">
                    {}
                </p>
                <p>
                    {} <span class="fa-solid fa-cog"/>
                </p>
                """.format(
                escape(_("Your stock is currently empty")),
                escape(
                    _(
                        'Press the "New" button to define the quantity for a product in your stock or import quantities from a spreadsheet via the Actions menu'
                    )
                ),
            ),
        }

    def action_apply_inventory(self, date=None):
        ctx = dict(self.env.context or {})
        ctx["default_quant_ids"] = self.ids
        quants_outdated = self.filtered(lambda quant: quant.is_outdated)
        if quants_outdated:
            ctx["default_quant_to_fix_ids"] = quants_outdated.ids
            return {
                "name": _("Conflict in Inventory Adjustment"),
                "type": "ir.actions.act_window",
                "view_mode": "form",
                "views": [(False, "form")],
                "res_model": "stock.inventory.conflict",
                "target": "new",
                "context": ctx,
            }
        # No `inventory_quantity_set = False` here: `_apply_inventory` ends in
        # `action_clear_inventory_quantity`, which already cleared it.
        self._apply_inventory(date)
        return None

    def action_stock_quant_relocate(self):
        if (
            len(self.company_id) > 1
            or any(not q.company_id.id for q in self)
            or any(q.product_uom_id.compare(q.quantity, 0) <= 0 for q in self)
        ):
            raise UserError(
                _(
                    "You can only move positive quantities stored in locations used by a single company per relocation."
                )
            )
        context = {
            "default_quant_ids": self.ids,
            "default_lot_id": self.env.context.get("default_lot_id", False),
            "single_product": self.env.context.get("single_product", False),
        }
        return {
            "res_model": "stock.quant.relocate",
            "views": [[False, "form"]],
            "target": "new",
            "type": "ir.actions.act_window",
            "context": context,
        }

    def action_inventory_history(self):
        self.ensure_one()
        action = {
            "name": _("History"),
            "view_mode": "list,form",
            "res_model": "stock.move.line",
            "views": [
                (self.env.ref("stock.view_stock_move_line_list").id, "list"),
                (False, "form"),
            ],
            "type": "ir.actions.act_window",
            "context": {
                "search_default_inventory": 1,
                "search_default_done": 1,
                "search_default_product_id": self.product_id.id,
            },
            "domain": [
                ("company_id", "=", self.company_id.id),
                "|",
                ("location_id", "=", self.location_id.id),
                ("location_dest_id", "=", self.location_id.id),
            ],
        }
        if self.lot_id:
            action["context"]["search_default_lot_id"] = self.lot_id.id
        if self.package_id:
            action["context"]["search_default_package_id"] = self.package_id.id
            action["context"]["search_default_result_package_id"] = self.package_id.id
        if self.owner_id:
            action["context"]["search_default_owner_id"] = self.owner_id.id
        return action

    def action_set_inventory_quantity(self):
        quants_already_set = self.filtered(lambda quant: quant.inventory_quantity_set)
        if quants_already_set:
            ctx = dict(self.env.context or {}, default_quant_ids=self.ids)
            view = self.env.ref("stock.inventory_warning_set_view", False)
            return {
                "name": _("Quantities Already Set"),
                "type": "ir.actions.act_window",
                "view_mode": "form",
                "views": [(view.id, "form")],
                "view_id": view.id,
                "res_model": "stock.inventory.warning",
                "target": "new",
                "context": ctx,
            }
        if not self.env.context.get("from_request_count"):
            for quant in self:
                quant.inventory_quantity = quant.quantity
        self.user_id = self.env.user.id
        self.inventory_quantity_set = True
        return None

    def action_apply_all(self):
        active_domain = self.env.context.get("active_domain") or [
            ("id", "in", self.ids)
        ]
        quant_ids = self.env["stock.quant"].search(active_domain).ids
        ctx = dict(self.env.context or {}, default_quant_ids=quant_ids)
        view = self.env.ref("stock.stock_inventory_adjustment_name_form_view", False)
        return {
            "name": _("Inventory Adjustment"),
            "type": "ir.actions.act_window",
            "views": [(view.id, "form")],
            "res_model": "stock.inventory.adjustment.name",
            "target": "new",
            "context": ctx,
        }

    def action_reset(self):
        ctx = dict(self.env.context or {}, default_quant_ids=self.ids)
        view = self.env.ref("stock.inventory_warning_reset_view", False)
        return {
            "name": _("Quantities To Reset"),
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "views": [(view.id, "form")],
            "view_id": view.id,
            "res_model": "stock.inventory.warning",
            "target": "new",
            "context": ctx,
        }

    def action_clear_inventory_quantity(self):
        self.inventory_quantity = 0
        self.inventory_diff_quantity = 0
        self.inventory_quantity_set = False
        self.user_id = False

    def action_set_inventory_quantity_zero(self):
        self.inventory_quantity = 0
        if self.env.context.get("inventory_report_mode"):
            self._apply_inventory()
        else:
            self.user_id = self.env.user.id

    def _update_next_inventory_date(self):
        """Set ``inventory_date`` on every quant in ``self`` to its location's next
        scheduled count date, resolving each location's date only once. The caller
        decides which quants qualify (``_compute_inventory_date`` filters to
        uncounted internal/transit quants; ``_apply_inventory`` reschedules all).
        """
        date_by_location = {
            loc: loc._get_next_inventory_date() for loc in self.location_id
        }
        for quant in self:
            quant.inventory_date = date_by_location[quant.location_id]

    @api.model
    def name_create(self, name):
        return False

    def _load_records_create(self, values):
        """Add default location if import file did not fill it"""
        company_user = self.env.company
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", company_user.id)], limit=1
        )
        for value in values:
            if "location_id" not in value:
                value["location_id"] = warehouse.lot_stock_id.id
        return super(
            StockQuant, self.with_context(inventory_mode=True)
        )._load_records_create(values)

    def _load_records_write(self, values):
        """Set inventory_mode so write() restricts the fields editable by import."""
        return super(
            StockQuant, self.with_context(inventory_mode=True)
        )._load_records_write(values)

    def _read_group_select(self, aggregate_spec, query):
        if aggregate_spec == "inventory_quantity:sum" and self.env.context.get(
            "inventory_report_mode"
        ):
            return SQL("NULL")
        if aggregate_spec == "available_quantity:sum":
            sql_quantity = self._read_group_select("quantity:sum", query)
            sql_reserved_quantity = self._read_group_select(
                "reserved_quantity:sum", query
            )
            return SQL("%s - %s", sql_quantity, sql_reserved_quantity)
        if aggregate_spec == "inventory_quantity_auto_apply:sum":
            return self._read_group_select("quantity:sum", query)
        return super()._read_group_select(aggregate_spec, query)

    @api.model
    def get_import_templates(self):
        return [
            {
                "label": _("Import Template for Inventory Adjustments"),
                "template": "/stock/static/xlsx/stock_quant.xlsx",
            }
        ]

    @api.model
    def _get_forbidden_fields_write(self):
        """Returns a list of fields user can't edit when he want to edit a quant in `inventory_mode`."""
        return ["product_id", "location_id", "lot_id", "package_id", "owner_id"]

    def _run_least_packages_removal_strategy_astar(self, domain, qty):
        domain = Domain(domain).optimize(self)
        query = self._search(domain, bypass_access=True)
        query.groupby = SQL("package_id")
        query.having = SQL("SUM(quantity - reserved_quantity) > 0")
        query.order = SQL("available_qty DESC")
        qty_by_package = self.env.execute_query(
            query.select(
                "package_id", "SUM(quantity - reserved_quantity) AS available_qty"
            )
        )

        real_packages = []
        singles_count = 0
        for package_id, available_qty in qty_by_package:
            if package_id is None:
                singles_count += int(available_qty)
            else:
                # No `available_qty != 0` guard: `query.having` above already keeps
                # only groups with SUM(quantity - reserved_quantity) > 0.
                real_packages.append((package_id, available_qty))

        if not real_packages:
            return domain

        try:
            qty_by_package = real_packages + [(None, 1)] * singles_count
            taken_packages = _least_packages_search(qty_by_package, qty)
            return self._least_packages_domain(taken_packages, domain)
        except MemoryError:
            _logger.info(
                "Ran out of memory while trying to use the least_packages strategy to get quants. Domain: %s",
                domain,
            )
            return domain

    def _least_packages_domain(self, taken_packages, domain):
        """Build the search domain covering the packages/singles selected by
        :func:`_least_packages_search`.

        Unpackaged singles are resolved to concrete quant ids in a single query.

        ``single_count`` counts selected *unit slots*: the A* sized it from the
        unpackaged group's **available** sum, expanding it into one ``(None, 1)`` entry
        per available unit. Redeeming those slots must therefore also count available
        units. Taking the first ``single_count`` *records* instead -- as this did --
        assumes every loose quant carries at least one available unit, which a fully
        reserved, fractional or negative quant does not. Being older, such a quant sorts
        to the head of the FIFO order below, so it consumed a slot, supplied nothing,
        and pushed the quants that do hold stock out of the candidate set: the gather
        then saw only empty quants and reserved zero while availability reported the
        full amount. Accumulate availability instead, and skip what cannot contribute.

        The A* fixes the loose-unit *count*, not which quants, so walk the FIFO-oldest
        singles (``in_date, id``) -- matching the ``least_packages`` removal order.
        Slicing the tail would restrict the candidate set to the *newest* loose quants
        and strand older stock the final strategy-ordered gather could never reconsider.

        Over-covering on the unpackaged side stays harmless: the reservation loop caps
        consumption at the requested quantity, and the package set is pinned exactly by
        ``package_id in [...]`` below, so no extra package is ever opened.
        """
        single_count = sum(1 for pkg in taken_packages if pkg[0] is None)
        selected_single_items = []
        if single_count:
            for quant in self.search(
                Domain("package_id", "=", False) & domain, order="in_date, id"
            ):
                if single_count <= 0:
                    break
                available = quant.quantity - quant.reserved_quantity
                if available <= 0:
                    continue
                selected_single_items.append(quant.id)
                single_count -= available

        return (
            Domain(
                "package_id",
                "in",
                [pkg[0] for pkg in taken_packages if pkg[0] is not None],
            )
            | Domain("id", "in", selected_single_items)
        ) & domain

    def _gather(
        self,
        product_id,
        location_id,
        lot_id=None,
        package_id=None,
        owner_id=None,
        strict=False,
        qty=0,
    ):
        """Return the quants matching the given characteristics, ordered by the
        location/product removal strategy.

        Despite the historic name, this does **not** filter ``self``: it always
        resolves the candidate set from scratch -- by searching, or (for a strict,
        non-``least_packages`` gather inside a ``quants_cache`` context) from the
        pre-grouped cache. ``self`` is used only for ``env``/model access. A caller
        holding a gathered recordset must not assume passing it as ``self`` narrows the
        result (see ``_get_reserve_quantity``, which reuses its gather explicitly).

        This is an **extension point** overridden in sibling repos (e.g. agromarin's
        ``marin`` and ``stock_blocked_location``). Its public signature must stay
        stable: any per-call optimisation the reservation path needs is threaded via
        the private ``_gather_removal_strategy`` context key below, never as a new
        positional/keyword argument -- so an override with a fixed signature (or one
        forwarding ``**kwargs``) can never be broken by a caller passing a hint it does
        not declare. (A ``removal_strategy=`` kwarg here once crashed those overrides
        with ``TypeError`` on every reservation; the guard test in
        ``test_quant_improvements`` locks the signature down.)

        The context key holds a pre-resolved removal strategy for this
        product/location: resolving it walks the product category + location parent
        chain, so the reservation path (which gathers/measures the same characteristics
        up to three times) resolves once and threads the result. Absent the key it is
        resolved here.
        """
        removal_strategy = self.env.context.get(
            "_gather_removal_strategy"
        ) or self._get_removal_strategy(product_id, location_id)
        domain = self._get_gather_domain(
            product_id,
            location_id,
            lot_id,
            package_id,
            owner_id,
            strict,
        )

        if removal_strategy == "least_packages" and qty:
            domain = self._run_least_packages_removal_strategy_astar(domain, qty)

        order = self._get_removal_strategy_order(removal_strategy)
        quants_cache = self.env.context.get("quants_cache")
        cache_sort = self._get_removal_strategy_sort_key(removal_strategy)

        if (
            quants_cache is not None
            and strict
            and removal_strategy != "least_packages"
            and cache_sort is not None
            and quants_cache.covers(product_id, location_id, lot_id)
            and domain
            == StockQuant._get_gather_domain(
                self, product_id, location_id, lot_id, package_id, owner_id, strict
            )
        ):
            package_key = package_id.id if package_id else False
            owner_key = owner_id.id if owner_id else False
            res = self.env["stock.quant"]
            if lot_id:
                res |= quants_cache[
                    product_id.id, location_id.id, lot_id.id, package_key, owner_key
                ]
            res |= quants_cache[
                product_id.id, location_id.id, False, package_key, owner_key
            ]
            with_expiration = self.env.context.get("with_expiration")
            if with_expiration:
                cutoff = fields.Datetime.to_datetime(with_expiration)
                res = res.filtered(
                    lambda q: not q.removal_date or q.removal_date >= cutoff
                )
            sort_key, sort_reverse = cache_sort
            res = res.sorted(sort_key, reverse=sort_reverse)
        else:
            res = self.search(domain, order=order)

        if removal_strategy == "closest":
            res = res.sorted(lambda q: (q.location_id.complete_name, -q.id))

        return res.sorted(lambda q: not q.lot_id)

    def _apply_inventory(self, date=None):
        self.inventory_quantity_set = True
        move_vals = []
        default_loss_locations = {}
        # The product's loss location is company-dependent, so it is keyed by both.
        # Resolved once here and read from the map below, rather than re-derived per
        # quant inside the loop as well as in this filter.
        loss_location_by_product_company = {
            (quant.product_id.id, quant.company_id.id): quant.product_id.with_company(
                quant.company_id
            ).property_stock_inventory
            for quant in self
        }
        quants_with_missing_loss_locations = self.filtered(
            lambda quant: (
                not loss_location_by_product_company[
                    quant.product_id.id, quant.company_id.id
                ]
            )
        )
        if quants_with_missing_loss_locations:
            for company in quants_with_missing_loss_locations.mapped("company_id"):
                loss_location_id = (
                    self.env["ir.default"]
                    .with_company(company)
                    ._get_model_defaults("product.template")
                    .get("property_stock_inventory")
                )
                default_loss_locations[company.id] = self.env["stock.location"].browse(
                    loss_location_id
                )
        for quant in self:
            if (
                quant.env.context.get("from_inverse_qty")
                and quant.product_uom_id.compare(quant.inventory_diff_quantity, 0) == 0
            ):
                continue
            inventory_location = loss_location_by_product_company[
                quant.product_id.id, quant.company_id.id
            ] or default_loss_locations.get(quant.company_id.id)
            if not inventory_location:
                raise UserError(
                    _(
                        "No inventory loss location is configured for product "
                        "%(product)s (company %(company)s). Set one on the product "
                        "or in the company's default product settings.",
                        product=quant.product_id.display_name,
                        company=quant.company_id.display_name
                        or self.env.company.display_name,
                    )
                )
            if quant.product_uom_id.compare(quant.inventory_diff_quantity, 0) > 0:
                move_vals.append(
                    quant._get_inventory_move_values(
                        quant.inventory_diff_quantity,
                        inventory_location,
                        quant.location_id,
                        package_dest_id=quant.package_id,
                    )
                )
            else:
                move_vals.append(
                    quant._get_inventory_move_values(
                        -quant.inventory_diff_quantity,
                        quant.location_id,
                        inventory_location,
                        package_id=quant.package_id,
                    )
                )
        moves = (
            self.env["stock.move"].with_context(inventory_mode=False).create(move_vals)
        )
        moves.with_context(ignore_dest_packages=True)._action_done()
        if date:
            moves.date = date
        moves._trigger_assign()
        self.location_id.sudo().write({"last_inventory_date": fields.Date.today()})
        self._update_next_inventory_date()
        self.action_clear_inventory_quantity()

    @api.model
    def _update_available_quantity(
        self,
        product_id,
        location_id,
        quantity=False,
        reserved_quantity=False,
        lot_id=None,
        package_id=None,
        owner_id=None,
        in_date=None,
    ):
        """Increase or decrease `quantity` or `reserved_quantity` of a set of quants for a given
        product_id/location_id/lot_id/package_id/owner_id.

        :param datetime in_date: Should only be passed when calls to this method are done in
                                 order to move a quant. When creating a tracked quant, the
                                 current datetime will be used.
        :return: tuple (available_quantity, in_date as a datetime)
        """
        if not (quantity or reserved_quantity):
            raise ValidationError(_("Quantity or Reserved Quantity should be set."))
        self = self.sudo()
        self = self.with_context(
            _gather_removal_strategy=self._get_removal_strategy(product_id, location_id)
        )
        gathered = self._gather(
            product_id,
            location_id,
            lot_id=lot_id,
            package_id=package_id,
            owner_id=owner_id,
            strict=True,
        )
        quants = gathered
        if lot_id:
            if product_id.uom_id.compare(quantity, 0) > 0:
                quants = quants.filtered(lambda q: q.lot_id)
            else:
                quants = quants.filtered(
                    lambda q: product_id.uom_id.compare(q.quantity, 0) > 0 or q.lot_id,
                )

        if location_id.should_bypass_reservation():
            incoming_dates = []
        else:
            incoming_dates = [
                quant.in_date
                for quant in quants
                if quant.in_date and quant.product_uom_id.compare(quant.quantity, 0) > 0
            ]
        if in_date:
            incoming_dates += [in_date]
        if incoming_dates:
            in_date = min(incoming_dates)
        else:
            in_date = fields.Datetime.now()

        quant = None
        if quants:
            lockable = quants
            if reserved_quantity and reserved_quantity < 0:
                reserved_rows = quants.filtered(
                    lambda q: q.product_uom_id.compare(q.reserved_quantity, 0) > 0
                )
                if reserved_rows:
                    lockable = reserved_rows
            quant = lockable.try_lock_for_update(allow_referencing=True, limit=1)

        new_quant = self.env["stock.quant"]
        if quant:
            quant.invalidate_recordset(["quantity", "reserved_quantity"])
            vals = {"in_date": in_date}
            if quantity:
                vals["quantity"] = quant.quantity + quantity
            if reserved_quantity:
                vals["reserved_quantity"] = max(
                    0, quant.reserved_quantity + reserved_quantity
                )
            quant.write(vals)
        else:
            vals = {
                "product_id": product_id.id,
                "location_id": location_id.id,
                "lot_id": lot_id and lot_id.id,
                "package_id": package_id and package_id.id,
                "owner_id": owner_id and owner_id.id,
                "in_date": in_date,
            }
            if quantity:
                vals["quantity"] = quantity
            if reserved_quantity:
                vals["reserved_quantity"] = reserved_quantity
            new_quant = self.create(vals)
        avail_quants = gathered | new_quant
        with_expiration = self.env.context.get("with_expiration")
        if new_quant and with_expiration:
            cutoff = fields.Datetime.to_datetime(with_expiration)
            if new_quant.removal_date and new_quant.removal_date < cutoff:
                avail_quants -= new_quant
        return (
            self._sum_available_quantity(
                avail_quants,
                product_id,
                lot_id=lot_id,
                strict=True,
                allow_negative=True,
            ),
            in_date,
        )

    @api.model
    def _update_reserved_quantity(
        self,
        product_id,
        location_id,
        quantity,
        lot_id=None,
        package_id=None,
        owner_id=None,
    ):
        """Increase or decrease `reserved_quantity` of a set of quants for a given
        product_id/location_id/lot_id/package_id/owner_id.

        This always operates strictly (the exact characteristics tuple); reservation
        never needs the non-strict, child-location gather. It used to take a ``strict``
        flag that was never forwarded to `_update_available_quantity` (which hardcodes a
        strict gather), so it silently did nothing -- dropped to stop callers relying on
        a no-op.
        """
        self._update_available_quantity(
            product_id,
            location_id,
            reserved_quantity=quantity,
            lot_id=lot_id,
            package_id=package_id,
            owner_id=owner_id,
        )

    @api.model
    def _unlink_zero_quants(self, products=None, locations=None):
        """_update_available_quantity may leave quants with no
        quantity and no reserved_quantity. It used to directly unlink
        these zero quants but this proved to hurt the performance as
        this method is often called in batch and each unlink invalidate
        the cache. We defer the calls to unlink in this method.

        :param products, locations: optional recordsets scoping the cleanup to
            these product/location ids for model-level callers that know the
            touched scope but hold no quant recordset (e.g. the same-package
            path of ``stock.move._action_done``). Ignored when ``self`` holds
            records (the recordset defines the scope then).
        """
        # The candidate SELECT below is a hand-written SQL string, so its `to_flush`
        # is empty and `env.execute_query` flushes nothing for it -- it would read
        # the table while ORM writes to these four columns are still buffered, and
        # `unlink()` flushes before deleting, so a pending write would land and then
        # be dropped with the row. Today every caller happens to have flushed first
        # (`_quant_tasks` runs `_merge_quants`, whose `cr.savepoint()` flushes), but
        # that is their accident, not this method's contract. Flush explicitly, like
        # `_search_is_outdated` does for the same reason.
        self.env["stock.quant"].flush_model(
            ["quantity", "reserved_quantity", "inventory_quantity", "user_id"]
        )
        precision_digits = max(
            6, self.sudo().env.ref("uom.decimal_product_uom").digits * 2
        )
        query = SQL(
            """SELECT id FROM stock_quant
                WHERE (round(quantity::numeric, %s) = 0 OR quantity IS NULL)
                  AND round(reserved_quantity::numeric, %s) = 0
                  AND (round(inventory_quantity::numeric, %s) = 0 OR inventory_quantity IS NULL)
                  AND user_id IS NULL""",
            precision_digits,
            precision_digits,
            precision_digits,
        )
        if self._ids:
            quants = self.exists()
            products = quants.product_id
            locations = quants.location_id
        if products is not None and locations is not None:
            query = SQL(
                "%s AND location_id = ANY(%s) AND product_id = ANY(%s)",
                query,
                list(locations.ids),
                list(products.ids),
            )
        quants = self.env["stock.quant"].browse(
            row[0] for row in self.env.execute_query(query)
        )
        quants.sudo().unlink()

    @api.model
    def _clean_reservations(self, products=None, locations=None):
        """Realign quants' `reserved_quantity` with the sum still reserved by active
        move lines.

        Like its `_quant_tasks` siblings (`_merge_quants`, `_unlink_zero_quants`),
        a call on a recordset scopes the realignment to the touched
        product/location pairs instead of scanning the whole table; model-level
        callers (empty self) still run global unless they pass an explicit
        `products`/`locations` scope.

        :param products, locations: optional recordsets scoping the realignment
            for model-level callers that know the touched scope but hold no
            quant recordset. Unlike the recordset form, a products-only scope
            also covers (product, location) pairs with no quant row yet — the
            creation loop below provisions their reserved quants (needed by
            e.g. the consumable→storable flip, where open move lines predate
            any quant). Ignored when ``self`` holds records.
        """
        quant_domain = Domain("reserved_quantity", "!=", 0)
        move_line_domain = Domain(
            [
                (
                    "state",
                    "in",
                    ["assigned", "partially_available", "waiting", "confirmed"],
                ),
                ("quantity_product_uom", "!=", 0),
                ("product_id.is_storable", "=", True),
            ],
        )
        if self._ids:
            quants = self.exists()
            products = quants.product_id
            locations = quants.location_id
        if products is not None:
            scope_domain = Domain("product_id", "in", products.ids)
            if locations is not None:
                scope_domain &= Domain("location_id", "in", locations.ids)
            quant_domain &= scope_domain
            move_line_domain &= scope_domain
        elif locations is not None:
            scope_domain = Domain("location_id", "in", locations.ids)
            quant_domain &= scope_domain
            move_line_domain &= scope_domain
        reserved_quants = self.env["stock.quant"]._read_group(
            quant_domain,
            ["product_id", "location_id", "lot_id", "package_id", "owner_id"],
            ["reserved_quantity:sum", "id:recordset"],
        )
        reserved_move_lines = self.env["stock.move.line"]._read_group(
            move_line_domain,
            ["product_id", "location_id", "lot_id", "package_id", "owner_id"],
            ["quantity_product_uom:sum"],
        )
        reserved_move_lines = {
            (product, location, lot, package, owner): reserved_quantity
            for product, location, lot, package, owner, reserved_quantity in reserved_move_lines
        }
        for (
            product,
            location,
            lot,
            package,
            owner,
            reserved_quantity,
            quants,
        ) in reserved_quants:
            ml_reserved_qty = reserved_move_lines.get(
                (product, location, lot, package, owner), 0
            )
            if location.should_bypass_reservation():
                quants._update_reserved_quantity(
                    product,
                    location,
                    -reserved_quantity,
                    lot_id=lot,
                    package_id=package,
                    owner_id=owner,
                )
            elif product.uom_id.compare(reserved_quantity, ml_reserved_qty) != 0:
                quants._update_reserved_quantity(
                    product,
                    location,
                    ml_reserved_qty - reserved_quantity,
                    lot_id=lot,
                    package_id=package,
                    owner_id=owner,
                )
            if ml_reserved_qty:
                del reserved_move_lines[(product, location, lot, package, owner)]

        for (
            product,
            location,
            lot,
            package,
            owner,
        ), reserved_quantity in reserved_move_lines.items():
            if location.should_bypass_reservation() or self.env[
                "stock.quant"
            ]._should_bypass_product(
                product, location, reserved_quantity, lot, package, owner
            ):
                continue
            self.env["stock.quant"]._update_reserved_quantity(
                product,
                location,
                reserved_quantity,
                lot_id=lot,
                package_id=package,
                owner_id=owner,
            )

    def _quant_tasks(self):
        self._merge_quants()
        self._clean_reservations()
        self._unlink_zero_quants()

    def _set_view_context(self):
        """Adds context when opening quants related views."""
        if not self.env.user.has_group("stock.group_stock_multi_locations"):
            company_user = self.env.company
            warehouse = self.env["stock.warehouse"].search(
                [("company_id", "=", company_user.id)], limit=1
            )
            if warehouse:
                self = self.with_context(
                    default_location_id=warehouse.lot_stock_id.id,
                    hide_location=not self.env.context.get("always_show_loc", False),
                )

        if self.env.user.has_group("stock.group_stock_user"):
            self = self.with_context(inventory_mode=True)
        return self

    def get_aggregate_barcodes(self):
        """Generates and aggregates quants' barcodes. This method uses the config parameters
        `stock.agg_barcode_max_length` to determine the length limit of a single aggregate barcode
        (400 by default) and `stock.barcode_separator` to determine which character to use to
        separate individual encodings (this method can't work without this parameter and will return
        an empty list.) Depending on the number of quants, those parameters and the length of their
        barcode encodings, there can be one or more aggregate barcodes.

        :return: list
        """
        agg_barcode_max_length = int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("stock.agg_barcode_max_length", 400)
        )
        barcode_separator = (
            self.env["ir.config_parameter"].sudo().get_param("stock.barcode_separator")
        )
        if not barcode_separator:
            return []

        eol_char = "\t"
        aggregate_barcodes = []
        aggregate_barcode = ""

        uom_unit_id = self.env.ref("uom.product_uom_unit").id
        gs1_quantity_rules = self.env["barcode.rule"].search(
            [
                ("associated_uom_id", "!=", False),
                ("associated_uom_id", "!=", uom_unit_id),
                ("is_gs1_nomenclature", "=", True),
            ]
        )
        gs1_quantity_rules_ai_by_uom = {}

        for rule in gs1_quantity_rules:
            decimal = str(
                len(f"{rule.associated_uom_id.rounding:.10f}".rstrip("0").split(".")[1])
            )
            rule_ai = rule.pattern[1:4] + decimal
            gs1_quantity_rules_ai_by_uom[rule.associated_uom_id.id] = rule_ai

        previous_product = self.env["product.product"]
        for quant in self:
            if not quant.product_id.barcode:
                continue
            barcode = ""
            if previous_product != quant.product_id:
                previous_product = quant.product_id
                if not quant.product_id.valid_ean:
                    barcode += quant.product_id.barcode
            quant_gs1_barcode = quant._get_gs1_barcode(gs1_quantity_rules_ai_by_uom)
            if quant_gs1_barcode:
                barcode += (barcode_separator if barcode else "") + quant_gs1_barcode
            elif quant.tracking == "serial":
                barcode += (barcode_separator if barcode else "") + quant.lot_id.name
            if (
                aggregate_barcode
                and len(aggregate_barcode + barcode) > agg_barcode_max_length
            ):
                aggregate_barcodes.append(aggregate_barcode + eol_char)
                aggregate_barcode = ""
            if barcode:
                if aggregate_barcode and not aggregate_barcode.endswith(
                    barcode_separator
                ):
                    aggregate_barcode += barcode_separator
                aggregate_barcode += barcode

        if aggregate_barcode:
            aggregate_barcodes.append(aggregate_barcode + eol_char)

        return aggregate_barcodes

    def _get_available_quantity(
        self,
        product_id,
        location_id,
        lot_id=None,
        package_id=None,
        owner_id=None,
        strict=False,
        allow_negative=False,
    ):
        """Return the available quantity, i.e. the sum of `quantity` minus the sum of
        `reserved_quantity`, for the set of quants sharing the combination of `product_id,
        location_id` if `strict` is set to False or sharing the *exact same characteristics*
        otherwise.
        This method is called in the following usecases:
            - when a stock move checks its availability
            - when a stock move actually assign
            - when editing a move line, to check if the new value is forced or not
            - when validating a move line with some forced values and have to potentially unlink an
              equivalent move line in another picking
        In the two first usecases, `strict` should be set to `False`, as we don't know what exact
        quants we'll reserve, and the characteristics are meaningless in this context.
        In the last ones, `strict` should be set to `True`, as we work on a specific set of
        characteristics.

        Always resolves the candidate set with a fresh ``_gather``. A caller that just
        gathered the same characteristics reuses them via :meth:`_sum_available_quantity`
        instead of passing them here -- keeping this method's signature stable for the
        sibling-repo overrides that extend it (see :meth:`_gather`).

        :return: available quantity as a float
        """
        quants = self.sudo()._gather(
            product_id,
            location_id,
            lot_id=lot_id,
            package_id=package_id,
            owner_id=owner_id,
            strict=strict,
        )
        return self._sum_available_quantity(
            quants,
            product_id,
            lot_id=lot_id,
            strict=strict,
            allow_negative=allow_negative,
        )

    def _get_on_hand_shortfall(
        self, product_id, location_id, lot_id, package_id=None, owner_id=None
    ):
        """How far below zero the *on-hand* of ``lot_id``'s quants has gone, as a
        positive number (0.0 when non-negative).

        Deliberately not derived from availability: ``_get_available_quantity`` and
        ``_update_available_quantity`` both report on-hand *minus reserved*, which is
        negative for a merely fully-reserved quant that holds plenty of stock. Callers
        repairing a negative on-hand need the on-hand, so they ask for it here.

        The strict gather matches ``lot_id IN (False, lot)``, so the untracked rows are
        excluded explicitly -- they are the source the repair draws *from*.
        """
        quants = self.sudo()._gather(
            product_id,
            location_id,
            lot_id=lot_id,
            package_id=package_id,
            owner_id=owner_id,
            strict=True,
        )
        on_hand = sum(
            quant.quantity
            for quant in quants
            if quant.lot_id and quant.lot_id == lot_id
        )
        return -on_hand if product_id.uom_id.compare(on_hand, 0) < 0 else 0.0

    def _sum_available_quantity(
        self, quants, product_id, lot_id=None, strict=False, allow_negative=False
    ):
        """Sum on-hand-minus-reserved over an already-``_gather``-ed ``quants`` set.

        Split out of :meth:`_get_available_quantity` so :meth:`_get_reserve_quantity`
        can reuse the recordset it just gathered without a second identical search --
        *without* threading that recordset through ``_get_available_quantity``, which is
        an extension point overridden in sibling repos. Only reuse ``quants`` when it is
        the *full* gather for these characteristics: a ``least_packages`` gather is
        narrowed to the chosen packages and would under-report availability, so its
        caller re-gathers instead.
        """
        quants = quants.sudo()
        ledger = self.env.context.get("reservation_ledger")
        if product_id.tracking == "none":
            available_quantity = sum(quants.mapped("quantity")) - sum(
                quants.mapped("reserved_quantity")
            )
            if ledger is not None:
                available_quantity -= sum(ledger.pending(quant) for quant in quants)
            if allow_negative:
                return available_quantity
            return (
                available_quantity
                if product_id.uom_id.compare(available_quantity, 0.0) >= 0.0
                else 0.0
            )
        available_quantities = dict.fromkeys(set(quants.mapped("lot_id")), 0.0)
        available_quantities[None] = 0.0
        for quant in quants:
            if not quant.lot_id and strict and lot_id:
                continue
            available_quantities[quant.lot_id or None] += (
                quant.quantity
                - quant.reserved_quantity
                - (ledger.pending(quant) if ledger is not None else 0.0)
            )
        if allow_negative:
            return sum(available_quantities.values())
        return sum(
            available_quantity
            for available_quantity in available_quantities.values()
            if product_id.uom_id.compare(available_quantity, 0) > 0
        )

    def _get_gather_domain(
        self,
        product,
        location,
        lot=None,
        package=None,
        owner=None,
        strict=False,
    ):
        domains = [Domain("product_id", "=", product.id)]
        if not strict:
            if lot:
                domains.append(Domain("lot_id", "in", [lot.id, False]))
            if package:
                domains.append(Domain("package_id", "=", package.id))
            if owner:
                domains.append(Domain("owner_id", "=", owner.id))
            domains.append(Domain("location_id", "child_of", location.id))
        else:
            domains.extend(
                (
                    Domain("lot_id", "in", [False, lot.id if lot else False]),
                    Domain("package_id", "=", package.id if package else False),
                    Domain("owner_id", "=", owner.id if owner else False),
                    Domain("location_id", "=", location.id),
                ),
            )
        if self.env.context.get("with_expiration"):
            domains.append(
                Domain("removal_date", ">=", self.env.context["with_expiration"])
                | Domain("removal_date", "=", False),
            )
        return Domain.AND(domains)

    def _reservation_key(self):
        """The tuple of characteristics that identifies interchangeable quants for
        reservation (everything but product/quantity). Shared so callers group quants
        consistently instead of re-spelling the tuple.
        """
        self.ensure_one()
        return (self.location_id, self.lot_id, self.package_id, self.owner_id)

    def _get_gs1_barcode(self, gs1_quantity_rules_ai_by_uom=False):
        """Generates a GS1 barcode for the quant's properties (product, quantity and LN/SN.)

        :param gs1_quantity_rules_ai_by_uom: contains the products' GS1 AI paired with the UoM id
        :type gs1_quantity_rules_ai_by_uom: dict
        :return: str
        """
        self.ensure_one()
        gs1_quantity_rules_ai_by_uom = gs1_quantity_rules_ai_by_uom or {}
        barcode = ""

        if self.product_id.valid_ean:
            barcode = self.product_id.barcode
            barcode = "01" + "0" * (14 - len(barcode)) + barcode
        elif self.tracking == "none" or not self.lot_id:
            return ""

        if (
            self.tracking != "serial"
            or self.product_uom_id.compare(self.quantity, 1) > 0
        ):
            quantity_ai = gs1_quantity_rules_ai_by_uom.get(self.product_uom_id.id)
            if quantity_ai:
                # round(), not int(): `quantity / rounding` is a float division that
                # lands just under the integer for ordinary values, and truncating it
                # encodes one decimal step too little -- 0.29 kg went out as 0.28,
                # 1.16 as 1.15. The no-AI branch below already rounds.
                qty_str = str(round(self.quantity / self.product_uom_id.rounding))
                if len(qty_str) <= 6:
                    barcode += quantity_ai + "0" * (6 - len(qty_str)) + qty_str
            else:
                qty_str = str(round(self.quantity))
                if len(qty_str) <= 8:
                    barcode += "30" + "0" * (8 - len(qty_str)) + qty_str

        if self.lot_id:
            if len(self.lot_id.name) > 20:
                return ""
            tracking_ai = "21" if self.tracking == "serial" else "10"
            barcode += tracking_ai + self.lot_id.name
        return barcode

    @api.model
    def _get_inventory_fields_create(self):
        """Returns a list of fields user can edit when he want to create a quant in `inventory_mode`."""
        return ["product_id", "owner_id"] + self._get_inventory_fields_countable()

    @api.model
    def _get_inventory_fields_countable(self):
        """The count-related fields an inventory-mode ``create`` may carry.

        Named for what it is. It used to be ``_get_inventory_fields_write``, which
        `write()` never consulted -- that path gates on the *deny*-list
        ``_get_forbidden_fields_write`` instead, so this list's only consumer is
        ``_get_inventory_fields_create`` above. Modules extending it (stock_account's
        ``accounting_date``, stock_barcode's ``dummy_id``) were widening a write
        allowlist that does not exist; under the deny-list those fields were never
        blocked on write in the first place.

        Note ``lot_id``/``location_id``/``package_id`` are also in the deny-list, so
        they are writable only at creation time -- which is exactly what this list is
        for.
        """
        return [
            "inventory_quantity",
            "inventory_quantity_auto_apply",
            "inventory_diff_quantity",
            "inventory_date",
            "user_id",
            "inventory_quantity_set",
            "is_outdated",
            "lot_id",
            "location_id",
            "package_id",
        ]

    def _get_inventory_move_values(
        self,
        qty,
        location_id,
        location_dest_id,
        package_id=False,
        package_dest_id=False,
    ):
        """Called when user manually set a new quantity (via `inventory_quantity`)
        just before creating the corresponding stock move.

        :param location_id: `stock.location`
        :param location_dest_id: `stock.location`
        :param package_id: `stock.package`
        :param package_dest_id: `stock.package`
        :return: dict with all values needed to create a new `stock.move` with its move line.
        """
        self.ensure_one()

        res = {
            "product_id": self.product_id.id,
            "product_uom_id": self.product_uom_id.id,
            "product_uom_qty": qty,
            "company_id": self.company_id.id or self.env.company.id,
            "state": "confirmed",
            "location_id": location_id.id,
            "location_dest_id": location_dest_id.id,
            "restrict_partner_id": self.owner_id.id,
            "is_inventory": True,
            "picked": True,
            "move_line_ids": [
                (
                    0,
                    0,
                    {
                        "product_id": self.product_id.id,
                        "product_uom_id": self.product_uom_id.id,
                        "quantity": qty,
                        "location_id": location_id.id,
                        "location_dest_id": location_dest_id.id,
                        "company_id": self.company_id.id or self.env.company.id,
                        "lot_id": self.lot_id.id,
                        "package_id": package_id.id if package_id else False,
                        "result_package_id": (
                            package_dest_id.id if package_dest_id else False
                        ),
                        "owner_id": self.owner_id.id,
                    },
                )
            ],
        }
        if self.env.context.get("inventory_name"):
            res["inventory_name"] = self.env.context.get("inventory_name")

        return res

    @api.model
    def _get_quants_action(self, extend=False):
        """Returns an action to open (non-inventory adjustment) quant view.
        Depending of the context (user have right to be inventory mode or not),
        the list view will be editable or readonly.

        :param extend: If True, enables form, graph and pivot views. False by default.
        """
        if (
            not self.env["ir.config_parameter"]
            .sudo()
            .get_param("stock.skip_quant_tasks")
        ):
            self._quant_tasks()
        ctx = dict(self.env.context or {})
        ctx["inventory_report_mode"] = True
        ctx.pop("group_by", None)

        action = self.env["ir.actions.act_window"]._for_xml_id(
            "stock.stock_quant_action"
        )
        action["domain"] = [
            (
                "product_id.company_id",
                "in",
                ctx.get("allowed_company_ids", []) + [False],
            )
        ]

        form_view = self.env.ref("stock.view_stock_quant_form_editable").id
        if self.env.context.get("inventory_mode") and self.env.user.has_group(
            "stock.group_stock_manager"
        ):
            action["view_id"] = self.env.ref("stock.view_stock_quant_list_editable").id
        else:
            action["view_id"] = self.env.ref("stock.view_stock_quant_list").id
        action.update(
            {
                "views": [
                    (action["view_id"], "list"),
                    (form_view, "form"),
                ],
                "context": ctx,
            }
        )
        if extend:
            action.update(
                {
                    "view_mode": "list,form,pivot,graph",
                    "views": [
                        (action["view_id"], "list"),
                        (form_view, "form"),
                        (self.env.ref("stock.view_stock_quant_pivot").id, "pivot"),
                        (self.env.ref("stock.stock_quant_view_graph").id, "graph"),
                    ],
                }
            )
        action["path"] = "stock-locations"
        return action

    def _get_quants_by_products_locations(
        self, product_ids, location_ids, extra_domain=False, lot_scope=None
    ):
        res = _QuantsCache(
            self.env["stock.quant"],
            product_ids.ids,
            location_ids.mapped("parent_path"),
            lot_scope=lot_scope.ids if lot_scope is not None else None,
        )
        if product_ids and location_ids:
            domain = Domain(
                [
                    ("product_id", "in", product_ids.ids),
                    ("location_id", "child_of", location_ids.ids),
                ]
            )
            if lot_scope is not None:
                domain &= Domain(
                    ["|", ("lot_id", "in", lot_scope.ids), ("lot_id", "=", False)]
                )
            if extra_domain:
                domain &= Domain(extra_domain)
            needed_quants = self.env["stock.quant"]._read_group(
                domain,
                ["product_id", "location_id", "lot_id", "package_id", "owner_id"],
                ["id:recordset"],
                order="lot_id",
            )
            quant_ids = []
            for product, loc, lot, package, owner, quants in needed_quants:
                res[product.id, loc.id, lot.id, package.id, owner.id] = quants
                quant_ids.extend(quants.ids)
            self.env["stock.quant"].browse(quant_ids).fetch(
                [
                    "quantity",
                    "reserved_quantity",
                    "in_date",
                    "product_id",
                    "location_id",
                    "lot_id",
                    "package_id",
                    "owner_id",
                ]
            )
        return res

    @api.model
    def _get_removal_strategy(self, product_id, location_id):
        product_id = product_id.sudo()
        if product_id.categ_id.removal_strategy_id:
            return product_id.categ_id.removal_strategy_id.with_context(
                lang=None
            ).method
        location_id = location_id.sudo()
        if location_id.parent_path:
            ancestor_ids = [int(i) for i in location_id.parent_path.split("/") if i]
            for loc in self.env["stock.location"].browse(ancestor_ids[::-1]):
                if loc.removal_strategy_id:
                    return loc.removal_strategy_id.with_context(lang=None).method
        else:
            loc = location_id
            while loc:
                if loc.removal_strategy_id:
                    return loc.removal_strategy_id.with_context(lang=None).method
                loc = loc.location_id
        return "fifo"

    @api.model
    def _get_removal_strategy_order(self, removal_strategy):
        if removal_strategy in ["fifo", "least_packages"]:
            return "in_date ASC, id"
        elif removal_strategy == "lifo":
            return "in_date DESC, id DESC"
        elif removal_strategy == "closest":
            return False
        raise UserError(_("Removal strategy %s not implemented.", removal_strategy))

    @api.model
    def _get_removal_strategy_sort_key(self, removal_strategy):
        """Python equivalent of :meth:`_get_removal_strategy_order` for the
        ``_gather`` quants-cache fast path.

        Returns ``(key, reverse)`` for :meth:`recordset.sorted` when the strategy's
        SQL ordering can be replicated in Python, or ``None`` when it cannot --
        ``_gather`` then bypasses the cache and searches, so cache and search paths
        always return quants in the same order. Modules adding removal strategies
        (i.e. overriding :meth:`_get_removal_strategy_order`) should override this
        hook symmetrically; leaving it alone is safe (their strategies simply skip
        the cache fast path).
        """
        if removal_strategy in ("fifo", "least_packages"):
            return (lambda q: (q.in_date, q.id)), False
        if removal_strategy == "lifo":
            return (lambda q: (q.in_date, q.id)), True
        if removal_strategy == "closest":
            return (lambda q: q.id), False
        return None

    def _get_reserve_quantity(
        self,
        product_id,
        location_id,
        quantity,
        uom_id=None,
        lot_id=None,
        package_id=None,
        owner_id=None,
        strict=False,
    ):
        """Get the quantity available to reserve for the set of quants
        sharing the combination of `product_id, location_id` if `strict` is set to False or sharing
        the *exact same characteristics* otherwise. `self` is never consulted: the
        candidate set is always resolved from scratch by `_gather` (see its docstring).
        Typically, this method is called before the `stock.move.line` creation to know the reserved_qty that could be used.
        It's also called by `stock.move._update_reserved_quantity_vals` to find the quants to reserve.

        :return: a list of tuples (quant, quantity_reserved) showing on which quant the reservation
            could be done and how much the system is able to reserve on it
        """
        self = self.sudo()

        removal_strategy = self._get_removal_strategy(product_id, location_id)
        self = self.with_context(_gather_removal_strategy=removal_strategy)
        quants = self._gather(
            product_id,
            location_id,
            lot_id=lot_id,
            package_id=package_id,
            owner_id=owner_id,
            strict=strict,
            qty=quantity,
        )

        if removal_strategy == "least_packages":
            available_quantity = self._get_available_quantity(
                product_id,
                location_id,
                lot_id=lot_id,
                package_id=package_id,
                owner_id=owner_id,
                strict=strict,
            )
        else:
            available_quantity = self._sum_available_quantity(
                quants, product_id, lot_id=lot_id, strict=strict, allow_negative=False
            )

        if (
            self.env.context.get("packaging_uom_id")
            and product_id.product_tmpl_id.categ_id.packaging_reserve_method == "full"
        ):
            available_quantity = self.env.context.get(
                "packaging_uom_id"
            )._round_to_packaging_multiple(
                min(quantity, available_quantity), product_id.uom_id, "DOWN"
            )

        quantity = min(quantity, available_quantity)

        if not strict and uom_id and product_id.uom_id != uom_id:
            quantity_move_uom = product_id.uom_id._compute_quantity(
                quantity, uom_id, rounding_method="DOWN"
            )
            quantity = uom_id._compute_quantity(
                quantity_move_uom, product_id.uom_id, rounding_method="HALF-UP"
            )

        if product_id.tracking == "serial":
            if product_id.uom_id.compare(quantity, int(quantity)) != 0:
                quantity = 0

        if product_id.uom_id.compare(quantity, 0) <= 0:
            return []

        precision_digits = self.env["decimal.precision"].precision_get("Product Unit")
        ledger = self.env.context.get("reservation_ledger")
        candidates = [
            _ReservationCandidate(
                quant,
                quant.quantity,
                quant.reserved_quantity
                + (ledger.pending(quant) if ledger is not None else 0.0),
                quant._reservation_key(),
            )
            for quant in quants
        ]
        reserved = _distribute_reservation(candidates, quantity, precision_digits)
        if reserved and _logger.isEnabledFor(logging.DEBUG):
            _logger.debug(
                "reserve product=%s location=%s asked=%s -> %s",
                product_id.id,
                location_id.id,
                quantity,
                [(quant.id, qty) for quant, qty in reserved],
            )
        return reserved

    @api.model
    def _merge_quants(self):
        """In a situation where one transaction is updating a quant via
        `_update_available_quantity` and another concurrent one calls this function with the same
        argument, we'll create a new quant in order for these transactions to not rollback. This
        method will find and deduplicate these quants.
        """
        params = []
        query = """WITH
                        dupes AS (
                            SELECT min(id) as to_update_quant_id,
                                (array_agg(id ORDER BY id))[2:array_length(array_agg(id), 1)] as to_delete_quant_ids,
                                GREATEST(0, SUM(reserved_quantity)) as reserved_quantity,
                                SUM(inventory_quantity) as inventory_quantity,
                                SUM(quantity) as quantity,
                                MIN(in_date) as in_date
                            FROM stock_quant
        """
        if self._ids:
            query += """
                            WHERE
                                location_id = ANY(%s)
                                AND product_id = ANY(%s)
            """
            params = [list(self.location_id.ids), list(self.product_id.ids)]
        query += """
                            GROUP BY product_id, company_id, location_id, lot_id, package_id, owner_id
                            HAVING count(id) > 1
                        ),
                        -- _up is never referenced below, but PostgreSQL always executes
                        -- data-modifying WITH clauses exactly once, so this UPDATE runs.
                        _up AS (
                            UPDATE stock_quant q
                                SET quantity = d.quantity,
                                    reserved_quantity = d.reserved_quantity,
                                    inventory_quantity = d.inventory_quantity,
                                    in_date = d.in_date
                            FROM dupes d
                            WHERE d.to_update_quant_id = q.id
                        )
                   DELETE FROM stock_quant WHERE id in (SELECT unnest(to_delete_quant_ids) from dupes)
        """
        try:
            # `savepoint()` flushes (flush=True is its default), and that is
            # load-bearing here, not incidental: the raw statement below sums the
            # columns straight off the table, so an ORM write still buffered would be
            # left out of the merged total and then flushed back over it. Never pass
            # `flush=False`.
            with self.env.cr.savepoint():
                self.env.cr.execute(query, params)
                self.env.invalidate_all()
        except Error as e:
            _logger.warning("an error occurred while merging quants: %s", e)

    def move_quants(
        self,
        location_dest_id=False,
        package_dest_id=False,
        message=False,
        unpack=False,
        up_to_parent_packages=False,
    ):
        """Directly move a stock.quant to another location and/or package by creating a stock.move.

        :param location_dest_id: `stock.location` destination location for the quants
        :param package_dest_id: `stock.package` destination package for the quants
        :param message: String to fill the reference field on the generated stock.move
        :param unpack: set to True when needing to unpack the quant
        :param up_to_parent_packages: `stock.package` that are the upper limit to keep the parents
        """

        def set_parent_package(all_quants, package, limit_ids):
            if not package.parent_package_id or (limit_ids and package.id in limit_ids):
                return None
            if any(
                quant not in all_quants
                for quant in package.parent_package_id.contained_quant_ids
            ):
                return None
            package.package_dest_id = package.parent_package_id
            return set_parent_package(all_quants, package.parent_package_id, limit_ids)

        message = message or _("Quantity Relocated")
        move_vals = []
        limit_ids = set(up_to_parent_packages.ids if up_to_parent_packages else [])
        for quant in self:
            result_package_id = package_dest_id
            if not unpack and not package_dest_id:
                result_package_id = quant.package_id
                set_parent_package(self, result_package_id, limit_ids)
            move_vals.append(
                quant.with_context(inventory_name=message)._get_inventory_move_values(
                    quant.quantity,
                    quant.location_id,
                    location_dest_id or quant.location_id,
                    quant.package_id,
                    result_package_id,
                )
            )
        moves = self.env["stock.move"].create(move_vals)
        moves._action_done()

    def check_quantity(self):
        """Ensure no serial number is present more than once at a given location."""
        sn_quants = self.filtered(
            lambda q: (
                q.product_id.tracking == "serial"
                and q.location_id.usage != "inventory"
                and q.lot_id
            )
        )
        if not sn_quants:
            return
        domain = [
            ("product_id", "in", sn_quants.product_id.ids),
            ("location_id", "child_of", sn_quants.location_id.ids),
            ("lot_id", "in", sn_quants.lot_id.ids),
        ]
        groups = self._read_group(
            domain,
            ["product_id", "location_id", "lot_id"],
            ["quantity:sum"],
        )
        for product, _location, lot, qty in groups:
            # `abs`: more than one unit of a serial at one location is broken either
            # way, but the two directions are different faults and the "already
            # assigned" wording only fits the positive one. A single negative unit
            # stays legal -- that is an ordinary delivery-before-receipt.
            if product.uom_id.compare(abs(qty), 1) <= 0:
                continue
            if product.uom_id.compare(qty, 0) > 0:
                raise ValidationError(
                    _(
                        "The serial number has already been assigned: \n Product: %(product)s, Serial Number: %(serial_number)s",
                        product=product.display_name,
                        serial_number=lot.name,
                    )
                )
            raise ValidationError(
                _(
                    "This serial number is at a negative quantity, so it has been"
                    " taken out more times than it was brought in: \n Product:"
                    " %(product)s, Serial Number: %(serial_number)s",
                    product=product.display_name,
                    serial_number=lot.name,
                )
            )

    @api.model
    def _check_serial_number(
        self,
        product_id,
        lot_id,
        company_id,
        source_location_id=None,
        ref_doc_location_id=None,
    ):
        """Checks for duplicate serial numbers (SN) when assigning a SN (i.e. no source_location_id)
        and checks for potential incorrect location selection of a SN when using a SN (i.e.
        source_location_id). Returns warning message of all locations the SN is located at and
        (optionally) a recommended source location of the SN (when using SN from incorrect location).
        This function is designed to be used by onchange functions across differing situations including,
        but not limited to scrap, incoming picking SN encoding, and outgoing picking SN selection.

        :param product_id: `product.product` product to check SN for
        :param lot_id: `stock.lot` SN to check
        :param company_id: `res.company` company to check against (i.e. we ignore duplicate SNs across
            different companies for lots defined with a company)
        :param source_location_id: `stock.location` optional source location if using the SN rather
            than assigning it
        :param ref_doc_location_id: `stock.location` optional reference document location for
            determining recommended location. This is param expected to only be used when a
            `source_location_id` is provided.
        :return: tuple(message, recommended_location) If not None, message is a string expected to be
            used in warning message dict and recommended_location is a `location_id`
        """
        message = None
        recommended_location = None
        if product_id.tracking == "serial":
            internal_domain = Domain("location_id.usage", "in", ("internal", "transit"))
            if lot_id.company_id:
                internal_domain &= Domain("company_id", "=", company_id.id)
            quants = self.env["stock.quant"].search(
                Domain.AND(
                    (
                        Domain("product_id", "=", product_id.id),
                        Domain("lot_id", "in", lot_id.ids),
                        Domain("quantity", "!=", 0),
                        Domain("location_id.usage", "=", "customer") | internal_domain,
                    ),
                ),
            )
            sn_locations = quants.mapped("location_id")
            if quants:
                if not source_location_id:
                    message = _(
                        "The Serial Number (%(serial_number)s) is already used in location(s): %(location_list)s.\n\n"
                        "Is this expected? For example, this can occur if a delivery operation is validated "
                        "before its corresponding receipt operation is validated. In this case the issue will be solved "
                        "automatically once all steps are completed. Otherwise, the serial number should be corrected to "
                        "prevent inconsistent data.",
                        serial_number=lot_id.name,
                        location_list=sn_locations.mapped("display_name"),
                    )

                elif source_location_id and source_location_id not in sn_locations:
                    recommended_location = self.env["stock.location"]
                    if ref_doc_location_id:
                        for location in sn_locations:
                            if location._child_of(ref_doc_location_id):
                                recommended_location = location
                                break
                    else:
                        for location in sn_locations:
                            if location.usage != "customer":
                                recommended_location = location
                                break
                    if (
                        recommended_location
                        and recommended_location.company_id == company_id
                    ):
                        message = _(
                            "Serial number (%(serial_number)s) is not located in %(source_location)s, but is located in location(s): %(other_locations)s.\n\n"
                            "Source location for this move will be changed to %(recommended_location)s",
                            serial_number=lot_id.name,
                            source_location=source_location_id.display_name,
                            other_locations=sn_locations.mapped("display_name"),
                            recommended_location=recommended_location.display_name,
                        )
                    else:
                        message = _(
                            "Serial number (%(serial_number)s) is not located in %(source_location)s, but is located in location(s): %(other_locations)s.\n\n"
                            "Please correct this to prevent inconsistent data.",
                            serial_number=lot_id.name,
                            source_location=source_location_id.display_name,
                            other_locations=sn_locations.mapped("display_name"),
                        )
                        recommended_location = None
        return message, recommended_location

    @api.model
    def _is_inventory_mode(self):
        """Used to control whether a quant was written on or created during an
        "inventory session", meaning a mode where we need to create the stock.move
        record necessary to be consistent with the `inventory_quantity` field.
        """
        return self.env.context.get("inventory_mode") and self.env.user.has_group(
            "stock.group_stock_user"
        )

    def _is_outdated(self):
        """A quant is outdated when a counted quantity has been set and the on-hand
        quantity has since drifted away from it. Single source of truth shared by
        _compute_is_outdated and _search_is_outdated.
        """
        self.ensure_one()
        return bool(
            self.inventory_quantity_set
            and self.product_id
            and self.product_uom_id.compare(
                self.inventory_quantity - self.inventory_diff_quantity, self.quantity
            )
        )

    def _should_bypass_product(
        self,
        product=False,
        location=False,
        reserved_quantity=0,
        lot_id=False,
        package_id=False,
        owner_id=False,
    ):
        """Hook for other modules to skip reservation clean-up for specific products."""
        return False

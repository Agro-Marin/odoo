import heapq
import logging
from ast import literal_eval
from collections import defaultdict, namedtuple

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


# Search node: remaining quantity to cover, the packages taken so far, and the
# index of the next candidate package to consider.
_LeastPackagesNode = namedtuple(
    "_LeastPackagesNode", "count_remaining taken_packages next_index"
)


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

        # Generate only one branch per distinct amount (the list is grouped by
        # amount).
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
                # Overselect case: keep the fewest-package / tightest leaf.
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
                # Not enough packages case: keep the closest leaf.
                if node.count_remaining < best_leaf.count_remaining:
                    best_leaf = node
                continue

            frontier.put(node, heuristic(node))

    # No exact matching possible, use best leaf.
    return best_leaf.taken_packages


# Reservation candidate: opaque handle returned to the caller (a stock.quant in
# production), its on-hand and reserved quantities, and the characteristics key
# grouping interchangeable candidates for over-reservation absorption.
_ReservationCandidate = namedtuple(
    "_ReservationCandidate", "handle on_hand reserved key"
)


def _distribute_reservation(candidates, quantity, available_quantity, precision_digits):
    """Distribute a signed ``quantity`` across pre-ordered reservation ``candidates``.

    Pure and DB-free (like :func:`_least_packages_search`): operates on plain numbers
    and opaque ``handle`` values only, so this allocation arithmetic -- the trickiest
    in the model -- is unit-testable with hand-built inputs.

    :param candidates: list of :class:`_ReservationCandidate` already ordered by the
        removal strategy. ``handle`` is echoed back verbatim; ``key`` groups
        interchangeable candidates so stock already over-reserved into negative
        available is absorbed first, before the rest of that group over-reserves too.
    :param quantity: signed target in the candidates' UoM -- ``> 0`` reserves,
        ``< 0`` unreserves. Its sign is fixed for the run: reserving never takes more
        than is left, so it converges to zero without crossing it.
    :param available_quantity: running budget the reserve branch draws down;
        allocation stops once it or ``quantity`` rounds to zero. The caller sizes it
        (positive branch: on-hand-minus-reserved of the whole set; negative branch:
        total reserved), so the loop needs no global view.
    :param precision_digits: 'Product Unit' decimal precision; every comparison rounds
        to it, matching ``uom.compare`` / ``uom.is_zero``.
    :return: list of ``(handle, amount)`` pairs -- ``amount`` positive when reserving,
        negative when unreserving.
    """
    reserved = []
    if float_is_zero(quantity, precision_digits=precision_digits):
        return reserved
    reserving = float_compare(quantity, 0, precision_digits=precision_digits) > 0

    # Group already-over-reserved (negative available) quantity by characteristics
    # so it is absorbed first, not spread as more over-reservation in the group.
    negative_available = defaultdict(float)
    for cand in candidates:
        slack = cand.on_hand - cand.reserved
        if float_compare(slack, 0, precision_digits=precision_digits) < 0:
            negative_available[cand.key] += slack

    for cand in candidates:
        if reserving:
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
            available_quantity -= max_on_cand
        else:
            max_on_cand = min(cand.reserved, abs(quantity))
            reserved.append((cand.handle, -max_on_cand))
            quantity += max_on_cand
            available_quantity += max_on_cand

        if float_is_zero(quantity, precision_digits=precision_digits) or float_is_zero(
            available_quantity, precision_digits=precision_digits
        ):
            break
    return reserved


class StockQuant(models.Model):
    _name = "stock.quant"
    _description = "Quants"
    _rec_name = "product_id"
    _rec_names_search = ["location_id", "lot_id", "package_id", "owner_id"]

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

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
        # No standalone index: product_id is the leading column of both
        # _product_location_idx and _quant_merge_idx below, so a dedicated
        # single-column btree is pure write overhead on this hot table.
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

    # Inventory Fields
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

    # ------------------------------------------------------------
    # INDEXES
    # ------------------------------------------------------------

    # Composite index for _gather() queries:
    # WHERE product_id=? AND location_id=? (strict) or location_id child_of (non-strict)
    _product_location_idx = models.Index("(product_id, location_id)")

    # Composite index for _merge_quants() GROUP BY and _get_quants_by_products_locations() _read_group.
    # Column order matches the common _read_group groupby: product, location, lot, package, owner.
    # company_id is last since _read_group calls don't include it in their groupby.
    _quant_merge_idx = models.Index(
        "(product_id, location_id, lot_id, package_id, owner_id, company_id)"
    )

    def init(self):
        super().init()
        # product_id dropped its standalone `index=True` (it leads both composite
        # indexes above, so a single-column btree is pure write overhead here).
        # `_auto_init` no longer creates it, but the ORM never drops indexes it once
        # made, so remove the now-orphan index here. Idempotent, and runs after
        # `_auto_init` so it won't be recreated underneath us.
        self.env.cr.execute("DROP INDEX IF EXISTS stock_quant__product_id_index")

    # ------------------------------------------------------------
    # CONSTRAINT METHODS
    # ------------------------------------------------------------

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

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

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
        # `results[i]` holds the quant for `vals_list[i]`, preserving order. Inventory-
        # mode rows are handled one at a time (each gathers/merges against existing
        # quants); other rows are deferred to one batched super().create() so
        # @api.model_create_multi issues a single INSERT instead of N.
        #
        # Inventory-mode rows resolve to an *existing* quant when one matches, so two
        # vals with the same characteristics can map to the same record and the result
        # is then shorter than `vals_list`. That coalescing is intended (one physical
        # quant per characteristics tuple) -- callers must not positionally zip the
        # result against the input.
        results = [self.env["stock.quant"]] * len(vals_list)
        plain_vals = []  # list of (index, vals) for the batched, non-inventory create
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
                # stock.quant omits `_check_company_auto`, so the ORM never auto-runs
                # `_check_company` on create/write (unlike stock.lot, stock.location).
                # The engine path is trusted (company_id is a stored related off
                # location_id), so this explicit call on the user-input (inventory)
                # path is the *only* company consistency check.
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
        # Decide the mode by which *key* is present, not by truthiness: a counted
        # quantity of 0 is a valid value, and passing both keys must not let one
        # field's value leak into the other.
        if "inventory_quantity_auto_apply" in vals:
            auto_apply = True
            inventory_quantity = vals.pop("inventory_quantity_auto_apply") or 0
            vals.pop("inventory_quantity", None)
        else:
            auto_apply = False
            inventory_quantity = vals.pop("inventory_quantity", False) or 0
        # Create an empty quant or write on a similar one.
        product = self.env["product.product"].browse(vals["product_id"])
        location = self.env["stock.location"].browse(vals["location_id"])
        lot_id = self.env["stock.lot"].browse(vals.get("lot_id"))
        package_id = self.env["stock.package"].browse(vals.get("package_id"))
        owner_id = self.env["res.partner"].browse(vals.get("owner_id"))
        quant = self.env["stock.quant"]
        if not self.env.context.get("import_file"):
            # Merge quants later, to make sure one line = one record during batch import
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
            # Set the `inventory_quantity` field to create the necessary move.
            quant.inventory_quantity = inventory_quantity
            quant.user_id = vals.get("user_id", self.env.user.id)
            quant.inventory_date = fields.Date.today()
        return quant, created

    def write(self, vals):
        """Override to handle the "inventory mode" and create the inventory move."""
        forbidden_fields = self._get_forbidden_fields_write()
        if self._is_inventory_mode() and any(
            field for field in forbidden_fields if field in vals
        ):
            # Quants in an inventory-adjustment location can't be meaningfully edited,
            # so a forbidden write on them is silently ignored (returning True honours
            # write()'s contract: a no-op still "succeeded"). Don't extend that leniency
            # to a mixed recordset: if a real quant is also being written the operation
            # is restricted, and swallowing it would drop the caller's change. So
            # partition on the location's usage rather than gate on `any(...)`.
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

    # ------------------------------------------------------------
    # DEFAULT METHODS
    # ------------------------------------------------------------

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

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

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
        quants._assign_next_inventory_date()

    def _compute_last_count_date(self):
        """We look at the stock move lines associated with every quant to get the last count date."""
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

        # A move line can be the "last count" for a quant on either end of the move
        # (source/dest location) reached through either package slot (package/result
        # package): the 2x2 cross product below is those four (location, package)
        # tuples. Keep the newest date per tuple.
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
        # The read_group already detects duplicates globally; only flag the records in
        # self. Searching for (and assigning to) quants outside self both wastes a query
        # and writes a computed value onto records the ORM never asked us to compute.
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

    # ------------------------------------------------------------
    # INVERSE METHODS
    # ------------------------------------------------------------

    def _inverse_inventory_quantity(self):
        """Inverse method to create stock move when `inventory_quantity` is set
        (`inventory_quantity` is only accessible in inventory mode).
        """
        if not self._is_inventory_mode():
            return
        quant_to_inventory = self.env["stock.quant"]
        for quant in self:
            if quant.quantity == quant.inventory_quantity_auto_apply:
                continue
            quant.inventory_quantity = quant.inventory_quantity_auto_apply
            quant_to_inventory |= quant
        quant_to_inventory.action_apply_inventory()

    # ------------------------------------------------------------
    # SEARCH METHODS
    # ------------------------------------------------------------

    def _search(self, domain, *args, **kwargs):
        # lot_properties only exists on stock.lot; redirect searches through lot_id.
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
        quant_ids = (
            self.search([("inventory_quantity_set", "=", True)])
            .filtered(lambda quant: quant._is_outdated())
            .ids
        )
        return [("id", "in", quant_ids)]

    def _search_on_hand(self, operator, value):
        """Handle the "on_hand" filter, indirectly calling `_get_domain_locations`."""
        if operator != "in":
            return NotImplemented
        return self.env["product.product"]._get_domain_locations()[0]

    # ------------------------------------------------------------
    # ONCHANGE METHODS
    # ------------------------------------------------------------

    @api.onchange("location_id", "product_id", "lot_id", "package_id", "owner_id")
    def _onchange_location_or_product_id(self):
        vals = {}

        # Once the new line is complete, fetch the new theoretical values.
        if self.product_id and self.location_id:
            # Clear the lot if it doesn't apply to (or match) the selected product.
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

            # Special case: directly set the quantity to one for serial numbers,
            # it'll trigger `inventory_quantity` compute.
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

    # ------------------------------------------------------------
    # ACTION METHODS
    # ------------------------------------------------------------

    def action_view_stock_moves(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "stock.stock_move_line_action"
        )
        # Move lines that touched this location on either end, filtered to this quant's
        # lot. For an untracked quant ``lot_id.id`` is False, correctly matching the
        # lot-less move lines of an untracked product. Built with Domain operators so
        # the (source-or-dest) grouping is explicit, not reliant on prefix precedence.
        domain = (
            Domain("location_id", "=", self.location_id.id)
            | Domain("location_dest_id", "=", self.location_id.id)
        ) & Domain("lot_id", "=", self.lot_id.id)
        if self.package_id:
            domain &= Domain("package_id", "=", self.package_id.id) | Domain(
                "result_package_id", "=", self.package_id.id
            )
        action["domain"] = domain
        action["context"] = literal_eval(action.get("context"))
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
        # env.context isn't reliably passed to the wizard for multi-record actions,
        # so pass the quant ids explicitly.
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
        self._apply_inventory(date)
        self.inventory_quantity_set = False
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
        # The list-view button passes the current filter as `active_domain`. If the
        # action is reached without it, fall back to the records in self rather than
        # raising KeyError (or, worse, searching an empty domain = every quant).
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

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    def _assign_next_inventory_date(self):
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
        # Quants can't be quick-created (e.g. from a many2one dropdown).
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
            # Not meaningful in report mode: hide it instead of aggregating.
            return SQL("NULL")
        if aggregate_spec == "available_quantity:sum":
            # available_quantity isn't a stored column, derive it from its parts.
            sql_quantity = self._read_group_select("quantity:sum", query)
            sql_reserved_quantity = self._read_group_select(
                "reserved_quantity:sum", query
            )
            return SQL("%s - %s", sql_quantity, sql_reserved_quantity)
        if aggregate_spec == "inventory_quantity_auto_apply:sum":
            # Computed field mirroring quantity (see _compute_inventory_quantity_auto_apply).
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
        # Fetch available quantity per package.
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

        # Split rows into real packages (kept as-is) and a running count of unpackaged
        # single units. Real packages make this strategy worthwhile: with none, bail
        # out *before* allocating anything. Otherwise a location with lots of unpackaged
        # stock would build -- then immediately discard -- a list of that many single-
        # unit entries for a guaranteed no-op (~46 ms for 2M units before this return).
        real_packages = []
        singles_count = 0
        for package_id, available_qty in qty_by_package:
            if package_id is None:
                # Unpackaged stock is expanded into N single (None, 1) units below, so
                # a fractional remainder (< 1 unit) can't be its own selectable unit and
                # is floored away here: least_packages ranks whole selectable units.
                singles_count += int(available_qty)
            elif available_qty != 0:
                real_packages.append((package_id, available_qty))

        if not real_packages:
            return domain

        try:
            # Expanding singles into individual (None, 1) entries is the memory-hungry
            # step, so it lives inside the MemoryError guard with the search (previously
            # it was left unguarded). Singles are appended last on purpose; see
            # _least_packages_search.
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
        Slicing the tail (``[-single_count:]``) yields the same id-set the old
        per-single popping loop produced, without re-running the query each time.

        Note the deliberate asymmetry: ``single_count`` counts selected *unit slots*
        (the search expands loose stock into one ``(None, 1)`` entry per unit), but
        ``single_item_ids`` are quant *records*, each possibly holding several units.
        Taking the last ``single_count`` records thus yields *at least* that many loose
        units -- never fewer -- so the candidate set can only over-cover on the
        unpackaged side. That is harmless: the reservation loop caps consumption at the
        requested quantity, and the package set is pinned exactly by
        ``package_id in [...]`` below, so no extra package is ever opened.
        """
        single_count = sum(1 for pkg in taken_packages if pkg[0] is None)
        selected_single_items = []
        if single_count:
            single_item_ids = self.search(Domain("package_id", "=", None) & domain).ids
            selected_single_items = single_item_ids[-single_count:]

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

        if quants_cache is not None and strict and removal_strategy != "least_packages":
            # package_id/owner_id may be None (their documented default); the cache is
            # keyed by id, so normalise to False like the search path does.
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
                # The cache is built without the removal_date filter, so apply it here to
                # keep the cache path equivalent to the search path (_get_gather_domain).
                cutoff = fields.Datetime.to_datetime(with_expiration)
                res = res.filtered(
                    lambda q: not q.removal_date or q.removal_date >= cutoff
                )
            # The search path orders on the DB by `order`; the cache is keyed but
            # unordered, so replicate the fifo/lifo in_date ordering here. Otherwise the
            # two paths return quants in a different order (id vs in_date), so the first
            # quant locked/consumed downstream would differ by whether a quants_cache
            # was in context. (closest is re-sorted below for both paths; least_packages
            # never takes this branch.)
            if removal_strategy == "fifo":
                res = res.sorted(lambda q: (q.in_date, q.id))
            elif removal_strategy == "lifo":
                res = res.sorted(lambda q: (q.in_date, q.id), reverse=True)
        else:
            res = self.search(domain, order=order)

        if removal_strategy == "closest":
            res = res.sorted(lambda q: (q.location_id.complete_name, -q.id))

        return res.sorted(lambda q: not q.lot_id)

    def _apply_inventory(self, date=None):
        # Consider the inventory_quantity as set => recompute the inventory_diff_quantity if needed
        self.inventory_quantity_set = True
        move_vals = []
        default_loss_locations = {}
        quants_with_missing_loss_locations = self.filtered(
            lambda quant: (
                not quant.product_id.with_company(
                    quant.company_id
                ).property_stock_inventory
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
            # if inventory applied from product's inverse_qty and the inventory_diff_quantity is 0,
            # we skip creating a move with 0 quantity.
            if (
                quant.env.context.get("from_inverse_qty")
                and quant.product_uom_id.compare(quant.inventory_diff_quantity, 0) == 0
            ):
                continue
            inventory_location = quant.product_id.with_company(
                quant.company_id
            ).property_stock_inventory or default_loss_locations.get(
                quant.company_id.id
            )
            # Positive diff (counted more than expected): receive stock from the loss location.
            # Negative diff: send the missing stock to the loss location.
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
        self._assign_next_inventory_date()
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
        # Resolve the strategy once and thread it (via the private
        # `_gather_removal_strategy` context key, see `_gather`) to both the gather
        # below and the closing `_get_available_quantity` re-gather, so neither re-walks
        # the product category + location parent chain.
        self = self.with_context(
            _gather_removal_strategy=self._get_removal_strategy(product_id, location_id)
        )
        quants = self._gather(
            product_id,
            location_id,
            lot_id=lot_id,
            package_id=package_id,
            owner_id=owner_id,
            strict=True,
        )
        if lot_id:
            if product_id.uom_id.compare(quantity, 0) > 0:
                quants = quants.filtered(lambda q: q.lot_id)
            else:
                # Don't remove quantity from a negative, untracked quant.
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
        # If multiple incoming dates are available for a given lot_id/package_id/owner_id, we
        # consider only the oldest one as being relevant.
        if incoming_dates:
            in_date = min(incoming_dates)
        else:
            in_date = fields.Datetime.now()

        quant = None
        if quants:
            # quants are already ordered by _gather; lock the first one.
            quant = quants.try_lock_for_update(allow_referencing=True, limit=1)

        if quant:
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
            self.create(vals)
        return (
            self._get_available_quantity(
                product_id,
                location_id,
                lot_id=lot_id,
                package_id=package_id,
                owner_id=owner_id,
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
    def _unlink_zero_quants(self):
        """_update_available_quantity may leave quants with no
        quantity and no reserved_quantity. It used to directly unlink
        these zero quants but this proved to hurt the performance as
        this method is often called in batch and each unlink invalidate
        the cache. We defer the calls to unlink in this method.
        """
        precision_digits = max(
            6, self.sudo().env.ref("uom.decimal_product_uom").digits * 2
        )
        # Use a select instead of ORM search for UoM robustness.
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
            # When called on a recordset (e.g. via _quant_tasks after moving quants),
            # scope to the touched product/location like _merge_quants does instead of
            # scanning the whole table. Model-level callers (empty self) still run global.
            query = SQL(
                "%s AND location_id = ANY(%s) AND product_id = ANY(%s)",
                query,
                list(self.location_id.ids),
                list(self.product_id.ids),
            )
        quants = self.env["stock.quant"].browse(
            row[0] for row in self.env.execute_query(query)
        )
        quants.sudo().unlink()

    @api.model
    def _clean_reservations(self):
        """Realign quants' `reserved_quantity` with the sum still reserved by active move lines."""
        reserved_quants = self.env["stock.quant"]._read_group(
            [("reserved_quantity", "!=", 0)],
            ["product_id", "location_id", "lot_id", "package_id", "owner_id"],
            ["reserved_quantity:sum", "id:recordset"],
        )
        reserved_move_lines = self.env["stock.move.line"]._read_group(
            [
                (
                    "state",
                    "in",
                    ["assigned", "partially_available", "waiting", "confirmed"],
                ),
                ("quantity_product_uom", "!=", 0),
                ("product_id.is_storable", "=", True),
            ],
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

    @api.model
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
            return []  # A barcode separator is mandatory to be able to aggregate barcodes.

        eol_char = "\t"  # Added at the end of aggregate barcodes to end `barcode_scanned` event.
        aggregate_barcodes = []
        aggregate_barcode = ""

        # Searches all GS1 rules linked to an UoM other than Unit and retrieves their AI.
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
            # In case the quant product's barcode is not GS1 compliant, add it first,
            # so that the lots and qty barcodes that follow it will be used for this product.
            if previous_product != quant.product_id:
                previous_product = quant.product_id
                if not quant.product_id.valid_ean:
                    barcode += quant.product_id.barcode
            # Fall back to the bare serial number if no GS1 barcode could be built.
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
                if aggregate_barcode and aggregate_barcode[-1] != barcode_separator:
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
        if product_id.tracking == "none":
            available_quantity = sum(quants.mapped("quantity")) - sum(
                quants.mapped("reserved_quantity")
            )
            if allow_negative:
                return available_quantity
            return (
                available_quantity
                if product_id.uom_id.compare(available_quantity, 0.0) >= 0.0
                else 0.0
            )
        # Key per-lot availability by the lot record, with None standing in for
        # untracked quants (the honest empty-lot value, not a magic string).
        available_quantities = dict.fromkeys(set(quants.mapped("lot_id")), 0.0)
        available_quantities[None] = 0.0
        for quant in quants:
            if not quant.lot_id and strict and lot_id:
                continue
            available_quantities[quant.lot_id or None] += (
                quant.quantity - quant.reserved_quantity
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

        # Product part.
        if self.product_id.valid_ean:
            barcode = self.product_id.barcode
            barcode = "01" + "0" * (14 - len(barcode)) + barcode
        elif self.tracking == "none" or not self.lot_id:
            return ""  # Doesn't make sense to generate a GS1 barcode for qty with no other data.

        # Quantity part.
        if self.tracking != "serial" or self.quantity > 1:
            quantity_ai = gs1_quantity_rules_ai_by_uom.get(self.product_uom_id.id)
            if quantity_ai:
                qty_str = str(int(self.quantity / self.product_uom_id.rounding))
                if len(qty_str) <= 6:
                    barcode += quantity_ai + "0" * (6 - len(qty_str)) + qty_str
            else:
                # No decimal indicator for GS1 Units, no better solution than rounding the qty.
                qty_str = str(round(self.quantity))
                if len(qty_str) <= 8:
                    barcode += "30" + "0" * (8 - len(qty_str)) + qty_str

        # Tracking part (must be GS1 barcode's last part since we don't know SN/LN length.)
        if self.lot_id:
            if len(self.lot_id.name) > 20:
                # Cannot generate a valid GS1 barcode since the lot/serial number max length is
                # exceeded and this information is required if the LN/SN is present.
                return ""
            tracking_ai = "21" if self.tracking == "serial" else "10"
            barcode += tracking_ai + self.lot_id.name
        return barcode

    @api.model
    def _get_inventory_fields_create(self):
        """Returns a list of fields user can edit when he want to create a quant in `inventory_mode`."""
        return ["product_id", "owner_id"] + self._get_inventory_fields_write()

    @api.model
    def _get_inventory_fields_write(self):
        """Returns a list of fields user can edit when he want to edit a quant in `inventory_mode`."""
        # Returned as a literal so no local `fields` binding shadows the module import.
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
        # Used by the server action so this action can be reached directly via URL.
        action["path"] = "stock-locations"
        return action

    def _get_quants_by_products_locations(
        self, product_ids, location_ids, extra_domain=False
    ):
        res = defaultdict(lambda: self.env["stock.quant"])
        if product_ids and location_ids:
            domain = Domain(
                [
                    ("product_id", "in", product_ids.ids),
                    ("location_id", "child_of", location_ids.ids),
                ]
            )
            if extra_domain:
                domain &= Domain(extra_domain)
            needed_quants = self.env["stock.quant"]._read_group(
                domain,
                ["product_id", "location_id", "lot_id", "package_id", "owner_id"],
                ["id:recordset"],
                order="lot_id",
            )
            for product, loc, lot, package, owner, quants in needed_quants:
                res[product.id, loc.id, lot.id, package.id, owner.id] = quants
        return res

    @api.model
    def _get_removal_strategy(self, product_id, location_id):
        product_id = product_id.sudo()
        if product_id.categ_id.removal_strategy_id:
            return product_id.categ_id.removal_strategy_id.with_context(
                lang=None
            ).method
        location_id = location_id.sudo()
        # The nearest ancestor location carrying a strategy wins, else fifo. Rather
        # than climb one `location_id` read per level, resolve the whole chain from the
        # materialised `parent_path` ("/"-joined ids, root-first, self last) and browse
        # it at once: the first `removal_strategy_id` access prefetches the column for
        # every ancestor in one query. Falls back to the climb only if `parent_path` is
        # not set yet (transient during creation).
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
        the *exact same characteristics* otherwise. If no quants are in self, `_gather` will do a search to fetch the quants.
        Typically, this method is called before the `stock.move.line` creation to know the reserved_qty that could be used.
        It's also called by `_update_reserved_quantity` to find the quant to reserve.

        :return: a list of tuples (quant, quantity_reserved) showing on which quant the reservation
            could be done and how much the system is able to reserve on it
        """
        self = self.sudo()

        # Resolve the strategy once and thread it to every gather below via the private
        # `_gather_removal_strategy` context key (see `_gather`), so neither the gather
        # nor the availability re-gather re-walks the category + location parent chain.
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

        # allow_negative defaults to False: quants left negative by another lot/package
        # don't reduce the available quantity of the rest.
        #
        # For every strategy but least_packages the availability is measured over the
        # `quants` just gathered, so reuse them via `_sum_available_quantity` and save a
        # second full search of the stock_quant hot table. least_packages is the
        # exception: `quants` was narrowed to the chosen packages by `qty`, but
        # availability must be measured over the *whole* set, so re-gather it (a fresh
        # `_get_available_quantity`, which reuses the threaded strategy above).
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

        # Packaging with a "full" reserve method can only reserve whole packages.
        if (
            self.env.context.get("packaging_uom_id")
            and product_id.product_tmpl_id.categ_id.packaging_reserve_method == "full"
        ):
            available_quantity = self.env.context.get("packaging_uom_id")._check_qty(
                min(quantity, available_quantity), product_id.uom_id, "DOWN"
            )

        quantity = min(quantity, available_quantity)

        # `quantity` is in the quants' UoM. Blindly reserving it could break the move's
        # UoM rounding (e.g. when that rounding forbids fractional reservation), so
        # round-trip it: convert to the move's UoM rounding DOWN, then back to the
        # quants' UoM rounding HALF-UP, which never reserves more than allowed. Skipped
        # when `available_quantity` comes from a chained move line -- there
        # `_prepare_move_line_vals` changes the UoM to the product's.
        if not strict and uom_id and product_id.uom_id != uom_id:
            quantity_move_uom = product_id.uom_id._compute_quantity(
                quantity, uom_id, rounding_method="DOWN"
            )
            quantity = uom_id._compute_quantity(
                quantity_move_uom, product_id.uom_id, rounding_method="HALF-UP"
            )

        if product_id.tracking == "serial":
            # Serial-tracked products can only be reserved in whole units.
            if product_id.uom_id.compare(quantity, int(quantity)) != 0:
                quantity = 0

        # Size the running budget from the whole gathered set (the reserve branch draws
        # it down; the unreserve branch guards against releasing more than is reserved),
        # then hand per-candidate allocation to the pure `_distribute_reservation`. The
        # `raise` and ORM aggregates stay here; the DB-free arithmetic is extracted.
        cmp_quantity = product_id.uom_id.compare(quantity, 0)
        if cmp_quantity > 0:
            # Positive quantity means reserving.
            available_quantity = sum(
                quants.filtered(
                    lambda q: product_id.uom_id.compare(q.quantity, 0) > 0
                ).mapped("quantity")
            ) - sum(quants.mapped("reserved_quantity"))
        elif cmp_quantity < 0:
            # Negative quantity means unreserving.
            available_quantity = sum(quants.mapped("reserved_quantity"))
            if product_id.uom_id.compare(abs(quantity), available_quantity) > 0:
                raise UserError(
                    _(
                        "It is not possible to unreserve more products of %s than you have in stock.",
                        product_id.display_name,
                    )
                )
        else:
            return []

        precision_digits = self.env["decimal.precision"].precision_get("Product Unit")
        candidates = [
            _ReservationCandidate(
                quant, quant.quantity, quant.reserved_quantity, quant._reservation_key()
            )
            for quant in quants
        ]
        return _distribute_reservation(
            candidates, quantity, available_quantity, precision_digits
        )

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
            with self.env.cr.savepoint():
                self.env.cr.execute(query, params)
                self.env.invalidate_all()
        except Error as e:
            _logger.warning("an error occurred while merging quants: %s", e.pgerror)

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
                # Only move the container package as well if its whole content is moved as well
                return None
            package.package_dest_id = package.parent_package_id
            return set_parent_package(all_quants, package.parent_package_id, limit_ids)

        message = message or _("Quantity Relocated")
        move_vals = []
        limit_ids = set(up_to_parent_packages.ids if up_to_parent_packages else [])
        for quant in self:
            result_package_id = (
                package_dest_id  # temp variable to keep package_dest_id unchanged
            )
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

    # ------------------------------------------------------------
    # VALIDATIONS
    # ------------------------------------------------------------

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
            if product.uom_id.compare(abs(qty), 1) > 0:
                raise ValidationError(
                    _(
                        "The serial number has already been assigned: \n Product: %(product)s, Serial Number: %(serial_number)s",
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
                    # trying to assign an already existing SN
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
                    # using an existing SN in the wrong location
                    recommended_location = self.env["stock.location"]
                    if ref_doc_location_id:
                        for location in sn_locations:
                            if ref_doc_location_id.parent_path in location.parent_path:
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

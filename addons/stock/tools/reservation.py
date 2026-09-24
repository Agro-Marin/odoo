import heapq
import math
import typing
from collections import defaultdict

from odoo.libs.debug_log import DebugLog
from odoo.tools import float_compare, float_is_zero, float_round

_debug = DebugLog(__name__)


class LeastPackagesPriorityQueue:
    def __init__(self):
        self.elements = []
        self._counter = 0

    def is_empty(self) -> bool:
        return not self.elements

    def put(self, item, priority):
        heapq.heappush(self.elements, (priority, self._counter, item))
        self._counter += 1

    def get(self):
        return heapq.heappop(self.elements)[2]


class LeastPackagesNode(typing.NamedTuple):
    count_remaining: float
    taken_packages: tuple
    next_index: int


def get_least_packages(qty_by_package, qty):
    size = len(qty_by_package)

    def heuristic(node):
        if node.next_index < size:
            return (
                len(node.taken_packages)
                + node.count_remaining / qty_by_package[node.next_index][1]
            )
        return len(node.taken_packages)

    frontier = LeastPackagesPriorityQueue()
    frontier.put(LeastPackagesNode(qty, (), 0), 0)
    best_leaf = LeastPackagesNode(qty, (), 0)

    while not frontier.is_empty():
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
            node = LeastPackagesNode(count, taken, i)

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


class RemovalStrategy(typing.NamedTuple):
    order: str | typing.Literal[False]
    sort_key: typing.Callable | None = None
    reverse: bool = False
    narrows_to_packages: bool = False
    sorts_by_location: bool = False

    def resolve_sorted_arguments(self):
        return None if self.sort_key is None else (self.sort_key, self.reverse)


class ReservationLedger:
    __slots__ = ("_by_move", "_pending", "move_line_vals")

    def __init__(self, move_line_vals=None):
        self._pending = defaultdict(float)
        self._by_move = defaultdict(list)
        self.move_line_vals = []
        self.add_move_line_vals(move_line_vals or ())

    def add_move_line_vals(self, vals_list):
        for vals in vals_list:
            self.move_line_vals.append(vals)
            self._by_move[vals.get("move_id")].append(vals)

    def get_pending(self, quant):
        return self._pending.get(quant.id, 0.0)

    def take(self, quant, quantity):
        self._pending[quant.id] += quantity

    def get_pending_quant_ids(self):
        return [quant_id for quant_id, quantity in self._pending.items() if quantity]

    def get_total_pending(self):
        return sum(self._pending.values())

    def get_pending_move_line_vals(self, move_ids):
        return [vals for move_id in move_ids for vals in self._by_move.get(move_id, ())]


class ReservationCandidate(typing.NamedTuple):
    handle: object
    on_hand: float
    reserved: float
    key: object


def distribute_reservation(candidates, quantity, precision_rounding, whole_units=False):
    reserved = []
    if float_compare(quantity, 0, precision_rounding=precision_rounding) <= 0:
        return reserved

    negative_available = defaultdict(float)
    for cand in candidates:
        slack = cand.on_hand - cand.reserved
        if float_compare(slack, 0, precision_rounding=precision_rounding) < 0:
            negative_available[cand.key] += slack
    if _debug.logic.enabled and negative_available:
        _debug.logic(
            "distribute_reservation_negative_first", places=len(negative_available)
        )

    for cand in candidates:
        max_on_cand = cand.on_hand - cand.reserved
        if float_compare(max_on_cand, 0, precision_rounding=precision_rounding) <= 0:
            continue
        negative = negative_available[cand.key]
        if negative:
            to_absorb = min(abs(negative), max_on_cand)
            negative_available[cand.key] += to_absorb
            max_on_cand -= to_absorb
        if float_compare(max_on_cand, 0, precision_rounding=precision_rounding) <= 0:
            continue
        max_on_cand = min(max_on_cand, quantity)
        if whole_units:
            max_on_cand = float(
                math.floor(
                    float_round(max_on_cand, precision_rounding=precision_rounding)
                )
            )
            if max_on_cand <= 0:
                continue
        reserved.append((cand.handle, max_on_cand))
        quantity -= max_on_cand

        if float_is_zero(quantity, precision_rounding=precision_rounding):
            break
    _debug.logic(
        "distribute_reservation",
        candidates=len(candidates),
        whole_units=whole_units,
        taken=len(reserved),
        unserved=quantity,
    )
    return reserved


class QuantsCache:
    __slots__ = (
        "_by_product",
        "_data",
        "_empty",
        "_location_paths",
        "_lot_scope",
        "_paths_by_location",
        "_product_ids",
    )

    def __init__(self, empty, product_ids=(), location_paths=(), lot_scope=None):
        self._data = {}
        self._by_product = defaultdict(list)
        self._empty = empty
        self._product_ids = frozenset(product_ids)
        self._location_paths = tuple(p for p in location_paths if p)
        self._lot_scope = None if lot_scope is None else frozenset(lot_scope)
        self._paths_by_location = {}

    def __getitem__(self, key):
        return self._data.get(key, self._empty)

    def __setitem__(self, key, value):
        if key not in self._data:
            self._by_product[key[0]].append(key)
        self._data[key] = value

    def set_location_path(self, location_id, parent_path):
        self._paths_by_location[location_id] = parent_path or ""

    def add(self, quant):
        location = quant.location_id
        key = (
            quant.product_id.id,
            location.id,
            quant.lot_id.id,
            quant.package_id.id,
            quant.owner_id.id,
        )
        self[key] |= quant
        self.set_location_path(location.id, location.parent_path)

    def under(
        self, product_id, location_path, lot_id=None, package_id=None, owner_id=None
    ):
        # the quants a non-strict gather selects: every location under the
        # path, the lot or none when a lot is asked, any package or owner
        # unless one is asked
        paths = self._paths_by_location
        result = self._empty
        for key in self._by_product.get(product_id, ()):
            _product, location, lot, package, owner = key
            if not paths.get(location, "").startswith(location_path):
                continue
            if lot_id and lot not in (lot_id, False):
                continue
            if package_id and package != package_id:
                continue
            if owner_id and owner != owner_id:
                continue
            result |= self._data[key]
        return result

    def is_covering(self, product_id, location_id, lot_id=None):
        if product_id.id not in self._product_ids:
            _debug.perf.count("quants_cache_miss_product", product=product_id.id)
            return False
        path = location_id.parent_path or ""
        if not any(path.startswith(root) for root in self._location_paths):
            _debug.perf.count("quants_cache_miss_location", location=location_id.id)
            return False
        return self._lot_scope is None or not lot_id or lot_id.id in self._lot_scope

import heapq
import math
import typing
from collections import defaultdict

from odoo.tools import float_compare, float_is_zero


class LeastPackagesPriorityQueue:
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


class LeastPackagesNode(typing.NamedTuple):
    count_remaining: float
    taken_packages: tuple
    next_index: int


def least_packages_search(qty_by_package, qty):
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

    def as_sorted_arguments(self):
        return None if self.sort_key is None else (self.sort_key, self.reverse)


class ReservationLedger:
    __slots__ = ("_pending", "move_line_vals")

    def __init__(self, move_line_vals=None):
        self._pending = defaultdict(float)
        self.move_line_vals = move_line_vals if move_line_vals is not None else []

    def pending(self, quant):
        return self._pending.get(quant.id, 0.0)

    def take(self, quant, quantity):
        self._pending[quant.id] += quantity

    def total_pending(self):
        return sum(self._pending.values())


class ReservationCandidate(typing.NamedTuple):
    handle: object
    on_hand: float
    reserved: float
    key: object


def distribute_reservation(candidates, quantity, precision_digits, whole_units=False):
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
        if whole_units:
            max_on_cand = float(math.floor(round(max_on_cand, precision_digits)))
            if max_on_cand <= 0:
                continue
        reserved.append((cand.handle, max_on_cand))
        quantity -= max_on_cand

        if float_is_zero(quantity, precision_digits=precision_digits):
            break
    return reserved


class QuantsCache:
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
        if product_id.id not in self._product_ids:
            return False
        path = location_id.parent_path or ""
        if not any(path.startswith(root) for root in self._location_paths):
            return False
        return self._lot_scope is None or not lot_id or lot_id.id in self._lot_scope

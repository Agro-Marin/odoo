"""Set-algebra expressions over named sets.

This module models combinations of named sets using union, intersection and
complement.  :class:`SetDefinitions` builds :class:`SetExpression` objects
(implemented by :class:`Union`, :class:`Inter` and :class:`Leaf`), notably to
express group membership rules.
"""

import ast
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable


# Backstop against the exponential blow-up of intersecting (and hence inverting,
# which expands ``~(A | B | ...)`` to ``~A & ~B & ...`` via De Morgan) large
# disjunctive normal forms: a Union of N intersections of m leaves inverts to
# m**N terms.  A real ``res.groups`` expression is far smaller; a value this
# large means a pathological input, so raise a clear error instead of hanging a
# worker.  Mirrors the ``MAX_OPTIMIZE_ITERATIONS`` backstop in the domain
# optimizer.
MAX_INTERSECTION_TERMS = 100_000


class SetExpressionError(ValueError):
    """Raised when a set expression cannot be evaluated within safe bounds."""


class SetDefinitions:
    """A collection of set definitions, used as a factory for set expressions.

    Each set is defined by an id, a name, its supersets, and the sets that are
    disjoint with it.  Set expressions are combinations of named sets with
    union, intersection and complement.
    """

    __slots__ = ("__leaves",)

    def __init__(self, definitions: dict[int, dict[str, object]]) -> None:
        r"""Initialize the object from the given set ``definitions``.

        ``definitions`` maps each set id to a dict with a required key ``"ref"``
        (value is the set's name) and optional keys ``"supersets"`` (value is a
        collection of set ids) and ``"disjoints"`` (value is a collection of set
        ids).

        Here is an example of set definitions, with natural numbers (N), integer
        numbers (Z), rational numbers (Q), irrational numbers (R\\Q), real
        numbers (R), imaginary numbers (I) and complex numbers (C)::

            {
                1: {"ref": "N", "supersets": [2]},
                2: {"ref": "Z", "supersets": [3]},
                3: {"ref": "Q", "supersets": [4]},
                4: {"ref": "R", "supersets": [6]},
                5: {"ref": "I", "supersets": [6], "disjoints": [4]},
                6: {"ref": "C"},
                7: {"ref": "R\\Q", "supersets": [4]},
            }
            Representation:
            ┌──────────────────────────────────────────┐
            │ C  ┌──────────────────────────┐          │
            │    │ R  ┌───────────────────┐ │ ┌──────┐ |   "C"
            │    │    │ Q  ┌────────────┐ │ │ │ I    | |   "I" implied "C"
            │    │    │    │ Z  ┌─────┐ │ │ │ │      | |   "R" implied "C"
            │    │    │    │    │ N   │ │ │ │ │      │ │   "Q" implied "R"
            │    │    │    │    └─────┘ │ │ │ │      │ │   "R\\Q" implied "R"
            │    │    │    └────────────┘ │ │ │      │ │   "Z" implied "Q"
            │    │    └───────────────────┘ │ │      │ │   "N" implied "Z"
            │    │      ┌───────────────┐   │ │      │ │
            │    │      │ R\\Q          │   │ │      │ │
            │    │      └───────────────┘   │ └──────┘ │
            │    └──────────────────────────┘          │
            └──────────────────────────────────────────┘
        """
        self.__leaves: dict[int | str, Leaf] = {}

        for leaf_id, info in definitions.items():
            ref = info["ref"]
            if ref == "*":
                msg = "The set reference '*' is reserved for the universal set."
                raise ValueError(msg)
            leaf = Leaf(leaf_id, ref)
            self.__leaves[leaf_id] = leaf
            self.__leaves[ref] = leaf

        # compute transitive closure of subsets and supersets
        subsets = {leaf.id: leaf.subsets for leaf in self.__leaves.values()}
        supersets = {leaf.id: leaf.supersets for leaf in self.__leaves.values()}
        for leaf_id, info in definitions.items():
            for greater_id in info.get("supersets", ()):
                # transitive closure: smaller_ids <= leaf_id <= greater_id <= greater_ids
                smaller_ids = subsets[leaf_id]
                greater_ids = supersets[greater_id]
                for smaller_id in smaller_ids:
                    supersets[smaller_id].update(greater_ids)
                for greater_id in greater_ids:
                    subsets[greater_id].update(smaller_ids)

        # compute transitive closure of disjoint relation
        disjoints = {leaf.id: leaf.disjoints for leaf in self.__leaves.values()}
        for leaf_id, info in definitions.items():
            for distinct_id in info.get("disjoints", set()):
                # all subsets[leaf_id] are disjoint from all subsets[distinct_id]
                left_ids = subsets[leaf_id]
                right_ids = subsets[distinct_id]
                for left_id in left_ids:
                    disjoints[left_id].update(right_ids)
                for right_id in right_ids:
                    disjoints[right_id].update(left_ids)

    @property
    def empty(self) -> SetExpression:
        """Return the empty set expression."""
        return EMPTY_UNION

    @property
    def universe(self) -> SetExpression:
        """Return the universal set expression."""
        return UNIVERSAL_UNION

    def parse(self, refs: str, raise_if_not_found: bool = True) -> SetExpression:
        """Return the set expression corresponding to ``refs``.

        :param str refs: comma-separated list of set references
            optionally preceded by ``!`` (negative item). The result is
            a union of the positive items, each intersected with every
            negative group.
            (e.g. ``base.group_user,base.group_portal,!base.group_system``)
        """
        positives: list[Leaf] = []
        negatives: list[Leaf] = []
        for xmlid in refs.split(","):
            if xmlid.startswith("!"):
                negatives.append(
                    ~self.__get_leaf(xmlid.removeprefix("!"), raise_if_not_found)
                )
            else:
                positives.append(self.__get_leaf(xmlid, raise_if_not_found))

        if positives:
            return Union(Inter([leaf] + negatives) for leaf in positives)
        else:
            return Union([Inter(negatives)])

    def from_ids(self, ids: Iterable[int], keep_subsets: bool = False) -> SetExpression:
        """Return the set expression corresponding to given set ids."""
        if keep_subsets:
            ids = set(ids)
            ids = [
                leaf_id
                for leaf_id in ids
                if not any((self.__leaves[leaf_id].subsets - {leaf_id}) & ids)
            ]
        return Union(Inter([self.__leaves[leaf_id]]) for leaf_id in ids)

    def from_key(self, key: str) -> SetExpression:
        """Return the set expression corresponding to the given key."""
        # union_tuple = tuple(tuple(tuple(leaf_id, negative), ...), ...)
        union_tuple = ast.literal_eval(key)
        return Union(
            [
                Inter(
                    [
                        ~leaf if negative else leaf
                        for leaf_id, negative in inter_tuple
                        for leaf in [self.__get_leaf(leaf_id, raise_if_not_found=False)]
                    ],
                    optimal=True,
                )
                for inter_tuple in union_tuple
            ],
            optimal=True,
        )

    def get_id(self, ref: str | int) -> LeafIdType | None:
        """Return a set id from its reference, or ``None`` if it does not exist."""
        if ref == "*":
            return UNIVERSAL_LEAF.id
        leaf = self.__leaves.get(ref)
        return None if leaf is None else leaf.id

    def __get_leaf(self, ref: str | int, raise_if_not_found: bool = True) -> Leaf:
        """Return the ``Leaf`` for the reference ``ref``."""
        if ref == "*":
            return UNIVERSAL_LEAF
        if not raise_if_not_found and ref not in self.__leaves:
            return Leaf(UnknownId(ref), ref)
        return self.__leaves[ref]

    def get_superset_ids(self, ids: Iterable[int]) -> list[int]:
        """Return the supersets matching the provided list of ids.

        Following the example defined in this class's constructor::
        The supersets of "Q" (id 3) are "R" and "C" with ids [4, 6]
        """
        return sorted(
            {
                sup_id
                for id_ in ids
                if id_ in self.__leaves
                for sup_id in self.__leaves[id_].supersets
                if sup_id != id_
            }
        )

    def get_subset_ids(self, ids: Iterable[int]) -> list[int]:
        """Return the subsets matching the provided list of ids.

        Following the example defined in this class's constructor::
        The subsets of "Q" (id 3) are "Z" and "N" with ids [1, 2]
        """
        return sorted(
            {
                sub_id
                for id_ in ids
                if id_ in self.__leaves
                for sub_id in self.__leaves[id_].subsets
                if sub_id != id_
            }
        )

    def get_disjoint_ids(self, ids: Iterable[int]) -> list[int]:
        r"""Return the disjoint sets matching the provided list of ids.

        Following the example defined in this class's constructor::
        The disjoint sets of "Q" (id 3) are "R\\Q" and "I" with ids [7, 5]
        """
        return sorted(
            {
                disjoint_id
                for id_ in ids
                if id_ in self.__leaves
                for disjoint_id in self.__leaves[id_].disjoints
            }
        )


class SetExpression(ABC):
    """A combination of named sets with union, intersection and complement."""

    @abstractmethod
    def is_empty(self) -> bool:
        """Return whether ``self`` is the empty set."""
        raise NotImplementedError

    @abstractmethod
    def is_universal(self) -> bool:
        """Return whether ``self`` is the universal set."""
        raise NotImplementedError

    @abstractmethod
    def invert_intersect(self, factor: SetExpression) -> SetExpression | None:
        """Return ``result`` such that ``self == result & factor`` (factorization)."""
        raise NotImplementedError

    @abstractmethod
    def matches(self, user_group_ids: Iterable[int]) -> bool:
        """Return whether the given group ids are included to ``self``.

        Note: an empty ``user_group_ids`` returns ``False`` for *every*
        expression -- including the universal set and negations such as ``~A``.
        A groupless subject is treated as matching no set, not as an empty set
        that would trivially satisfy a complement.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def key(self) -> str:
        """Return a unique identifier for the expression."""
        raise NotImplementedError

    @abstractmethod
    def __and__(self, other: SetExpression) -> SetExpression:
        """Return the intersection of ``self`` and ``other``."""
        raise NotImplementedError

    @abstractmethod
    def __or__(self, other: SetExpression) -> SetExpression:
        """Return the union of ``self`` and ``other``."""
        raise NotImplementedError

    @abstractmethod
    def __invert__(self) -> SetExpression:
        """Return the complement of ``self``."""
        raise NotImplementedError

    @abstractmethod
    def __eq__(self, other: object) -> bool:
        """Return whether ``self`` and ``other`` represent the same set."""
        raise NotImplementedError

    @abstractmethod
    def __le__(self, other: SetExpression) -> bool:
        """Return whether ``self`` is a subset of ``other``."""
        raise NotImplementedError

    @abstractmethod
    def __lt__(self, other: SetExpression) -> bool:
        """Return whether ``self`` is a strict subset of ``other``."""
        raise NotImplementedError

    @abstractmethod
    def __hash__(self) -> int:
        """Return the hash of ``self``."""
        raise NotImplementedError


class Union(SetExpression):
    """A set expression represented as a union of intersections.

    Each intersection combines named sets or their complement.
    """

    def __init__(self, inters: Iterable[Inter] = (), optimal: bool = False) -> None:
        """Build a union from the given intersections.

        When ``optimal`` is false, the intersections are first combined into a
        canonical, non-redundant form.
        """
        if inters and not optimal:
            inters = self.__combine((), inters)
        self.__inters = sorted(inters, key=lambda inter: inter.key)
        self.__key = str(tuple(inter.key for inter in self.__inters))
        self.__hash = hash(self.__key)

    @property
    def key(self) -> str:
        """Return a unique identifier for the expression."""
        return self.__key

    @staticmethod
    def __combine(
        inters: Iterable[Inter], inters_to_add: Iterable[Inter]
    ) -> list[Inter]:
        """Combine some existing union of intersections with extra intersections."""
        result = list(inters)

        todo = list(inters_to_add)
        while todo:
            inter_to_add = todo.pop()
            if inter_to_add.is_universal():
                return [UNIVERSAL_INTER]
            if inter_to_add.is_empty():
                continue

            for index, inter in enumerate(result):
                merged = inter._union_merge(inter_to_add)
                if merged is not None:
                    result.pop(index)
                    todo.append(merged)
                    break
            else:
                result.append(inter_to_add)

        return result

    def is_empty(self) -> bool:
        """Return whether ``self`` is the empty set."""
        return not self.__inters

    def is_universal(self) -> bool:
        """Return whether ``self`` is the universal set."""
        return any(item.is_universal() for item in self.__inters)

    def invert_intersect(self, factor: SetExpression) -> Union | None:
        """Return ``result`` such that ``self == result & factor`` (factorization)."""
        if factor == self:
            return UNIVERSAL_UNION

        rfactor = ~factor
        if rfactor.is_empty() or rfactor.is_universal():
            return None
        rself = ~self

        if not isinstance(rfactor, Union):
            raise TypeError(f"Expected Union, got {type(rfactor).__name__}")
        inters = [inter for inter in rself.__inters if inter not in rfactor.__inters]
        if len(rself.__inters) - len(inters) != len(rfactor.__inters):
            # not possible to invert the intersection
            return None

        rself_value = Union(inters)
        return ~rself_value

    def __and__(self, other: SetExpression) -> Union:
        """Return the intersection of ``self`` and ``other``."""
        if not isinstance(other, Union):
            raise TypeError(f"Expected Union, got {type(other).__name__}")
        if self.is_universal():
            return other
        if other.is_universal():
            return self
        if self.is_empty() or other.is_empty():
            return EMPTY_UNION
        if self == other:
            return self
        # The product below has len(self) * len(other) terms; guard before
        # materializing it so a runaway inversion fails fast (and bounds the
        # repeated ``&`` in ``__invert__``) instead of exhausting time/memory.
        if len(self.__inters) * len(other.__inters) > MAX_INTERSECTION_TERMS:
            raise SetExpressionError(
                f"set expression intersection too large "
                f"({len(self.__inters)} x {len(other.__inters)} terms exceeds "
                f"{MAX_INTERSECTION_TERMS}); the input expression is pathological"
            )
        return Union(
            self_inter & other_inter
            for self_inter in self.__inters
            for other_inter in other.__inters
        )

    def __or__(self, other: SetExpression) -> Union:
        """Return the union of ``self`` and ``other``."""
        if not isinstance(other, Union):
            raise TypeError(f"Expected Union, got {type(other).__name__}")
        if self.is_empty():
            return other
        if other.is_empty():
            return self
        if self.is_universal() or other.is_universal():
            return UNIVERSAL_UNION
        if self == other:
            return self
        inters = self.__combine(self.__inters, other.__inters)
        return Union(inters, optimal=True)

    def __invert__(self) -> Union:
        """Return the complement of ``self``."""
        if self.is_empty():
            return UNIVERSAL_UNION
        if self.is_universal():
            return EMPTY_UNION

        # De Morgan expands ``~(A1 & ...) & ~(B1 & ...) & ...`` to a product of
        # the per-intersection leaf counts.  Estimate that product upfront
        # (O(number of intersections)) and refuse a pathological blow-up before
        # building millions of terms, instead of discovering it mid-expansion.
        estimate = 1
        for inter in self.__inters:
            estimate *= max(1, len(inter.leaves))
            if estimate > MAX_INTERSECTION_TERMS:
                raise SetExpressionError(
                    f"cannot invert set expression: De Morgan expansion exceeds "
                    f"{MAX_INTERSECTION_TERMS} terms; the input is pathological"
                )

        # apply De Morgan's laws
        inverses_of_inters = [
            # ~(A & B) = ~A | ~B
            Union(Inter([~leaf]) for leaf in inter.leaves)
            for inter in self.__inters
        ]
        result = inverses_of_inters[0]
        # ~(A | B) = ~A & ~B
        for inverse in inverses_of_inters[1:]:
            result = result & inverse

        return result

    def matches(self, user_group_ids: Iterable[int]) -> bool:
        """Return whether the given group ids match ``self``."""
        # Materialize first: the emptiness contract below tests truthiness, and a
        # non-empty *iterator* (e.g. ``iter([])``) is always truthy, so an empty
        # generator would wrongly pass the guard and match the universal set.
        user_group_ids = set(user_group_ids)
        # empty ids match nothing, even the universal set / a negation (checked
        # before is_universal on purpose -- see SetExpression.matches note)
        if self.is_empty() or not user_group_ids:
            return False
        if self.is_universal():
            return True
        return any(inter.matches(user_group_ids) for inter in self.__inters)

    def __bool__(self) -> bool:
        """Raise ``NotImplementedError``; set expressions are not truth-testable."""
        raise NotImplementedError

    def __eq__(self, other: object) -> bool:
        """Return whether ``self`` and ``other`` represent the same set."""
        return isinstance(other, Union) and self.__key == other.__key

    def __le__(self, other: SetExpression) -> bool:
        """Return whether ``self`` is a subset of ``other``."""
        if not isinstance(other, Union):
            return False
        if self.__key == other.__key:
            return True
        if self.is_universal() or other.is_empty():
            return False
        if other.is_universal() or self.is_empty():
            return True
        return all(
            any(self_inter <= other_inter for other_inter in other.__inters)
            for self_inter in self.__inters
        )

    def __lt__(self, other: SetExpression) -> bool:
        """Return whether ``self`` is a strict subset of ``other``."""
        return self != other and self.__le__(other)

    def __str__(self) -> str:
        """Return a human-readable ``|`` of ``&``-joined references.

        e.g. ('base.group_user' & 'base.group_multi_company') | ('base.group_portal' & ~'base.group_multi_company') | 'base.group_public'
        """
        if self.is_empty():
            return "~*"

        def leaf_to_str(leaf: Leaf) -> str:
            return f"{'~' if leaf.negative else ''}{leaf.ref!r}"

        def inter_to_str(inter: Inter, wrapped: bool = False) -> str:
            result = " & ".join(leaf_to_str(leaf) for leaf in inter.leaves) or "*"
            return f"({result})" if wrapped and len(inter.leaves) > 1 else result

        wrapped = len(self.__inters) > 1
        return " | ".join(inter_to_str(inter, wrapped) for inter in self.__inters)

    def __repr__(self) -> str:
        """Return the string representation of ``self``."""
        return repr(self.__str__())

    def __hash__(self) -> int:
        """Return the hash of ``self``."""
        return self.__hash


class Inter:
    """An intersection of named sets or their complement.

    Part of the implementation of a :class:`Union` set expression.
    """

    __slots__ = ("key", "leaves")

    def __init__(self, leaves: Iterable[Leaf] = (), optimal: bool = False) -> None:
        """Build an intersection from the given leaves.

        When ``optimal`` is false, the leaves are first combined into a
        canonical, non-redundant form.
        """
        if leaves and not optimal:
            leaves = self.__combine((), leaves)
        self.leaves: list[Leaf] = sorted(leaves, key=lambda leaf: leaf.key)
        self.key: tuple[tuple[LeafIdType, bool], ...] = tuple(
            leaf.key for leaf in self.leaves
        )

    @staticmethod
    def __combine(leaves: Iterable[Leaf], leaves_to_add: Iterable[Leaf]) -> list[Leaf]:
        """Combine some existing intersection of leaves with extra leaves.

        Produces a canonical, order-independent leaf set: every added leaf is
        checked against *all* existing leaves (not just up to the first
        subsumption).
        """
        result = list(leaves)
        for leaf_to_add in leaves_to_add:
            if leaf_to_add.is_universal():
                continue  # universe is the identity of intersection
            # Disjoint with any existing leaf => the whole intersection is empty.
            if any(leaf.isdisjoint(leaf_to_add) for leaf in result):
                return [EMPTY_LEAF]
            # Already implied by a narrower existing leaf => adds nothing.
            if any(leaf <= leaf_to_add for leaf in result):
                continue
            # Otherwise keep it, dropping any existing leaves it subsumes.
            result = [leaf for leaf in result if not leaf_to_add <= leaf]
            result.append(leaf_to_add)
        return result

    def is_empty(self) -> bool:
        """Return whether ``self`` is the empty set."""
        return any(item.is_empty() for item in self.leaves)

    def is_universal(self) -> bool:
        """Return whether ``self`` is the universal set."""
        return not self.leaves

    def matches(self, user_group_ids: Collection[int]) -> bool:
        """Return whether the given group ids match every leaf of ``self``."""
        return all(leaf.matches(user_group_ids) for leaf in self.leaves)

    def _union_merge(self, other: Inter) -> Inter | None:
        """Return the union of ``self`` with ``other`` as a single intersection.

        Return ``None`` when that union cannot be represented as an
        intersection.
        """
        # the following covers cases like (A & B) | A -> A
        if self.is_universal() or other <= self:
            return self
        if self <= other:
            return other

        # combine complementary parts: (A & ~B) | (A & B) -> A
        if len(self.leaves) == len(other.leaves):
            opposite_index = None
            # we use the property that __leaves are ordered
            for index, self_leaf, other_leaf in zip(
                range(len(self.leaves)), self.leaves, other.leaves, strict=False
            ):
                if self_leaf.id != other_leaf.id:
                    return None
                if self_leaf.negative != other_leaf.negative:
                    if opposite_index is not None:
                        return None  # we already have two opposite leaves
                    opposite_index = index
            if opposite_index is not None:
                leaves = list(self.leaves)
                leaves.pop(opposite_index)
                return Inter(leaves, optimal=True)
        return None

    def __and__(self, other: Inter) -> Inter:
        """Return the intersection of ``self`` and ``other``."""
        if self.is_empty() or other.is_empty():
            return EMPTY_INTER
        if self.is_universal():
            return other
        if other.is_universal():
            return self
        leaves = self.__combine(self.leaves, other.leaves)
        return Inter(leaves, optimal=True)

    def __eq__(self, other: object) -> bool:
        """Return whether ``self`` and ``other`` are the same intersection."""
        return isinstance(other, Inter) and self.key == other.key

    def __le__(self, other: Inter) -> bool:
        """Return whether ``self`` is a subset of ``other``."""
        return self.key == other.key or all(
            any(self_leaf <= other_leaf for self_leaf in self.leaves)
            for other_leaf in other.leaves
        )

    def __lt__(self, other: Inter) -> bool:
        """Return whether ``self`` is a strict subset of ``other``."""
        return self != other and self <= other

    def __hash__(self) -> int:
        """Return the hash of ``self``."""
        return hash(self.key)


class Leaf:
    """A named set or its complement.

    Part of the implementation of a :class:`Union` set expression.
    """

    __slots__ = (
        "disjoints",
        "id",
        "inverse",
        "key",
        "negative",
        "ref",
        "subsets",
        "supersets",
    )

    def __init__(
        self,
        leaf_id: LeafIdType,
        ref: str | int | None = None,
        negative: bool = False,
    ) -> None:
        """Build a leaf for the set ``leaf_id``.

        :param ref: the human-readable reference; defaults to ``str(leaf_id)``
        :param negative: whether the leaf denotes the set's complement
        """
        self.id = leaf_id
        self.ref = ref or str(leaf_id)
        self.negative = bool(negative)
        self.key: tuple[LeafIdType, bool] = (leaf_id, self.negative)

        self.subsets: set[LeafIdType] = {leaf_id}  # all the leaf ids that are <= self
        self.supersets: set[LeafIdType] = {leaf_id}  # all the leaf ids that are >= self
        self.disjoints: set[LeafIdType] = set()  # all the leaf ids disjoint from self
        self.inverse: Leaf | None = None

    def __invert__(self) -> Leaf:
        """Return the complement of ``self``."""
        if self.inverse is None:
            self.inverse = Leaf(self.id, self.ref, negative=not self.negative)
            self.inverse.inverse = self
            self.inverse.subsets = self.subsets
            self.inverse.supersets = self.supersets
            self.inverse.disjoints = self.disjoints
        return self.inverse

    def is_empty(self) -> bool:
        """Return whether ``self`` is the empty set."""
        return self.ref == "*" and self.negative

    def is_universal(self) -> bool:
        """Return whether ``self`` is the universal set."""
        return self.ref == "*" and not self.negative

    def isdisjoint(self, other: Leaf) -> bool:
        """Return whether ``self`` and ``other`` have no element in common."""
        if self.negative:
            return other <= ~self
        elif other.negative:
            return self <= ~other
        else:
            return self.id in other.disjoints

    def matches(self, user_group_ids: Collection[int]) -> bool:
        """Return whether the given group ids match ``self``."""
        return (
            (self.id not in user_group_ids)
            if self.negative
            else (self.id in user_group_ids)
        )

    def __eq__(self, other: object) -> bool:
        """Return whether ``self`` and ``other`` are the same leaf."""
        return isinstance(other, Leaf) and self.key == other.key

    def __le__(self, other: Leaf) -> bool:
        """Return whether ``self`` is a subset of ``other``."""
        if self.is_empty() or other.is_universal():
            return True
        elif self.is_universal() or other.is_empty():
            return False
        elif self.negative:
            return other.negative and ~other <= ~self
        elif other.negative:
            return self.id in other.disjoints
        else:
            return self.id in other.subsets

    def __lt__(self, other: Leaf) -> bool:
        """Return whether ``self`` is a strict subset of ``other``."""
        return self != other and self <= other

    def __hash__(self) -> int:
        """Return the hash of ``self``."""
        return hash(self.key)


class UnknownId(str):
    """Special id object for unknown leaves.

    It compares as strictly greater than any other kind of id.
    """

    __slots__ = ()

    def __lt__(self, other: object) -> bool:
        """Return whether ``self`` sorts before ``other``."""
        if isinstance(other, UnknownId):
            return super().__lt__(other)
        return False

    def __gt__(self, other: object) -> bool:
        """Return whether ``self`` sorts after ``other``."""
        if isinstance(other, UnknownId):
            return super().__gt__(other)
        return True


type LeafIdType = int | Literal["*"] | UnknownId

# constants
UNIVERSAL_LEAF = Leaf("*")
EMPTY_LEAF = ~UNIVERSAL_LEAF

EMPTY_INTER = Inter([EMPTY_LEAF])
UNIVERSAL_INTER = Inter()

EMPTY_UNION = Union()
UNIVERSAL_UNION = Union([UNIVERSAL_INTER])

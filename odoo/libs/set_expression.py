import ast
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict, cast

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable


__all__ = ["SetDefinitions", "SetExpressionError"]
"""Only these two leave the module.  `SetExpression`, `SetDefinition`,
`UnknownId`, the EMPTY_*/UNIVERSAL_* singletons and `MAX_INTERSECTION_TERMS`
are the vocabulary `SetDefinitions` is built from, not its surface."""

MAX_INTERSECTION_TERMS = 100_000


class SetExpressionError(ValueError):
    pass


class SetDefinition(TypedDict):
    ref: str
    supersets: NotRequired[Collection[int]]
    disjoints: NotRequired[Collection[int]]


class SetDefinitions:
    __slots__ = ("__leaves",)

    def __init__(self, definitions: dict[int, SetDefinition]) -> None:
        self.__leaves: dict[int | str, Leaf] = {}

        for leaf_id, info in definitions.items():
            ref = info["ref"]
            if ref == "*":
                msg = "The set reference '*' is reserved for the universal set."
                raise ValueError(msg)
            leaf = Leaf(leaf_id, ref)
            self.__leaves[leaf_id] = leaf
            self.__leaves[ref] = leaf

        subsets = {leaf.id: leaf.subsets for leaf in self.__leaves.values()}
        supersets = {leaf.id: leaf.supersets for leaf in self.__leaves.values()}
        for leaf_id, info in definitions.items():
            for direct_greater_id in info.get("supersets", ()):
                smaller_ids = subsets[leaf_id]
                greater_ids = supersets[direct_greater_id]
                for smaller_id in smaller_ids:
                    supersets[smaller_id].update(greater_ids)
                for greater_id in greater_ids:
                    subsets[greater_id].update(smaller_ids)

        disjoints = {leaf.id: leaf.disjoints for leaf in self.__leaves.values()}
        for leaf_id, info in definitions.items():
            for distinct_id in info.get("disjoints", set()):
                left_ids = subsets[leaf_id]
                right_ids = subsets[distinct_id]
                for left_id in left_ids:
                    disjoints[left_id].update(right_ids)
                for right_id in right_ids:
                    disjoints[right_id].update(left_ids)

    @property
    def empty(self) -> SetExpression:
        return EMPTY_UNION

    @property
    def universe(self) -> SetExpression:
        return UNIVERSAL_UNION

    def parse(self, refs: str, raise_if_not_found: bool = True) -> SetExpression:
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
        if keep_subsets:
            ids = set(ids)
            ids = [
                leaf_id
                for leaf_id in ids
                if not any((self.__leaves[leaf_id].subsets - {leaf_id}) & ids)
            ]
        return Union(Inter([self.__leaves[leaf_id]]) for leaf_id in ids)

    def from_key(self, key: str) -> SetExpression:
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
        if ref == "*":
            return UNIVERSAL_LEAF.id
        leaf = self.__leaves.get(ref)
        return None if leaf is None else leaf.id

    def __get_leaf(self, ref: str | int, raise_if_not_found: bool = True) -> Leaf:
        if ref == "*":
            return UNIVERSAL_LEAF
        if not raise_if_not_found and ref not in self.__leaves:
            return Leaf(UnknownId(ref), ref)
        return self.__leaves[ref]

    def get_superset_ids(self, ids: Iterable[int]) -> list[int]:
        return sorted(
            cast(
                "set[int]",
                {
                    sup_id
                    for id_ in ids
                    if id_ in self.__leaves
                    for sup_id in self.__leaves[id_].supersets
                    if sup_id != id_
                },
            )
        )

    def get_subset_ids(self, ids: Iterable[int]) -> list[int]:
        return sorted(
            cast(
                "set[int]",
                {
                    sub_id
                    for id_ in ids
                    if id_ in self.__leaves
                    for sub_id in self.__leaves[id_].subsets
                    if sub_id != id_
                },
            )
        )


class SetExpression(ABC):
    @abstractmethod
    def is_empty(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def is_universal(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def invert_intersect(self, factor: SetExpression) -> SetExpression | None:
        raise NotImplementedError

    @abstractmethod
    def matches(self, user_group_ids: Iterable[int]) -> bool:
        raise NotImplementedError

    @property
    @abstractmethod
    def key(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def __and__(self, other: SetExpression) -> SetExpression:
        raise NotImplementedError

    @abstractmethod
    def __or__(self, other: SetExpression) -> SetExpression:
        raise NotImplementedError

    @abstractmethod
    def __invert__(self) -> SetExpression:
        raise NotImplementedError

    @abstractmethod
    def __eq__(self, other: object) -> bool:
        raise NotImplementedError

    @abstractmethod
    def __le__(self, other: SetExpression) -> bool:
        raise NotImplementedError

    @abstractmethod
    def __lt__(self, other: SetExpression) -> bool:
        raise NotImplementedError

    @abstractmethod
    def __hash__(self) -> int:
        raise NotImplementedError


class Union(SetExpression):
    def __init__(self, inters: Iterable[Inter] = (), optimal: bool = False) -> None:
        if inters and not optimal:
            inters = self.__combine((), inters)
        self.__inters = sorted(inters, key=lambda inter: inter.key)
        self.__key = str(tuple(inter.key for inter in self.__inters))
        self.__hash = hash(self.__key)

    @property
    def key(self) -> str:
        return self.__key

    @staticmethod
    def __combine(
        inters: Iterable[Inter], inters_to_add: Iterable[Inter]
    ) -> list[Inter]:
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
        return not self.__inters

    def is_universal(self) -> bool:
        return any(item.is_universal() for item in self.__inters)

    def invert_intersect(self, factor: SetExpression) -> Union | None:
        if factor == self:
            return UNIVERSAL_UNION

        rfactor = ~factor
        if rfactor.is_empty() or rfactor.is_universal():
            return None
        rself = ~self

        if not isinstance(rfactor, Union):
            raise TypeError(f"Expected Union, got {type(rfactor).__name__}")
        rfactor_inters = frozenset(rfactor.__inters)
        inters = [inter for inter in rself.__inters if inter not in rfactor_inters]
        if len(rself.__inters) - len(inters) != len(rfactor.__inters):
            return None

        rself_value = Union(inters)
        return ~rself_value

    def __and__(self, other: SetExpression) -> Union:
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
        if self.is_empty():
            return UNIVERSAL_UNION
        if self.is_universal():
            return EMPTY_UNION

        estimate = 1
        for inter in self.__inters:
            estimate *= max(1, len(inter.leaves))
            if estimate > MAX_INTERSECTION_TERMS:
                raise SetExpressionError(
                    f"cannot invert set expression: De Morgan expansion exceeds "
                    f"{MAX_INTERSECTION_TERMS} terms; the input is pathological"
                )

        inverses_of_inters = [
            Union(Inter([~leaf]) for leaf in inter.leaves) for inter in self.__inters
        ]
        result = inverses_of_inters[0]
        for inverse in inverses_of_inters[1:]:
            result &= inverse

        return result

    def matches(self, user_group_ids: Iterable[int]) -> bool:
        user_group_ids = set(user_group_ids)
        if self.is_empty() or not user_group_ids:
            return False
        if self.is_universal():
            return True
        return any(inter.matches(user_group_ids) for inter in self.__inters)

    def __bool__(self) -> bool:
        raise NotImplementedError

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Union) and self.__key == other.__key

    def __le__(self, other: SetExpression) -> bool:
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
        return self != other and self.__le__(other)

    def __str__(self) -> str:
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
        return repr(self.__str__())

    def __hash__(self) -> int:
        return self.__hash


class Inter:
    __slots__ = ("key", "leaves")

    def __init__(self, leaves: Iterable[Leaf] = (), optimal: bool = False) -> None:
        if leaves and not optimal:
            leaves = self.__combine((), leaves)
        self.leaves: list[Leaf] = sorted(leaves, key=lambda leaf: leaf.key)
        self.key: tuple[tuple[LeafIdType, bool], ...] = tuple(
            leaf.key for leaf in self.leaves
        )

    @staticmethod
    def __combine(leaves: Iterable[Leaf], leaves_to_add: Iterable[Leaf]) -> list[Leaf]:
        result = list(leaves)
        for leaf_to_add in leaves_to_add:
            if leaf_to_add.is_universal():
                continue
            if any(leaf.isdisjoint(leaf_to_add) for leaf in result):
                return [EMPTY_LEAF]
            if any(leaf <= leaf_to_add for leaf in result):
                continue
            result = [leaf for leaf in result if not leaf_to_add <= leaf]
            result.append(leaf_to_add)
        return result

    def is_empty(self) -> bool:
        return any(item.is_empty() for item in self.leaves)

    def is_universal(self) -> bool:
        return not self.leaves

    def matches(self, user_group_ids: Collection[int]) -> bool:
        return all(leaf.matches(user_group_ids) for leaf in self.leaves)

    def _union_merge(self, other: Inter) -> Inter | None:
        if self.is_universal() or other <= self:
            return self
        if self <= other:
            return other

        if len(self.leaves) == len(other.leaves):
            opposite_index = None
            for index, self_leaf, other_leaf in zip(
                range(len(self.leaves)), self.leaves, other.leaves, strict=False
            ):
                if self_leaf.id != other_leaf.id:
                    return None
                if self_leaf.negative != other_leaf.negative:
                    if opposite_index is not None:
                        return None
                    opposite_index = index
            if opposite_index is not None:
                leaves = list(self.leaves)
                leaves.pop(opposite_index)
                return Inter(leaves, optimal=True)
        return None

    def __and__(self, other: Inter) -> Inter:
        if self.is_empty() or other.is_empty():
            return EMPTY_INTER
        if self.is_universal():
            return other
        if other.is_universal():
            return self
        leaves = self.__combine(self.leaves, other.leaves)
        return Inter(leaves, optimal=True)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Inter) and self.key == other.key

    def __le__(self, other: Inter) -> bool:
        return self.key == other.key or all(
            any(self_leaf <= other_leaf for self_leaf in self.leaves)
            for other_leaf in other.leaves
        )

    def __lt__(self, other: Inter) -> bool:
        return self != other and self <= other

    def __hash__(self) -> int:
        return hash(self.key)


class Leaf:
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
        self.id = leaf_id
        self.ref = ref or str(leaf_id)
        self.negative = bool(negative)
        self.key: tuple[LeafIdType, bool] = (leaf_id, self.negative)

        self.subsets: set[LeafIdType] = {leaf_id}
        self.supersets: set[LeafIdType] = {leaf_id}
        self.disjoints: set[LeafIdType] = set()
        self.inverse: Leaf | None = None

    def __invert__(self) -> Leaf:
        if self.inverse is None:
            self.inverse = Leaf(self.id, self.ref, negative=not self.negative)
            self.inverse.inverse = self
            self.inverse.subsets = self.subsets
            self.inverse.supersets = self.supersets
            self.inverse.disjoints = self.disjoints
        return self.inverse

    def is_empty(self) -> bool:
        return self.ref == "*" and self.negative

    def is_universal(self) -> bool:
        return self.ref == "*" and not self.negative

    def isdisjoint(self, other: Leaf) -> bool:
        if self.negative:
            return other <= ~self
        elif other.negative:
            return self <= ~other
        else:
            return self.id in other.disjoints

    def matches(self, user_group_ids: Collection[int]) -> bool:
        return (
            (self.id not in user_group_ids)
            if self.negative
            else (self.id in user_group_ids)
        )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Leaf) and self.key == other.key

    def __le__(self, other: Leaf) -> bool:
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
        return self != other and self <= other

    def __hash__(self) -> int:
        return hash(self.key)


class UnknownId(str):
    __slots__ = ()

    def __lt__(self, other: object) -> bool:
        if isinstance(other, UnknownId):
            return super().__lt__(other)
        return False

    def __gt__(self, other: object) -> bool:
        if isinstance(other, UnknownId):
            return super().__gt__(other)
        return True


type LeafIdType = int | Literal["*"] | UnknownId

UNIVERSAL_LEAF = Leaf("*")
EMPTY_LEAF = ~UNIVERSAL_LEAF

EMPTY_INTER = Inter([EMPTY_LEAF])
UNIVERSAL_INTER = Inter()

EMPTY_UNION = Union()
UNIVERSAL_UNION = Union([UNIVERSAL_INTER])

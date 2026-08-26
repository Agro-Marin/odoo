import ast
import unittest
from pathlib import Path

from odoo.orm.fields.base import Field


def _string_operands(node: ast.expr) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return {
            e.value
            for e in node.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        }
    return set()


PREDICATE_TYPES: dict[str, frozenset[str]] = {
    "is_x2many": frozenset({"many2many", "one2many"}),
    "is_temporal": frozenset({"date", "datetime"}),
    "is_properties": frozenset({"properties"}),
    "is_many2one": frozenset({"many2one"}),
    "is_one2many": frozenset({"one2many"}),
    "is_many2many": frozenset({"many2many"}),
    "is_many2one_reference": frozenset({"many2one_reference"}),
    "is_boolean": frozenset({"boolean"}),
    "is_integer": frozenset({"integer"}),
    "is_monetary": frozenset({"monetary"}),
    "is_date": frozenset({"date"}),
    "is_datetime": frozenset({"datetime"}),
    "is_html": frozenset({"html"}),
    "is_binary": frozenset({"binary"}),
}

UNCONVERTED: dict[str, str] = {}


class TestPredicatesMatchTheTypeStrings(unittest.TestCase):
    def test_the_registry_is_populated(self):
        self.assertGreaterEqual(
            len(Field._by_type__),
            15,
            "Field._by_type__ is unexpectedly small; the field modules may not "
            "have been imported, which would make every assertion below vacuous",
        )

    def test_each_predicate_holds_for_exactly_its_types(self):
        for predicate, want_types in PREDICATE_TYPES.items():
            for type_name, cls in sorted(Field._by_type__.items()):
                with self.subTest(predicate=predicate, type=type_name):
                    self.assertEqual(
                        bool(getattr(cls, predicate, False)),
                        type_name in want_types,
                        f"{cls.__name__}.{predicate} disagrees with "
                        f"`type == {type_name!r}`",
                    )

    def test_each_predicate_is_true_somewhere(self):
        for predicate, want_types in PREDICATE_TYPES.items():
            with self.subTest(predicate=predicate):
                answering = {
                    type_name
                    for type_name, cls in Field._by_type__.items()
                    if getattr(cls, predicate, False)
                }
                self.assertTrue(
                    answering & want_types,
                    f"no registered field type answers {predicate} -- either the "
                    f"override was lost or the field module is not imported",
                )


class TestTheMigrationIsComplete(unittest.TestCase):
    def _survivors(self) -> dict[str, list[str]]:
        root = Path(__file__).resolve().parents[1]
        repo = root.parents[1]
        found: dict[str, list[str]] = {}
        for path in sorted(root.rglob("*.py")):
            parts = path.parts
            if "tests" in parts or "__pycache__" in parts:
                continue
            rel = path.relative_to(repo).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                left = node.left
                if not (isinstance(left, ast.Attribute) and left.attr == "type"):
                    continue
                for comparator in node.comparators:
                    values = _string_operands(comparator)
                    for predicate, want in PREDICATE_TYPES.items():
                        if values and values == want:
                            found.setdefault(rel, []).append(
                                f"line {node.lineno}: {predicate}"
                            )
        return found

    def test_no_unlisted_file_still_compares_type_strings(self):
        survivors = self._survivors()
        unexpected = {f: v for f, v in survivors.items() if f not in UNCONVERTED}
        self.assertFalse(
            unexpected,
            "these compare `.type` against a set that now has a predicate; "
            "convert them, or add the file to UNCONVERTED with the reason:\n"
            + "\n".join(f"  {f}: {v}" for f, v in sorted(unexpected.items())),
        )

    def test_the_unconverted_list_has_no_stale_entries(self):
        survivors = self._survivors()
        stale = sorted(set(UNCONVERTED) - set(survivors))
        self.assertFalse(
            stale,
            f"UNCONVERTED names files with nothing left to convert: {stale}. "
            f"Remove them -- an exemption nobody needs is an exemption nobody "
            f"rereads.",
        )


class TestTheDomainStubKeepsUp(unittest.TestCase):
    """``domain/tests/test_optimize_unit.py`` restates this map, and must.

    That suite is DB-free and cannot import ``odoo.orm.fields``:
    ``fields/base.py`` imports ``odoo.orm.domain``, the package it is testing,
    so asking the real classes there is a cycle. The copy is therefore
    necessary -- but it silently fell behind the day a fifth predicate landed,
    and the optimizer reached ``field.is_many2many`` on a stub that had never
    heard of it. Read with ``ast`` rather than imported, for the same reason
    the copy exists.
    """

    STUB = (
        Path(__file__).resolve().parents[1]
        / "domain"
        / "tests"
        / "test_optimize_unit.py"
    )

    def _stub_table(self) -> dict[str, set[str]]:
        tree = ast.parse(self.STUB.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "_PREDICATES_BY_TYPE" not in targets:
                continue
            assert isinstance(node.value, ast.Dict), (
                "_PREDICATES_BY_TYPE is expected to be a dict literal"
            )
            table: dict[str, set[str]] = {}
            for key, value in zip(node.value.keys, node.value.values, strict=True):
                assert isinstance(key, ast.Constant) and isinstance(value, ast.Call), (
                    "_PREDICATES_BY_TYPE maps a literal key to a call"
                )
                assert isinstance(key.value, str)
                table[key.value] = _string_operands(value.args[0])
            return table
        self.fail(f"no _PREDICATES_BY_TYPE assignment found in {self.STUB}")
        raise AssertionError("unreachable")  # self.fail always raises

    def test_the_stub_lists_every_predicate_with_the_same_types(self):
        self.assertEqual(
            self._stub_table(),
            {name: set(types) for name, types in PREDICATE_TYPES.items()},
            f"{self.STUB.name}'s _PREDICATES_BY_TYPE has drifted from "
            f"PREDICATE_TYPES; a stub field that does not answer a predicate "
            f"raises AttributeError from inside the optimizer",
        )


class TestNoFlagLeaksThroughAResetType(unittest.TestCase):
    def _resetting_classes(self):
        for type_name, cls in sorted(Field._by_type__.items()):
            for parent in cls.__mro__[1:]:
                if not (isinstance(parent, type) and issubclass(parent, Field)):
                    continue
                parent_type = parent.__dict__.get("type")
                if parent_type is not None and parent_type != type_name:
                    yield cls, parent, type_name, parent_type

    def test_the_hazard_shape_still_exists(self):
        found = list(self._resetting_classes())
        self.assertTrue(
            found,
            "no field class resets `type` under a typed parent; either the "
            "hierarchy changed or _by_type__ is not populated, and the leak "
            "test below is now vacuous",
        )

    def test_no_predicate_flag_is_inherited_across_a_reset_type(self):
        for cls, parent, type_name, parent_type in self._resetting_classes():
            for predicate, want_types in PREDICATE_TYPES.items():
                if not getattr(parent, predicate, False):
                    continue
                if type_name in want_types:
                    continue
                # The parent claims it and the child's type is not covered, so
                # the child has to say so. Checked on the child rather than on
                # the parent: a parent declaring a predicate its subclasses do
                # not share is fine -- what is not fine is the subclass staying
                # silent about it.
                with self.subTest(cls=cls.__name__, predicate=predicate):
                    self.assertFalse(
                        getattr(cls, predicate, False),
                        f"{cls.__name__} (type={type_name!r}) inherits "
                        f"{predicate} from {parent.__name__} "
                        f"(type={parent_type!r}), which is exactly the leak "
                        f"fields/_field_sql.py warns about: a flag is inherited, "
                        f"a type string is not. Declare {predicate} on the "
                        f"narrower class, or keep the type comparison here.",
                    )


class TestInstancePredicates(unittest.TestCase):
    def test_delegating_follows_the_delegate_flag(self):
        from odoo.orm.fields.relational import Many2one

        field = Many2one("res.users")
        self.assertFalse(field.is_delegating)
        field.delegate = True
        self.assertTrue(field.is_delegating)

    def test_attachment_backed_follows_the_attachment_flag(self):
        from odoo.orm.fields.binary import Binary

        field = Binary()
        self.assertTrue(
            field.is_attachment_backed, "Binary stores in an attachment by default"
        )
        field.attachment = False
        self.assertFalse(field.is_attachment_backed)

    def test_a_plain_field_answers_neither(self):
        from odoo.orm.fields.textual import Char

        char = Char()
        self.assertFalse(char.is_delegating)
        self.assertFalse(char.is_attachment_backed)


if __name__ == "__main__":
    unittest.main()

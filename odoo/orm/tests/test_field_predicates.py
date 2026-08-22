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
                with self.subTest(cls=cls.__name__, predicate=predicate):
                    if not getattr(parent, predicate, False):
                        continue
                    self.assertIn(
                        type_name,
                        want_types,
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

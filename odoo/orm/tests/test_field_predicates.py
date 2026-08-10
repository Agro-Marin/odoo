"""The predicates that replaced ``field.type == "..."`` must not widen.

`Field` carries a class hierarchy *and* a string type tag, and the fork is
migrating the second onto the first: `is_x2many`, `is_temporal`,
`is_properties`, `is_delegating`, `is_attachment_backed`. Each replaces a
comparison against one or more `type` strings.

**The migration has a hazard, and it is written down at the one site that
refused it** (`fields/_field_sql.py`, the company-dependent column branch):

    A `type` check, NOT a class flag, and it must stay one. `type` is leaf
    identity that subclasses reset; a boolean class attribute is inherited.

That asymmetry is the whole risk. `Many2oneReference` subclasses `Integer` and
resets `type` to `"many2one_reference"`; had `Integer` carried an
`is_fixed_width_column = True`, the subclass would have inherited it and
silently changed the SQL for every m2o-reference column. Nothing checked that,
so this file does.

Two invariants, both measured over `Field._by_type__` -- every field class that
has ever been imported, not merely the ones some registry happens to
instantiate:

1. each predicate agrees, class by class, with the type-string test it replaced;
2. no class inherits a predicate flag from a parent whose `type` it resets.

The second is the one that catches the hazard before it ships: it fails on a new
subclass the day it is written, rather than on the SQL it quietly changed.
"""

import ast
import unittest
from pathlib import Path

from odoo.orm.fields.base import Field


def _string_operands(node: ast.expr) -> set[str]:
    """The string literals *node* compares against, as a set.

    Handles the constant and the container forms alike, so a reversed tuple is
    the same fact as an ordered one -- which is precisely what the regex sweep
    this test replaces could not see.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return {
            e.value
            for e in node.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        }
    return set()


#: ``predicate -> the type strings it must be true for, and no others``.
#:
#: Deliberately spelled as the literal type strings rather than derived from the
#: classes, so this is a second, independent statement of the intent -- deriving
#: it from the same class attributes the code reads would make the test agree
#: with any bug it is meant to catch.
PREDICATE_TYPES: dict[str, frozenset[str]] = {
    "is_x2many": frozenset({"many2many", "one2many"}),
    "is_temporal": frozenset({"date", "datetime"}),
    "is_properties": frozenset({"properties"}),
    "is_many2one": frozenset({"many2one"}),
}

#: Files still comparing `.type` against a migrated set, with the reason.
#:
#: A half-migrated cluster is worse than either end state -- two ways to ask one
#: question, and a reader cannot tell which is current. So the sweep below fails
#: on any survivor that is not listed here, and the list is the remaining work
#: rather than a place to put inconvenient sites.
UNCONVERTED: dict[str, str] = {}
"""Files still comparing `.type` against a migrated set, with the reason.

Empty, and the second test below keeps it that way honestly: an entry naming a
file with nothing left to convert fails, so this cannot quietly become a place
to put inconvenient sites. It held ``orm/domain/optimizations.py`` for one
commit, while another session had uncommitted work in it.
"""


class TestPredicatesMatchTheTypeStrings(unittest.TestCase):
    def test_the_registry_is_populated(self):
        """A predicate suite over an empty registry proves nothing."""
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
        """A predicate nothing answers True is a stub, not a migration."""
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
    """No `.type` comparison against a migrated set may survive unlisted.

    This exists because a regex sweep silently missed four sites and I reported
    the clusters as complete on the strength of the sweep rather than by
    measuring afterwards. Two spellings defeated it: a reversed tuple
    (``field.type in ("datetime", "date")``) and a subscript receiver
    (``fields[name].type != "properties"``), neither matched by a pattern
    written for ``field.type in ("date", "datetime")``.

    An AST walk cannot be fooled that way, and running it as a test means the
    next cluster is finished or explicitly unfinished, never accidentally
    half-done.
    """

    def _survivors(self) -> dict[str, list[str]]:
        root = Path(__file__).resolve().parents[1]  # odoo/orm
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
        """A file that has been converted must leave the list."""
        survivors = self._survivors()
        stale = sorted(set(UNCONVERTED) - set(survivors))
        self.assertFalse(
            stale,
            f"UNCONVERTED names files with nothing left to convert: {stale}. "
            f"Remove them -- an exemption nobody needs is an exemption nobody "
            f"rereads.",
        )


class TestNoFlagLeaksThroughAResetType(unittest.TestCase):
    """The hazard `fields/_field_sql.py` names, checked rather than remembered."""

    def _resetting_classes(self):
        """``(cls, parent)`` for every class that resets `type` under a parent."""
        for type_name, cls in sorted(Field._by_type__.items()):
            for parent in cls.__mro__[1:]:
                if not (isinstance(parent, type) and issubclass(parent, Field)):
                    continue
                parent_type = parent.__dict__.get("type")
                if parent_type is not None and parent_type != type_name:
                    yield cls, parent, type_name, parent_type

    def test_the_hazard_shape_still_exists(self):
        """If nothing resets `type` any more, this suite has stopped testing."""
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
    """`is_delegating` / `is_attachment_backed` are per-instance, not per-class.

    They report an attribute rather than a fixed class answer, so they are set
    on the instance here. Passing ``delegate=True`` to the constructor would
    *not* work and the first draft of this file assumed it would:
    ``Field.__init__`` stashes its kwargs in ``_args__`` and
    ``_setup_attrs__`` applies them when the field is set up on a model, so
    before setup the instance still carries the class default. The predicate
    reads the resolved attribute, which is the state every caller sees.
    """

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

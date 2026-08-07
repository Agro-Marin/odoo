import importlib.util
import logging
import pathlib
import unittest

_SCRIPT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "upgrade_code"
    / "18.1-00-sql-constraint.py"
)

# `odoo/upgrade_code/` had no tests at all -- nine dated source-rewriting
# scripts that run over OTHER checkouts, in place, with nothing exercising them.
# This covers the one with the two sharpest failure modes, both of which were
# live before this file existed:
#
#   1. `ast.literal_eval` raises **ValueError** (not SyntaxError) for any
#      non-literal node. The most common real `_sql_constraints` entry has a
#      translated message -- ('uniq', 'unique(code)', _('...')) -- whose third
#      element is a Call. The script caught only SyntaxError, so that ValueError
#      escaped `re.sub` and `upgrade()` and killed the whole run partway through
#      the file list, leaving everything already processed rewritten on disk.
#
#   2. The rewrite names each new constraint `_{name}`. A constraint called
#      "name" therefore emitted `_name = models.Constraint(...)`, silently
#      REDEFINING the model's `_name` and destroying its identity. Same for
#      _table, _inherit, _order and 15 other BaseModel attributes.
#
# Both were reported in the round-1 audit and are reproduced here as tests so
# they cannot come back.


def _load():
    spec = importlib.util.spec_from_file_location("sql_constraint_upgrade", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _File:
    def __init__(self, content: str, name: str = "models/m.py"):
        self.path = pathlib.Path(name)
        self.content = content


def _run(source: str) -> str:
    module = _load()
    handle = _File(source)
    module.upgrade([handle])
    return handle.content


class TestSqlConstraintUpgrade(unittest.TestCase):
    def test_plain_constraint_is_converted(self):
        out = _run(
            "class M(models.Model):\n"
            "    _sql_constraints = [('uniq', 'unique(code)', 'Code must be unique')]\n"
        )
        self.assertIn("_uniq = models.Constraint(", out)
        self.assertIn("'unique(code)'", out)
        self.assertNotIn("_sql_constraints", out)

    def test_constraint_without_a_message_is_converted(self):
        out = _run(
            "class M(models.Model):\n"
            "    _sql_constraints = [('uniq', 'unique(code)')]\n"
        )
        self.assertIn("_uniq = models.Constraint(", out)

    def test_translated_message_is_left_alone_and_does_not_abort(self):
        source = (
            "class M(models.Model):\n"
            "    _sql_constraints = [('uniq', 'unique(code)', _('Must be unique'))]\n"
        )
        # The assertion that matters is that this RETURNS at all: it used to
        # raise ValueError out of upgrade().
        out = _run(source)
        self.assertEqual(out, source)

    def test_one_unconvertible_file_does_not_stop_the_others(self):
        module = _load()
        bad = _File(
            "class A(models.Model):\n"
            "    _sql_constraints = [('u', 'unique(a)', _('x'))]\n",
            "models/a.py",
        )
        good = _File(
            "class B(models.Model):\n"
            "    _sql_constraints = [('u', 'unique(b)', 'plain')]\n",
            "models/b.py",
        )
        module.upgrade([bad, good])
        self.assertIn("_sql_constraints", bad.content)
        self.assertIn("_u = models.Constraint(", good.content)

    def test_constraint_named_like_a_model_attribute_is_refused(self):
        for reserved in ("name", "table", "inherit", "order", "rec_name"):
            with self.subTest(constraint=reserved):
                source = (
                    "class M(models.Model):\n"
                    "    _name = 'my.model'\n"
                    f"    _sql_constraints = [('{reserved}', 'unique(x)', 'dup')]\n"
                )
                with self.assertLogs(level=logging.WARNING) as captured:
                    out = _run(source)
                self.assertEqual(out, source)
                self.assertTrue(
                    any("clobber" in m for m in captured.output),
                    f"no warning explaining why {reserved!r} was skipped",
                )

    def test_the_model_keeps_its_identity(self):
        # The concrete disaster: two _name assignments, the second winning.
        out = _run(
            "class M(models.Model):\n"
            "    _name = 'my.model'\n"
            "    _sql_constraints = [('name', 'unique(name)', 'dup')]\n"
        )
        self.assertEqual(out.count("_name ="), 1)
        self.assertIn("_name = 'my.model'", out)

    def test_reserved_set_covers_the_real_model_attributes(self):
        module = _load()
        for attr in ("_name", "_table", "_inherit", "_inherits", "_order", "_rec_name"):
            self.assertIn(attr, module._RESERVED_MODEL_ATTRIBUTES)

    def test_malformed_source_is_still_left_alone(self):
        source = "class M(models.Model):\n    _sql_constraints = [('u', 'unique(a)',]\n"
        self.assertEqual(_run(source), source)


if __name__ == "__main__":
    unittest.main()

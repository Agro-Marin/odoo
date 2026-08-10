import importlib.util
import logging
import pathlib
import unittest

_SCRIPT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "upgrade_code"
    / "18.1-00-sql-constraint.py"
)


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

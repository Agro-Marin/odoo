import importlib.util
import pathlib
import unittest

_SCRIPT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "upgrade_code"
    / "18.5-00-deprecated-properties.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("deprecated_properties", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _File:
    def __init__(self, content: str, name: str = "models/m.py"):
        self.path = pathlib.Path(name)
        self.content = content


def _run(source: str) -> str:
    handle = _File(source)
    _load().upgrade([handle])
    return handle.content


class TestDeprecatedPropertiesUpgrade(unittest.TestCase):
    def test_recordset_reads_are_converted(self):
        for old, new in (
            ("self._cr", "self.env.cr"),
            ("self._uid", "self.env.uid"),
            ("self._context", "self.env.context"),
            ("record._context", "record.env.context"),
        ):
            with self.subTest(expr=old):
                self.assertEqual(_run(f"x = {old}\n"), f"x = {new}\n")

    def test_several_on_one_line_are_all_converted(self):
        self.assertEqual(
            _run("a = self._cr; b = self._uid\n"),
            "a = self.env.cr; b = self.env.uid\n",
        )

    def test_already_on_env_is_left_alone(self):
        for src in ("cr = self.env._cr\n", "other.env._cr.execute(q)\n"):
            with self.subTest(src=src.strip()):
                self.assertEqual(_run(src), src)

    def test_string_literals_are_not_rewritten(self):
        src = "raise UserError('use ._context instead')\n"
        self.assertEqual(_run(src), src)

    def test_docstrings_are_not_rewritten(self):
        src = 'def f():\n    """Do not touch ._cr in prose."""\n    return 1\n'
        self.assertEqual(_run(src), src)

    def test_comments_are_not_rewritten(self):
        src = "# self._cr is deprecated, use env.cr\nx = 1\n"
        self.assertEqual(_run(src), src)

    def test_attribute_definitions_are_not_rewritten(self):
        src = "class A:\n    _context = {}\n"
        self.assertEqual(_run(src), src)

    def test_assignment_targets_are_not_rewritten(self):
        src = "conn._cr = make_cursor()\n"
        self.assertEqual(_run(src), src)

    def test_comparisons_are_still_reads(self):
        self.assertEqual(
            _run("if a._uid == 1:\n    pass\n"), "if a.env.uid == 1:\n    pass\n"
        )

    def test_unparseable_source_is_left_untouched(self):
        src = "def broken(:\n    pass\n"
        self.assertEqual(_run(src), src)

    def test_surrounding_formatting_is_preserved(self):
        src = "def f():\n    # keep\n    return  self._context   # trailing\n"
        self.assertEqual(
            _run(src),
            "def f():\n    # keep\n    return  self.env.context   # trailing\n",
        )

    def test_non_python_files_are_skipped(self):
        handle = _File("self._cr\n", "views/v.xml")
        _load().upgrade([handle])
        self.assertEqual(handle.content, "self._cr\n")


if __name__ == "__main__":
    unittest.main()

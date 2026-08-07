import importlib.util
import pathlib
import unittest

_SCRIPT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "upgrade_code"
    / "18.5-00-deprecated-properties.py"
)

# This script converts the deprecated recordset properties `._cr`, `._uid` and
# `._context` to `.env.cr` / `.env.uid` / `.env.context`. It was a bare regex
# over raw source:
#
#     re.compile(r"\._(cr|uid|context)\b").sub(r".env.\1", content)
#
# which is unsound in ways that produce code strictly worse than the input.
# Measured against seven realistic shapes, five were mis-rewritten and three of
# those five no longer run:
#
#     self.env._cr           -> self.env.env.cr        (broken)
#     other.env._cr.execute  -> other.env.env.cr       (broken)
#     conn._cr = cursor      -> conn.env.cr = cursor   (broken; conn has no env)
#     '...use ._context...'  -> '...use .env.context'  (rewrites a string)
#     # self._cr deprecated  -> # self.env.cr ...      (rewrites a comment)
#
# These scripts run IN PLACE over other people's checkouts, so "mostly right" is
# not a safe default. The rewrite is now driven by `tokenize`, which cannot see
# inside strings or comments and exposes the neighbouring tokens.


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
        # The worst of the old failures: env._cr -> env.env.cr, which raises.
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
        # `record.env.cr = ...` is not a thing, so `x._cr = ...` is some other
        # object that happens to use the name.
        src = "conn._cr = make_cursor()\n"
        self.assertEqual(_run(src), src)

    def test_comparisons_are_still_reads(self):
        self.assertEqual(_run("if a._uid == 1:\n    pass\n"), "if a.env.uid == 1:\n    pass\n")

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

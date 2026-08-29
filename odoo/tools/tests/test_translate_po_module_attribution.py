import io
import textwrap
import unittest

from odoo.tools.translate import PoFileReader

_HEADER = 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n\n'


def _read(body: str) -> list[dict]:
    source = io.BytesIO((_HEADER + textwrap.dedent(body)).encode())
    source.name = "x.po"
    return list(PoFileReader(source))


def _by_type(rows: list[dict]) -> dict[str, dict]:
    return {row["type"]: row for row in rows}


_MODEL_FIRST = """\
#. module: my_module
#: model:ir.ui.view,arch_db:other_module.some_view
#: code:addons/my_module/models/thing.py:0
msgid "Description"
msgstr "Descripcion"
"""

_CODE_FIRST = """\
#. module: my_module
#: code:addons/my_module/models/thing.py:0
#: model:ir.ui.view,arch_db:other_module.some_view
msgid "Description"
msgstr "Descripcion"
"""


class TestModuleAttribution(unittest.TestCase):
    def test_a_code_occurrence_keeps_the_module_its_comment_names(self):
        rows = _by_type(_read(_MODEL_FIRST))
        self.assertEqual(rows["code"]["module"], "my_module")

    def test_a_model_occurrence_keeps_the_module_of_its_xmlid(self):
        rows = _by_type(_read(_MODEL_FIRST))
        self.assertEqual(rows["model"]["module"], "other_module")

    def test_attribution_does_not_depend_on_occurrence_order(self):
        self.assertEqual(
            {t: r["module"] for t, r in _by_type(_read(_MODEL_FIRST)).items()},
            {t: r["module"] for t, r in _by_type(_read(_CODE_FIRST)).items()},
        )

    def test_a_code_only_entry_is_unaffected(self):
        rows = _read("""\
            #. module: my_module
            #: code:addons/my_module/models/thing.py:0
            msgid "X"
            msgstr "Y"
            """)
        self.assertEqual(rows[0]["module"], "my_module")


class TestCommentsColumn(unittest.TestCase):
    def test_both_module_and_modules_lines_are_stripped(self):
        for spelling in ("module", "modules"):
            with self.subTest(spelling=spelling):
                rows = _read(f"""\
                    #. {spelling}: my_module
                    #. a real note
                    #: code:addons/my_module/models/thing.py:0
                    msgid "X"
                    msgstr "Y"
                    """)
                self.assertEqual(rows[0]["comments"], "a real note")


if __name__ == "__main__":
    unittest.main()

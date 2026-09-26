import tempfile
import textwrap
import unittest
from pathlib import Path

from odoo.tools.translate import PoFileReader

_HEADER = 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n\n'


class TestPoFileReaderTemplate(unittest.TestCase):
    def _read(self, pot_body: str, po_body: str) -> dict[str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            i18n = Path(tmp, "mod_a", "i18n")
            i18n.mkdir(parents=True)
            Path(i18n, "mod_a.pot").write_text(
                _HEADER + textwrap.dedent(pot_body), encoding="utf-8"
            )
            po_path = Path(i18n, "fr.po")
            po_path.write_text(_HEADER + textwrap.dedent(po_body), encoding="utf-8")
            return {row["src"]: row["value"] for row in PoFileReader(str(po_path))}

    def test_a_term_the_template_lacks_is_still_read(self):
        rows = self._read(
            """\
            #. module: mod_a
            #: code:addons/mod_a/a.py:0
            msgid "Old"
            msgstr ""
            """,
            """\
            #. module: mod_a
            #: code:addons/mod_a/a.py:0
            msgid "Old"
            msgstr "Ancien"

            #. module: mod_a
            #: code:addons/mod_a/a.py:0
            msgid "New"
            msgstr "Nouveau"
            """,
        )
        self.assertEqual(rows, {"Old": "Ancien", "New": "Nouveau"})

    def test_an_obsolete_duplicate_never_overrides_the_live_translation(self):
        po_body = """\
            #. module: mod_a
            #: code:addons/mod_a/a.py:0
            msgid "Fiscal Years"
            msgstr "Ejercicios fiscales"

            #~ msgid "Fiscal Years"
            #~ msgstr "Años fiscales"
            """
        pot_entry = """\
            #. module: mod_a
            #: code:addons/mod_a/a.py:0
            msgid "Fiscal Years"
            msgstr ""
            """
        for pot_body in (pot_entry, pot_entry.replace("Fiscal Years", "Other")):
            with self.subTest(template_has_msgid="Fiscal Years" in pot_body):
                rows = self._read(pot_body, po_body)
                self.assertEqual(rows.get("Fiscal Years"), "Ejercicios fiscales")

    def test_an_obsolete_entry_the_template_carries_is_read_until_merged(self):
        rows = self._read(
            """\
            #. module: mod_a
            #: code:addons/mod_a/a.py:0
            msgid "Fiscal Years"
            msgstr ""
            """,
            """\
            #~ msgid "Fiscal Years"
            #~ msgstr "Años fiscales"
            """,
        )
        self.assertEqual(rows, {"Fiscal Years": "Años fiscales"})

    def test_the_template_refreshes_occurrences(self):
        with tempfile.TemporaryDirectory() as tmp:
            i18n = Path(tmp, "mod_a", "i18n")
            i18n.mkdir(parents=True)
            Path(i18n, "mod_a.pot").write_text(
                _HEADER
                + "#: model:res.partner.tag,name:mod_a.tag_new\n"
                + 'msgid "Tag"\nmsgstr ""\n',
                encoding="utf-8",
            )
            po_path = Path(i18n, "fr.po")
            po_path.write_text(
                _HEADER
                + "#: model:res.partner.tag,name:mod_a.tag_old\n"
                + 'msgid "Tag"\nmsgstr "Étiquette"\n',
                encoding="utf-8",
            )
            rows = list(PoFileReader(str(po_path)))
        self.assertEqual([row["imd_name"] for row in rows], ["tag_new"])


if __name__ == "__main__":
    unittest.main()

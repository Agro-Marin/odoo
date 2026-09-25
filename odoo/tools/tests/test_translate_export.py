import io
import tarfile
import tempfile
import typing
import unittest
from pathlib import Path
from unittest.mock import patch

from odoo.tools.translate import (
    PoFileWriter,
    TarFileWriter,
    TranslationModuleReader,
    get_po_file_stem,
    merge_po_template,
)

_MODULES = [f"module_{name}" for name in "qwertyuiopasdfghjklz"]


def _row(module, src="Term"):
    return (module, "code", "addons/x.py", 0, src, "", ())


class TestPoFileWriterHeader(unittest.TestCase):
    def test_header_lists_modules_in_sorted_order(self):
        buffer = io.BytesIO()
        PoFileWriter(buffer, lang=None).write_rows([_row(m) for m in _MODULES])
        listed = [
            line.removeprefix("# \t* ")
            for line in buffer.getvalue().decode().splitlines()
            if line.startswith("# \t* ")
        ]
        self.assertEqual(listed, sorted(_MODULES))


_PREVIOUS = """\
# Translation of Odoo Server.
# This file contains the translation of the following modules:
# * mod_a
#
# Translators:
# Ana Translator <ana@example.com>, 2025
msgid ""
msgstr ""
"Project-Id-Version: Odoo Server 19.0\\n"
"POT-Creation-Date: 2025-01-01 00:00+0000\\n"
"Last-Translator: Ana Translator <ana@example.com>\\n"
"Language: fr\\n"
"Plural-Forms: nplurals=2; plural=n > 1;\\n"

#. module: mod_a
#: code:addons/mod_a/a.py:0
#, python-format
msgid "Term"
msgstr "Terme"

#. module: mod_a
#: code:addons/mod_a/a.py:0
msgid "Gone"
msgstr "Parti"
"""


def _write_po(rows, lang="fr_FR", previous=None):
    buffer = io.BytesIO()
    PoFileWriter(buffer, lang=lang, previous=previous).write_rows(rows)
    return buffer.getvalue().decode()


class TestPoFileWriterTranslations(unittest.TestCase):
    def test_identity_translation_is_kept(self):
        written = _write_po([("mod_a", "code", "addons/mod_a/a.py", 0, "OK", "OK", ())])
        self.assertIn('msgid "OK"\nmsgstr "OK"\n', written)

    def test_previous_header_is_kept_verbatim(self):
        written = _write_po(
            [("mod_a", "code", "addons/mod_a/a.py", 0, "Term", "Terme", ())],
            previous=_PREVIOUS,
        )
        self.assertTrue(written.startswith(_PREVIOUS[: _PREVIOUS.index("\n\n") + 2]))
        self.assertIn('#, python-format\nmsgid "Term"\nmsgstr "Terme"\n', written)

    def test_vanished_translation_turns_obsolete(self):
        written = _write_po(
            [("mod_a", "code", "addons/mod_a/a.py", 0, "Term", "Terme", ())],
            previous=_PREVIOUS,
        )
        self.assertIn('#~ msgid "Gone"\n#~ msgstr "Parti"\n', written)

    def test_template_header_is_regenerated(self):
        written = _write_po(
            [("mod_a", "code", "addons/mod_a/a.py", 0, "Term", "", ())],
            lang=None,
            previous=_PREVIOUS,
        )
        self.assertNotIn("Ana Translator", written)
        self.assertNotIn("Gone", written)


_TEMPLATE = """\
#. module: mod_a
#: code:addons/mod_a/b.py:0
msgid "New"
msgstr ""

#. module: mod_a
#. odoo-python
#: code:addons/mod_a/b.py:0
msgid "Term"
msgstr ""
"""


class TestMergePoTemplate(unittest.TestCase):
    def setUp(self):
        self.merged = merge_po_template(_PREVIOUS, _TEMPLATE, "fr")

    def test_header_is_kept(self):
        self.assertTrue(
            self.merged.startswith(_PREVIOUS[: _PREVIOUS.index("\n\n") + 2])
        )

    def test_translation_takes_the_template_occurrences(self):
        self.assertIn(
            "#. module: mod_a\n#. odoo-python\n#: code:addons/mod_a/b.py:0\n"
            '#, python-format\nmsgid "Term"\nmsgstr "Terme"\n',
            self.merged,
        )

    def test_new_term_is_untranslated(self):
        self.assertIn('msgid "New"\nmsgstr ""\n', self.merged)

    def test_vanished_translation_turns_obsolete(self):
        self.assertTrue(self.merged.endswith('#~ msgid "Gone"\n#~ msgstr "Parti"\n'))

    def test_obsolete_translation_is_revived(self):
        revived = merge_po_template(
            self.merged, _TEMPLATE.replace('"New"', '"Gone"'), "fr"
        )
        self.assertIn('msgid "Gone"\nmsgstr "Parti"\n', revived)
        self.assertNotIn("#~", revived)


class TestPoFileStem(unittest.TestCase):
    ISO_CODES = {
        "ca_ES": "ca_ES",
        "de_DE": "de",
        "de_CH": "de_CH",
        "es_ES": "es",
        "es_419": "es_419",
        "es_CL": "es_CL",
        "ko_KP": "ko_KP",
        "ko_KR": "ko_KR",
        "pt_PT": "pt",
        "pt_BR": "pt_BR",
        "sr@latin": "sr@latin",
        "zh_CN": "zh_CN",
        "zh_TW": "zh_TW",
    }

    def _stem(self, lang, existing=()):
        return get_po_file_stem(lang, self.ISO_CODES, set(existing))

    def test_existing_file_names_the_language(self):
        existing = {"ca", "de", "es", "es_419", "es_CL", "ko", "sr@latin", "zh_CN"}
        expected = {
            "ca_ES": "ca",
            "de_DE": "de",
            "es_ES": "es",
            "es_419": "es_419",
            "es_CL": "es_CL",
            "ko_KR": "ko",
            "sr@latin": "sr@latin",
            "zh_CN": "zh_CN",
        }
        self.assertEqual(
            {lang: self._stem(lang, existing) for lang in expected}, expected
        )

    def test_a_base_file_belongs_to_its_main_language_only(self):
        existing = {"de", "es", "ko", "pt"}
        for lang in ("de_CH", "es_CL", "ko_KP", "pt_BR"):
            with self.subTest(lang=lang):
                self.assertEqual(self._stem(lang, existing), lang)

    def test_new_file(self):
        expected = {
            "ca_ES": "ca",
            "de_DE": "de",
            "de_CH": "de_CH",
            "ko_KR": "ko_KR",
            "pt_BR": "pt_BR",
            "zh_CN": "zh_CN",
        }
        self.assertEqual({lang: self._stem(lang) for lang in expected}, expected)


class TestTarFileWriter(unittest.TestCase):
    def test_archive_holds_one_file_per_module(self):
        buffer = io.BytesIO()
        TarFileWriter(buffer, lang="fr_FR").write_rows([_row("mod_a"), _row("mod_b")])
        buffer.seek(0)
        with tarfile.open(fileobj=buffer, mode="r:gz") as tar:
            self.assertEqual(
                sorted(tar.getnames()), ["mod_a/i18n/fr_FR.po", "mod_b/i18n/fr_FR.po"]
            )

    def _archive(self, lang, root):
        buffer = io.BytesIO()
        with patch(
            "odoo.modules.get_module_path",
            lambda module, display_warning=True: (
                str(root / module) if module == "mod_a" else None
            ),
        ):
            TarFileWriter(
                buffer, lang=lang, iso_codes={"fr_FR": "fr", "fr_BE": "fr_BE"}
            ).write_rows([_row("mod_a"), _row("mod_b")])
        buffer.seek(0)
        with tarfile.open(fileobj=buffer, mode="r:gz") as tar:
            return {
                name: (tar.extractfile(name) or io.BytesIO()).read().decode()
                for name in tar.getnames()
            }

    def test_files_take_the_module_file_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mod_a" / "i18n").mkdir(parents=True)
            (root / "mod_a" / "i18n" / "fr.po").write_text(_PREVIOUS, encoding="utf-8")
            po_files = self._archive("fr_FR", root)
            pot_files = self._archive(None, root)
        self.assertEqual(sorted(po_files), ["mod_a/i18n/fr.po", "mod_b/i18n/fr.po"])
        self.assertIn("Ana Translator", po_files["mod_a/i18n/fr.po"])
        self.assertEqual(
            sorted(pot_files), ["mod_a/i18n/mod_a.pot", "mod_b/i18n/mod_b.pot"]
        )

    def test_archive_is_closed_when_a_row_fails(self):
        opened: list[typing.Any] = []
        real_open = tarfile.open

        def recording_open(*args, **kwargs):
            opened.append(real_open(*args, **kwargs))
            return opened[-1]

        with patch.object(tarfile, "open", recording_open):
            writer = TarFileWriter(io.BytesIO(), lang="fr_FR")
            with self.assertRaises(ValueError):
                writer.write_rows([("mod_a", "malformed")])
        self.assertTrue(all(tar.closed for tar in opened))


class _FakeModules:
    def __init__(self):
        self.asked = []

    def _extract_resource_attachment_translations(self, module, lang):
        self.asked.append(module)
        if module == "imported_mod":
            yield (module, "code", "addons/imported_mod/a.js", 1, "Imported term")


class TestModuleReaderAttachmentTerms(unittest.TestCase):
    def _reader(self, modules):
        fake = _FakeModules()
        reader: typing.Any = TranslationModuleReader.__new__(TranslationModuleReader)
        reader._cr = None
        reader._lang = "fr_FR"
        reader.env = {"ir.module.module": fake}
        reader._to_translate = []
        reader._modules = modules
        reader._installed_modules = ["web", "imported_mod"]
        reader._path_list = []
        return reader, fake

    def test_all_asks_every_installed_module(self):
        reader, fake = self._reader(["all"])
        reader._export_translatable_resources()
        self.assertEqual(fake.asked, ["web", "imported_mod"])
        self.assertIn("Imported term", [row[4] for row in reader])

    def test_named_modules_are_asked_as_given(self):
        reader, fake = self._reader(["imported_mod"])
        reader._export_translatable_resources()
        self.assertEqual(fake.asked, ["imported_mod"])


if __name__ == "__main__":
    unittest.main()

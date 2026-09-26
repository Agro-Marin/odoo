import unittest

import polib

from odoo.tools.translate import merge_po_template

_HEADER = 'msgid ""\nmsgstr ""\n"Language: es\\n"\n\n'


def _entry(msgid, msgstr="", obsolete=False):
    return polib.POEntry(msgid=msgid, msgstr=msgstr, obsolete=obsolete).__unicode__()


def _template(*msgids):
    return _HEADER + "\n".join(
        "#. module: mod_a\n#: model_terms:ir.ui.view,arch_db:mod_a.view\n"
        + _entry(msgid)
        for msgid in msgids
    )


def _merge(template, *entries):
    merged = merge_po_template(_HEADER + "\n".join(entries), template, "es")
    return polib.pofile(merged)


def _live(pofile):
    return {e.msgid: e.msgstr for e in pofile if not e.obsolete}


class TestMergeWhitespaceDrift(unittest.TestCase):
    def test_an_identity_translation_takes_the_new_indentation(self):
        new = ".\n                <br/>\n                --"
        merged = _merge(
            _template(new), _entry(".\n    <br/>\n    --", ".\n    <br/>\n    --")
        )
        self.assertEqual(_live(merged), {new: new})

    def test_line_breaks_are_rebased_onto_the_new_indentation(self):
        new = "changing decimals,\n        tax amounts"
        merged = _merge(
            _template(new),
            _entry(
                "changing decimals,\n            tax amounts",
                "cambiando decimales,\n            importes",
            ),
        )
        self.assertEqual(_live(merged), {new: "cambiando decimales,\n        importes"})

    def test_a_translation_whose_breaks_cannot_be_placed_is_kept_as_written(self):
        new = "The journal entries need\n                    posted in currency."
        merged = _merge(
            _template(new),
            _entry(
                "The journal entries need posted in currency.",
                "Los asientos contables en la moneda.",
                obsolete=True,
            ),
        )
        self.assertEqual(_live(merged), {new: "Los asientos contables en la moneda."})

    def test_the_old_term_stays_obsolete(self):
        old = "To\n    Review"
        merged = _merge(_template("To Review"), _entry(old, "A revisar"))
        self.assertEqual(
            {e.msgid: e.msgstr for e in merged if e.obsolete}, {old: "A revisar"}
        )

    def test_an_exact_translation_wins(self):
        merged = _merge(
            _template("To Review"),
            _entry("To Review", "Por revisar"),
            _entry("To\n    Review", "A revisar", obsolete=True),
        )
        self.assertEqual(_live(merged), {"To Review": "Por revisar"})

    def test_a_term_that_differs_beyond_whitespace_is_not_matched(self):
        merged = _merge(
            _template("To Review"),
            _entry("To  Reviews", "A revisar", obsolete=True),
            _entry("To Review", "A revisar", obsolete=True),
        )
        self.assertEqual(_live(merged), {"To Review": ""})


if __name__ == "__main__":
    unittest.main()

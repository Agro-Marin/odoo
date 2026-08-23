"""``18.5-00-no-tax-tag-invert.py`` — moving the sign off the tax tag.

The script carried a `test_tag_signs` function asserting the signs it derives
for eight Belgian and one Italian tag. Nothing called it, and it could only ever
have run against the real `l10n_be`/`l10n_it` template CSVs, so it was a table of
expectations dressed as a safety net. What it was sampling is `remove_sign`'s
rule, which is small enough to state directly and is what these tests pin.
"""

import importlib.util
import pathlib

import pytest

_SCRIPT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "upgrade_code"
    / "18.5-00-no-tax-tag-invert.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("no_tax_tag_invert", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load()


@pytest.mark.parametrize(
    ("tag", "type_tax_use", "document_type", "expected_sign"),
    [
        # The two combinations the script inverts, and the two it does not.
        ("+03", "sale", "invoice", -1),
        ("+03", "purchase", "refund", -1),
        ("+03", "sale", "refund", 1),
        ("+03", "purchase", "invoice", 1),
        ("-03", "sale", "invoice", 1),
        ("-03", "purchase", "invoice", -1),
    ],
)
def test_the_sign_recorded_flips_on_sale_invoice_and_purchase_refund(
    tag, type_tax_use, document_type, expected_sign
):
    tag_signs = {}
    stripped = MODULE.remove_sign(tag, tag_signs, type_tax_use, document_type, {})
    assert stripped == "03", "the sign must be removed from the tag itself"
    assert tag_signs["03"] == expected_sign


def test_a_tag_used_with_two_signs_is_marked_error_not_silently_last_wins():
    """The conflict the script cannot resolve, and must not paper over."""
    tag_signs = {}
    MODULE.remove_sign("+03", tag_signs, "sale", "invoice", {})
    MODULE.remove_sign("+03", tag_signs, "sale", "refund", {})
    assert tag_signs["03"] == "error"


def test_a_tag_with_no_sign_is_left_alone_and_records_nothing():
    tag_signs = {}
    assert MODULE.remove_sign("03", tag_signs, "sale", "invoice", {}) == "03"
    assert tag_signs == {}


def test_a_tax_that_is_neither_sale_nor_purchase_records_no_sign():
    """`none`-use taxes carry tags but no report direction to invert."""
    tag_signs = {}
    assert MODULE.remove_sign("+03", tag_signs, "none", "invoice", {}) == "03"
    assert tag_signs == {}


def test_several_tags_on_one_line_are_split_on_the_double_pipe():
    tag_signs = {}
    result = MODULE.remove_sign("+03||-49", tag_signs, "sale", "refund", {})
    assert result == "03||49"
    assert tag_signs == {"03": 1, "49": -1}


def test_an_empty_tag_string_is_returned_unchanged():
    assert MODULE.remove_sign("", {}, "sale", "invoice", {}) == ""


def test_template2country_maps_the_filename_suffix():
    assert MODULE.template2country("mx") == "base.mx"
    assert MODULE.template2country("be_asso") == "base.be"

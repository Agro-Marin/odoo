import pytest

from odoo.tools.tests._upgrade_script import load_upgrade_script

MODULE = load_upgrade_script("no_tax_tag_invert", "18.5-00-no-tax-tag-invert.py")


@pytest.mark.parametrize(
    ("tag", "type_tax_use", "document_type", "expected_sign"),
    [
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
    tag_signs: dict[str, int | str] = {}
    stripped = MODULE.remove_sign(tag, tag_signs, type_tax_use, document_type)
    assert stripped == "03", "the sign must be removed from the tag itself"
    assert tag_signs["03"] == expected_sign


def test_a_tag_used_with_two_signs_is_marked_error_not_silently_last_wins():
    tag_signs: dict[str, int | str] = {}
    MODULE.remove_sign("+03", tag_signs, "sale", "invoice")
    MODULE.remove_sign("+03", tag_signs, "sale", "refund")
    assert tag_signs["03"] == "error"


def test_a_tag_with_no_sign_is_left_alone_and_records_nothing():
    tag_signs: dict[str, int | str] = {}
    assert MODULE.remove_sign("03", tag_signs, "sale", "invoice") == "03"
    assert tag_signs == {}


def test_a_tax_that_is_neither_sale_nor_purchase_records_no_sign():
    tag_signs: dict[str, int | str] = {}
    assert MODULE.remove_sign("+03", tag_signs, "none", "invoice") == "03"
    assert tag_signs == {}


def test_several_tags_on_one_line_are_split_on_the_double_pipe():
    tag_signs: dict[str, int | str] = {}
    result = MODULE.remove_sign("+03||-49", tag_signs, "sale", "refund")
    assert result == "03||49"
    assert tag_signs == {"03": 1, "49": -1}


def test_an_empty_tag_string_is_returned_unchanged():
    assert MODULE.remove_sign("", {}, "sale", "invoice") == ""


def test_template2country_maps_the_filename_suffix():
    assert MODULE.template2country("mx") == "base.mx"
    assert MODULE.template2country("be_asso") == "base.be"

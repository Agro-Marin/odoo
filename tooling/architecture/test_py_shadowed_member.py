from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import py_shadowed_member as gate


def scan_source(tmp_path: Path, source: str) -> list[gate.Offence]:
    path = tmp_path / "probe.py"
    path.write_text(source, encoding="utf-8")
    return gate.scan(path, "probe.py")


def test_a_second_def_of_the_same_method_is_reported(tmp_path):
    found = scan_source(
        tmp_path,
        "class A:\n"
        "    def _m(self):\n"
        "        return 1\n"
        "\n"
        "    def other(self):\n"
        "        return 2\n"
        "\n"
        "    def _m(self):\n"
        "        return 3\n",
    )
    assert len(found) == 1
    assert (found[0].klass, found[0].member) == ("A", "_m")
    assert (found[0].first, found[0].line) == (2, 8)


def test_the_leading_underscore_is_not_an_exemption():
    # The whole reason this gate exists: ruff's F811 drops any name matching
    # its dummy-variable-rgx, and every Odoo model method is _-prefixed.
    assert gate.OVERLOAD_DECORATORS.isdisjoint({"_", "__"})
    assert not any(s.startswith("_") for s in gate.SELF_DECLARING_SUFFIXES)


@pytest.mark.parametrize("decorator", ["@_m.setter", "@_m.getter", "@_m.register"])
def test_a_redefinition_that_declares_itself_is_not_reported(tmp_path, decorator):
    found = scan_source(
        tmp_path,
        "class A:\n"
        "    def _m(self):\n"
        "        return 1\n"
        "\n"
        f"    {decorator}\n"
        "    def _m(self):\n"
        "        return 3\n",
    )
    assert found == []


@pytest.mark.parametrize("decorator", ["@overload", "@typing.overload"])
def test_overload_stubs_and_their_implementation_are_one_definition(
    tmp_path, decorator
):
    # The implementation that follows @overload stubs MUST be undecorated --
    # reporting it was this gate's own first bug, and it fired 13 times across
    # odoo/orm before the rule learned the difference.
    found = scan_source(
        tmp_path,
        "class A:\n"
        f"    {decorator}\n"
        "    def _m(self, x: int) -> int: ...\n"
        f"    {decorator}\n"
        "    def _m(self, x: str) -> str: ...\n"
        "\n"
        "    def _m(self, x):\n"
        "        return x\n",
    )
    assert found == []


def test_a_third_definition_after_an_overload_implementation_is_reported(tmp_path):
    found = scan_source(
        tmp_path,
        "class A:\n"
        "    @overload\n"
        "    def _m(self, x: int) -> int: ...\n"
        "\n"
        "    def _m(self, x):\n"
        "        return x\n"
        "\n"
        "    def _m(self, x):\n"
        "        return 0\n",
    )
    assert len(found) == 1


def test_a_bare_second_def_after_a_property_is_reported(tmp_path):
    # @property is deliberately not an exemption: the legitimate redefinition
    # is @_m.setter, and a plain `def` is the accident.
    found = scan_source(
        tmp_path,
        "class A:\n"
        "    @property\n"
        "    def _m(self):\n"
        "        return 1\n"
        "\n"
        "    def _m(self):\n"
        "        return 3\n",
    )
    assert len(found) == 1


def test_a_module_level_class_redefinition_is_out_of_scope(tmp_path):
    # test_orm and test_inherit redeclare models on purpose; a fixture that
    # redefines a class is not a shadowed member.
    found = scan_source(
        tmp_path,
        "class A:\n    pass\n\n\nclass A:\n    pass\n",
    )
    assert found == []


def test_a_nested_class_and_a_class_attribute_are_members(tmp_path):
    found = scan_source(
        tmp_path,
        "class A:\n"
        "    LIMIT = 1\n"
        "\n"
        "    class Inner:\n"
        "        pass\n"
        "\n"
        "    LIMIT = 2\n"
        "\n"
        "    class Inner:\n"
        "        pass\n",
    )
    assert {f.member for f in found} == {"LIMIT", "Inner"}


def test_the_same_name_in_two_different_classes_is_not_a_shadow(tmp_path):
    found = scan_source(
        tmp_path,
        "class A:\n"
        "    def _m(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "class B:\n"
        "    def _m(self):\n"
        "        return 2\n",
    )
    assert found == []


def test_a_file_that_does_not_parse_is_skipped_not_counted(tmp_path):
    assert scan_source(tmp_path, "class A:\n    def (\n") == []


def test_an_empty_tree_raises_rather_than_reporting_zero(tmp_path):
    with pytest.raises(RuntimeError, match="not the same as finding nothing wrong"):
        gate.measure(src=tmp_path)


def test_an_ungoverned_scope_is_refused_rather_than_scanned():
    assert gate.main(["--addon", "not_a_scope", "--count"]) == 2


def test_the_governed_scopes_include_every_sibling_checkout():
    # naming (ADR §9.4) is gated on odoo/ alone and a regression outside it is
    # caught by nothing. This one starts governed everywhere.
    assert set(gate.SIBLING_SCOPES) == {"enterprise", "agromarin", "design-themes"}

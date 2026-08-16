"""Tier-1 (DB-free) tests for the docstring/signature reflection helpers.

Every case here is a bug that reached production in ``addons/api_doc``: a
``:type:`` field written to the wrong attribute, ``**kwargs`` rendered as a
plain parameter, and a whole class of methods reflecting as ``(...)`` because
their annotations name types imported under ``if TYPE_CHECKING:``.
"""

import logging
import typing

import pytest

from odoo.libs import docstring

if typing.TYPE_CHECKING:
    # deliberately unimportable at runtime -- this is the ORM's situation
    from collections.abc import Sequence


class Recordset:
    """Stand-in for an annotation a transport wants rewritten."""


def _params(func, **kwargs):
    return docstring.parse_signature(func, **kwargs).as_dict()["parameters"]


def _signature(func, **kwargs):
    return docstring.parse_signature(func, **kwargs).as_dict()["signature"]


class TestTypeField:
    def test_type_field_fills_an_unannotated_parameter(self):
        def f(value):
            """Do a thing.

            :param value: what to do it to
            :type value: SomeCustomType
            """

        assert _params(f)["value"]["annotation"] == "SomeCustomType"

    def test_type_field_exports_no_other_key(self):
        # the original bug: `param.annotations = ...` created a stray attribute
        # that as_dict() then exported, while `annotation` stayed absent
        def f(value):
            """:type value: SomeCustomType"""

        assert set(_params(f)["value"]) == {"annotation"}

    def test_an_annotation_wins_over_the_type_field(self):
        def f(value: int):
            """:type value: str"""

        assert _params(f)["value"]["annotation"] == "int"

    def test_a_typo_in_a_field_name_cannot_create_an_attribute(self):
        # slots=True is what makes this a failure rather than silent data loss
        param = docstring.Param(
            "x", "POSITIONAL_OR_KEYWORD", docstring.EMPTY, None, None
        )
        with pytest.raises(AttributeError):
            param.annotations = "str"  # type: ignore[attr-defined]


class TestStringify:
    def test_var_positional_and_var_keyword_keep_their_stars(self):
        def f(a, *args, **kwargs):
            pass

        assert _signature(f) == "(a, *args, **kwargs)"

    def test_positional_only_marker_is_rendered(self):
        def f(a, b, /, c):
            pass

        assert _signature(f) == "(a, b, /, c)"

    def test_trailing_positional_only_marker_is_rendered(self):
        def f(a, /):
            pass

        assert _signature(f) == "(a, /)"

    def test_keyword_only_marker_is_rendered(self):
        def f(a, *, b):
            pass

        assert _signature(f) == "(a, *, b)"

    def test_var_positional_already_opens_the_keyword_only_section(self):
        def f(a, *args, b):
            pass

        assert _signature(f) == "(a, *args, b)"

    def test_every_marker_at_once(self):
        def f(a, /, b, *args, c=1, **kwargs):
            pass

        assert _signature(f) == "(a, /, b, *args, c=1, **kwargs)"

    def test_defaults_are_rendered_without_annotations(self):
        def f(a=1, b="x", c=None):
            pass

        assert _signature(f) == "(a=1, b='x', c=None)"

    def test_annotations_are_rendered_when_asked(self):
        def f(a: int = 1) -> str:
            return ""

        sig = docstring.parse_signature(f)
        assert sig.stringify() == "(a: int = 1) -> str"
        assert sig.stringify(annotation=False) == "(a=1) -> str"
        assert sig.stringify(return_annotation=False) == "(a: int = 1)"

    def test_self_is_dropped(self):
        class C:
            def m(self, a):
                pass

        assert _signature(C.m) == "(a)"

    def test_a_parameter_named_selfish_is_not_dropped(self):
        def f(selfish, a):
            pass

        assert _signature(f) == "(selfish, a)"


class TestDeferredAnnotations:
    def test_a_type_checking_only_name_does_not_raise(self):
        def f(names: Sequence[str], count: int = 0) -> Sequence[int]:
            return []

        # evaluating these annotations would raise NameError: Sequence
        params = _params(f)
        assert params["names"]["annotation"] == "Sequence[str]"
        assert params["count"]["annotation"] == "int"

    def test_annotations_keep_the_text_the_author_wrote(self):
        def f(a: dict[str, typing.Any]):
            pass

        assert _params(f)["a"]["annotation"] == "dict[str, typing.Any]"


class TestDefaults:
    def test_an_unserialisable_default_is_dropped(self):
        sentinel = object()

        def f(a=sentinel):
            pass

        assert "default" not in _params(f)["a"]

    def test_a_serialisable_default_is_kept(self):
        def f(a=[1, 2]):  # noqa: B006 - the value is data here, not state
            pass

        assert _params(f)["a"]["default"] == [1, 2]

    def test_no_default_exports_no_key(self):
        def f(a):
            pass

        assert "default" not in _params(f)["a"]


class TestInfoFields:
    def test_returns_and_rtype(self):
        def f():
            """Do it.

            :returns: the thing
            :rtype: dict
            """

        d = docstring.parse_signature(f).as_dict()
        assert d["return"]["annotation"] == "dict"
        assert "the thing" in d["return"]["doc"]

    def test_an_annotation_wins_over_rtype(self):
        def f() -> list[int]:
            """:rtype: dict"""
            return []

        assert (
            docstring.parse_signature(f).as_dict()["return"]["annotation"]
            == "list[int]"
        )

    def test_raises_is_collected_per_exception(self):
        def f():
            """
            :raises AccessError: not allowed
            :raises ValueError: bad input
            """

        raised = docstring.parse_signature(f).as_dict()["raise"]
        assert set(raised) == {"AccessError", "ValueError"}
        assert "not allowed" in raised["AccessError"]

    def test_inline_annotation_in_a_param_field(self):
        def f(a):
            """:param str a: the a"""

        param = _params(f)["a"]
        assert param["annotation"] == "str"
        assert "the a" in param["doc"]

    def test_prose_survives_as_the_doc(self):
        def f(a):
            """Summary line.

            :param a: ignored
            """

        assert "Summary line." in docstring.parse_signature(f).as_dict()["doc"]

    def test_a_field_for_an_unknown_parameter_is_ignored(self):
        def f(a):
            """:param nonexistent: nothing"""

        assert set(_params(f)) == {"a"}

    def test_var_fields_are_skipped_without_complaint(self, caplog):
        def f():
            """
            :ivar thing: an attribute
            :vartype thing: str
            :meta private:
            """

        with caplog.at_level(logging.WARNING, logger=docstring.__name__):
            docstring.parse_signature(f)
        assert caplog.records == []

    def test_an_unknown_field_name_is_reported(self, caplog):
        def f():
            """:nonsense value: what"""

        with caplog.at_level(logging.WARNING, logger=docstring.__name__):
            docstring.parse_signature(f)
        assert "cannot parse" in caplog.text


class TestNormalizeReturn:
    def test_the_hook_rewrites_the_return_annotation(self):
        def f() -> Recordset:  # type: ignore[empty-body]
            pass

        sig = docstring.parse_signature(
            f, normalize_return=lambda a: "list[int]" if a == "Recordset" else a
        )
        assert sig.as_dict()["return"]["annotation"] == "list[int]"
        assert sig.as_dict()["signature"] == "() -> list[int]"

    def test_without_the_hook_the_annotation_is_untouched(self):
        def f() -> Recordset:  # type: ignore[empty-body]
            pass

        assert (
            docstring.parse_signature(f).as_dict()["return"]["annotation"]
            == "Recordset"
        )


class TestNoDocstring:
    def test_a_method_without_a_docstring_exports_no_doc(self):
        def f(a):
            pass

        assert "doc" not in docstring.parse_signature(f).as_dict()


class TestBorrowedDocstring:
    """An override that documents nothing is described by what it replaced."""

    def test_an_explicit_docstring_is_merged_into_the_signature(self):
        def override(a):
            pass

        d = docstring.parse_signature(
            override, docstring="Base prose.\n\n:param a: from the base"
        ).as_dict()
        assert "Base prose." in d["doc"]
        assert "from the base" in d["parameters"]["a"]["doc"]

    def test_an_explicit_docstring_wins_over_the_callable_s_own(self):
        def override(a):
            """Own prose."""

        d = docstring.parse_signature(override, docstring="Borrowed prose.").as_dict()
        assert "Borrowed prose." in d["doc"]
        assert "Own prose." not in d["doc"]

    def test_a_borrowed_field_for_a_missing_parameter_is_ignored(self):
        def override(a):
            pass

        d = docstring.parse_signature(
            override, docstring=":param gone: not in this signature"
        ).as_dict()
        assert set(d["parameters"]) == {"a"}


class TestRenderDocstring:
    def test_prose_becomes_html(self):
        assert "<p>" in docstring.render_docstring("Hello.")

    def test_indentation_is_cleaned_before_rendering(self):
        rendered = docstring.render_docstring("Summary.\n\n    Indented body.\n")
        assert "Indented body." in rendered

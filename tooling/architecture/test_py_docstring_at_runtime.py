import textwrap
from pathlib import Path

import pytest
from py_docstring_at_runtime import measure


def _measure(tmp_path: Path, src: str):
    (tmp_path / "m.py").write_text(textwrap.dedent(src))
    return measure(files=[tmp_path / "m.py"])


CRASHES = [
    # the two that actually happened, in the shape they happened in
    ("__doc__.replace('a', 'b')", "attribute"),
    ("Field.__doc__ + 'more'", "operand"),
    # the rest of the same class
    ("x.__doc__.strip()", "attribute"),
    ("x.__doc__.splitlines()[0]", "attribute"),
    ("__doc__[0]", "subscript"),
    ("x.__doc__[:10]", "subscript"),
    ("'prefix' + x.__doc__", "operand"),
    ("x.__doc__ % ()", "operand"),
]

SAFE = [
    # None just flows; nothing raises
    "x.__doc__ or ''",
    "x.__doc__ or x.description",
    "d = x.__doc__",
    "return x.__doc__",
    "f(x.__doc__)",
    "if x.__doc__: pass",
    "[c.__doc__ for c in cs if c.__doc__]",
    "next((c.__doc__ for c in cs if c.__doc__), None)",
    "x.__doc__ is None",
    "assigned = ('__doc__',)",
]


class TestTheCrashClassIsCaught:
    @pytest.mark.parametrize(("body", "kind"), CRASHES)
    def test_a_none_docstring_would_raise_here(self, tmp_path, body, kind):
        found = _measure(tmp_path, body)
        assert len(found) == 1, f"{body!r} -> {found}"
        assert found[0].kind == kind

    def test_a_bare_module_docstring_is_a_name_not_an_attribute(self, tmp_path):
        assert _measure(tmp_path, "__doc__.replace('a', 'b')")


class TestWhatDoesNotRaiseIsNotReported:
    @pytest.mark.parametrize("body", SAFE)
    def test_no_offence(self, tmp_path, body):
        assert _measure(tmp_path, body) == []

    def test_a_docstring_of_its_own_is_not_a_read(self, tmp_path):
        assert (
            _measure(
                tmp_path,
                """
            def f():
                "documented"
        """,
            )
            == []
        )


class TestTheGateRefusesToPassVacuously:
    def test_an_empty_scope_raises_rather_than_reporting_clean(self, tmp_path):
        with pytest.raises(RuntimeError, match="not the same as finding nothing"):
            measure(src=tmp_path)

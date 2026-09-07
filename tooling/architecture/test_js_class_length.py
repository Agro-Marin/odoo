import js_class_length as jcl
import pytest


def _measure(monkeypatch, tmp_path, files):
    for rel, body in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    monkeypatch.setattr(jcl, "WEB_SRC", tmp_path)
    return jcl.measure(tmp_path)


def _class(name, body_lines, *, comment_lines=0):
    body = "".join(f"    m{i}() {{}}\n" for i in range(body_lines))
    comments = "".join(f"    // note {i}\n" for i in range(comment_lines))
    return f"export class {name} {{\n{comments}{body}}}\n"


def test_a_class_inside_the_budget_is_not_an_offender(monkeypatch, tmp_path):
    got = _measure(monkeypatch, tmp_path, {"a.js": _class("Small", 100)})
    assert got == []


def test_a_class_over_the_budget_reports_its_excess(monkeypatch, tmp_path):
    got = _measure(monkeypatch, tmp_path, {"a.js": _class("Big", 500)})
    assert [(c.what, c.lines) for c in got] == [("Big", 502)]
    assert jcl.excess_lines(got) == 502 - jcl.MAX_LINES


def test_comment_only_lines_do_not_count(monkeypatch, tmp_path):
    """jsfunclen runs eslint with skipComments; this budget must agree.

    Otherwise documenting a class prices it above an undocumented one of the
    same mass, and the two numbers stop being comparable.
    """
    got = _measure(
        monkeypatch, tmp_path, {"a.js": _class("Documented", 500, comment_lines=200)}
    )
    assert [c.lines for c in got] == [502]


def test_the_unit_is_excess_not_offender_count(monkeypatch, tmp_path):
    """Splitting one huge class into two large ones must lower the number."""
    one = _measure(monkeypatch, tmp_path, {"a.js": _class("Huge", 1000)})
    two = _measure(
        monkeypatch,
        tmp_path,
        {"a.js": _class("HalfA", 500) + "\n" + _class("HalfB", 500)},
    )
    assert len(two) > len(one)
    assert jcl.excess_lines(two) < jcl.excess_lines(one)


def test_an_anonymous_class_is_named_after_what_it_is_bound_to(monkeypatch, tmp_path):
    body = "".join(f"    m{i}() {{}}\n" for i in range(500))
    got = _measure(
        monkeypatch,
        tmp_path,
        {"a.js": f"const Patched = class extends Base {{\n{body}}};\n"},
    )
    assert [c.what for c in got] == ["Patched"]


def test_generated_sources_are_skipped(monkeypatch, tmp_path):
    got = _measure(
        monkeypatch,
        tmp_path,
        {"emoji_data.js": _class("Generated", 500), "hand.js": _class("Small", 10)},
    )
    assert got == []


def test_an_empty_tree_is_refused_not_reported_clean(monkeypatch, tmp_path):
    monkeypatch.setattr(jcl, "WEB_SRC", tmp_path)
    with pytest.raises(RuntimeError):
        jcl.measure(tmp_path)


def test_a_syntax_error_is_loud(monkeypatch, tmp_path):
    """A file the analyzer cannot parse must not silently measure as zero."""
    with pytest.raises(RuntimeError):
        _measure(monkeypatch, tmp_path, {"a.js": "export class Broken {"})

import js_unreached_assertions as jua
import pytest


def _measure(monkeypatch, tmp_path, body, name="t"):
    path = tmp_path / f"{name}.test.js"
    path.write_text(body)
    monkeypatch.setattr(jua, "WEB_TESTS", tmp_path)
    return jua.measure(tmp_path)


MASKED = """\
test("the shape this gate exists for", async () => {
    class MyComponent {
        plop(ev) {
            expect(ev.currentTarget).toBe(document);
        }
    }
    expect(".clickMe").toHaveText("text");
    await contains(".clickMe").click();
});
"""


def test_a_masked_deferred_assertion_is_reported(monkeypatch, tmp_path):
    got = _measure(monkeypatch, tmp_path, MASKED)
    assert [(f.method, f.test) for f in got] == [
        ("plop", "the shape this gate exists for")
    ]


def test_an_unmasked_one_is_not_hoot_already_fails_it(monkeypatch, tmp_path):
    """Every assertion inside the handler and none outside.

    Hoot fails a test that runs no assertion at all, so this case is covered
    already; reporting it would be debt the tree does not have.
    """
    got = _measure(
        monkeypatch,
        tmp_path,
        MASKED.replace('    expect(".clickMe").toHaveText("text");\n', ""),
    )
    assert got == []


def test_an_assertion_count_guard_clears_it(monkeypatch, tmp_path):
    got = _measure(
        monkeypatch,
        tmp_path,
        MASKED.replace(
            'test("the shape this gate exists for", async () => {',
            'test("guarded", async () => {\n    expect.assertions(2);',
        ),
    )
    assert got == []


def test_a_sentinel_clears_it(monkeypatch, tmp_path):
    """`let ran = false` ... `ran = true` ... `expect(ran).toBe(true)`.

    Idiomatic in this tree and a correct guard: the outer assertion fails if the
    handler never ran.
    """
    got = _measure(
        monkeypatch,
        tmp_path,
        """\
test("sentinel", async () => {
    let ran = false;
    class C {
        plop(ev) {
            ran = true;
            expect(ev.currentTarget).toBe(document);
        }
    }
    expect(".clickMe").toHaveText("text");
    await contains(".clickMe").click();
    expect(ran).toBe(true);
});
""",
    )
    assert got == []


def test_an_asserted_call_result_clears_it(monkeypatch, tmp_path):
    """A callback whose caller returns its value cannot have been skipped."""
    got = _measure(
        monkeypatch,
        tmp_path,
        """\
test("result asserted", () => {
    const seen = withWindow(() => {
        expect(model.blocked).toBe(true);
        return "value";
    });
    expect(seen).toBe("value");
});
""",
    )
    assert got == []


def test_a_callback_the_test_drives_itself_is_not_deferred(monkeypatch, tmp_path):
    got = _measure(
        monkeypatch,
        tmp_path,
        """\
test("array iteration", () => {
    expect(rows).toHaveLength(2);
    rows.forEach((r) => {
        expect(r.ok).toBe(true);
    });
});
""",
    )
    assert got == []


def test_an_empty_tree_is_refused_not_reported_clean(monkeypatch, tmp_path):
    monkeypatch.setattr(jua, "WEB_TESTS", tmp_path)
    with pytest.raises(RuntimeError):
        jua.measure(tmp_path)


def test_a_syntax_error_is_loud(monkeypatch, tmp_path):
    with pytest.raises(RuntimeError):
        _measure(monkeypatch, tmp_path, "test('broken', () => {")

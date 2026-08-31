import js_context_narrowing as jcn
import pytest


def _tree(root, files):
    static = root / "static"
    for rel, body in files.items():
        path = static / "src" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    (static / "src").mkdir(parents=True, exist_ok=True)
    return static


CONTEXT = """\
/**
 * @typedef {{
 * getA: () => number;
 * getB: () => number;
 * getC: () => number;
 * }} GridContext
 */
export const marker = 1;
"""


def _consumer(picked, body):
    members = " | ".join(f'"{m}"' for m in picked)
    return f"""\
/**
 * @param {{Pick<import("./context.js").GridContext, {members}>}} ctx
 */
export function useThing(ctx) {{
{body}
}}
"""


def _contracts(findings):
    return sorted(f.contract for f in findings)


def test_an_exact_narrowing_passes(tmp_path):
    static = _tree(
        tmp_path,
        {
            "context.js": CONTEXT,
            "consumer.js": _consumer(
                ["getA", "getB"], "    return ctx.getA() + ctx.getB();"
            ),
        },
    )
    assert jcn.analyse(static) == []


def test_a_member_declared_but_never_reached_fails(tmp_path):
    static = _tree(
        tmp_path,
        {
            "context.js": CONTEXT,
            "consumer.js": _consumer(["getA", "getB"], "    return ctx.getA();"),
        },
    )
    findings = jcn.analyse(static)
    assert _contracts(findings) == ["over-declared"]
    assert "getB" in findings[0].detail


def test_a_member_reached_but_not_declared_fails(tmp_path):
    static = _tree(
        tmp_path,
        {
            "context.js": CONTEXT,
            "consumer.js": _consumer(["getA"], "    return ctx.getA() + ctx.getC();"),
        },
    )
    findings = jcn.analyse(static)
    assert _contracts(findings) == ["under-declared"]
    assert "getC" in findings[0].detail


def test_destructuring_counts_as_reaching(tmp_path):
    static = _tree(
        tmp_path,
        {
            "context.js": CONTEXT,
            "consumer.js": _consumer(
                ["getA", "getB"],
                "    const { getA, getB } = ctx;\n    return getA() + getB();",
            ),
        },
    )
    assert jcn.analyse(static) == []


def test_a_member_named_only_in_a_comment_does_not_count_as_reached(tmp_path):
    static = _tree(
        tmp_path,
        {
            "context.js": CONTEXT,
            "consumer.js": _consumer(
                ["getA", "getB"],
                "    // getB is handled elsewhere\n    return ctx.getA();",
            ),
        },
    )
    assert _contracts(jcn.analyse(static)) == ["over-declared"]


def test_a_reach_behind_a_stored_field_counts(tmp_path):
    static = _tree(
        tmp_path,
        {
            "context.js": CONTEXT,
            "consumer.js": """\
/**
 * @param {Pick<import("./context.js").GridContext, "getA">} ctx
 */
export function useThing(ctx) {
    return new Thing(ctx);
}
class Thing {
    constructor(ctx) {
        this.ctx = ctx;
    }
    run() {
        return this.ctx.getA();
    }
}
""",
        },
    )
    assert jcn.analyse(static) == []


def test_computed_access_is_reported_rather_than_guessed_at(tmp_path):
    static = _tree(
        tmp_path,
        {
            "context.js": CONTEXT,
            "consumer.js": _consumer(["getA"], '    return ctx["getA"]();'),
        },
    )
    assert "unresolvable" in _contracts(jcn.analyse(static))


def test_an_intersection_of_two_narrowings_is_resolved(tmp_path):
    static = _tree(
        tmp_path,
        {
            "context.js": CONTEXT,
            "edit.js": """\
/**
 * @typedef {Pick<import("./context.js").GridContext, "getC">} EditContext
 */

/**
 * @param {EditContext} ctx
 */
export function makeHandlers(ctx) {
    return ctx.getC();
}
""",
            "consumer.js": """\
import { makeHandlers } from "./edit.js";
/**
 * @param {Pick<import("./context.js").GridContext, "getA"> &
 *   import("./edit.js").EditContext} ctx
 */
export function useThing(ctx) {
    return ctx.getA() + makeHandlers(ctx);
}
""",
        },
    )
    # getC is declared through the intersection and reached by the callee this
    # file forwards to; neither half may be reported.
    assert jcn.analyse(static) == []


def test_forwarding_does_not_excuse_a_member_nobody_reaches(tmp_path):
    static = _tree(
        tmp_path,
        {
            "context.js": CONTEXT,
            "edit.js": """\
/**
 * @param {Pick<import("./context.js").GridContext, "getC">} ctx
 */
export function makeHandlers(ctx) {
    return ctx.getC();
}
""",
            "consumer.js": """\
import { makeHandlers } from "./edit.js";
/**
 * @param {Pick<import("./context.js").GridContext, "getA" | "getB">} ctx
 */
export function useThing(ctx) {
    return makeHandlers(ctx);
}
""",
        },
    )
    findings = jcn.analyse(static)
    named = {
        (f.contract, f.detail.split("GridContext.")[1].split(" ")[0].rstrip(","))
        for f in findings
    }
    # getA and getB are declared and reached by nobody, here or downstream.
    # getC is the mirror image: forwarding reaches it, so the caller owes it a
    # place in its own Pick<> -- a hook that hands its context on is coupled to
    # what the callee reads.
    assert named == {
        ("over-declared", "getA"),
        ("over-declared", "getB"),
        ("under-declared", "getC"),
    }


def test_a_sub_property_annotation_is_not_a_narrowed_parameter(tmp_path):
    # `@param {T} params.action` types a property, not the parameter, and its
    # members must not be attributed to `params`.
    static = _tree(
        tmp_path,
        {
            "context.js": CONTEXT,
            "consumer.js": """\
/**
 * @param {object} params
 * @param {Pick<import("./context.js").GridContext, "getA">} params.grid
 */
export function useThing(params) {
    return params.grid.getA();
}
""",
        },
    )
    assert jcn.analyse(static) == []


def test_an_index_signature_is_not_read_as_a_member(tmp_path):
    # Pick<Factories["action"], "doAction"> narrows to doAction; "action" is the
    # index into the source type, not a member of it.
    static = _tree(
        tmp_path,
        {
            "context.js": """\
/**
 * @typedef {{ action: { doAction: () => void, other: () => void } }} Factories
 */
export const marker = 1;
""",
            "consumer.js": """\
/**
 * @param {Pick<import("./context.js").Factories["action"], "doAction">} ctx
 */
export function useThing(ctx) {
    return ctx.doAction();
}
""",
        },
    )
    assert jcn.analyse(static) == []


def test_an_empty_tree_is_refused(tmp_path):
    static = tmp_path / "static"
    (static / "src").mkdir(parents=True)
    with pytest.raises(SystemExit) as exc:
        jcn.main(["--web-static", str(static)])
    assert exc.value.code != 0

// @ts-check

/**
 * Cache coherence: useViewCompiler must register OWL templates under a
 * deterministic name (the arch-content key) so resetViewCompilerCache() +
 * recompiling the same arch overwrites the same globalTemplates slot instead
 * of accumulating entries (the leak from the original FIXME).
 */

import { describe, expect, test } from "@odoo/hoot";
import { App, Component } from "@odoo/owl";
import {
    makeIsVisibleExpr,
    resetViewCompilerCache,
    useViewCompiler,
    ViewCompiler,
} from "@web/views/view_compiler";
import { toStringExpression } from "@web/views/view_utils";

/**
 * Minimal ViewCompiler stub accepted by useViewCompiler.
 *
 * Satisfies the three requirements of the real ViewCompiler:
 *  - `static .name` — used as the template namespace prefix in the key
 *  - `constructor(templates)` — instantiated once per useViewCompiler call
 *  - `compile(tname, params) → Element` — returns a compilable DOM element
 */
class TestCompiler {
    constructor(templates) {
        this._templates = templates;
    }

    compile(tname) {
        const el = document.createElement("t");
        el.setAttribute("t-name", tname);
        return el;
    }
}

/**
 * Build a `templates` object (Record<string, Element>) from a list of
 * [name, tag, attrs?] triples, matching what view loaders produce.
 *
 * @param {Array<[string, string, Record<string,string>?]>} specs
 * @returns {Record<string, Element>}
 */
function makeTemplates(specs) {
    const templates = {};
    for (const [name, tag, attrs = {}] of specs) {
        const el = document.createElement(tag);
        for (const [k, v] of Object.entries(attrs)) {
            el.setAttribute(k, v);
        }
        templates[name] = el;
    }
    return templates;
}

describe("toStringExpression", () => {
    test("wraps a plain string in backticks", () => {
        expect(toStringExpression("abc")).toBe("`abc`");

        expect(eval(toStringExpression("abc"))).toBe("abc");
    });

    test("escapes backticks so the delimiter can't be closed early", () => {
        expect(toStringExpression("a`b")).toBe("`a\\`b`");

        expect(eval(toStringExpression("a`b"))).toBe("a`b");
    });

    test("neutralizes ${ interpolation so it stays a literal, not evaluated", () => {
        const expr = toStringExpression("a${1 + 1}b");
        expect(expr.includes("`a\\${1 + 1}b`")).toBe(true);

        expect(eval(expr)).toBe("a${1 + 1}b");
    });

    test("nullish input yields an empty-string literal", () => {
        expect(eval(toStringExpression(undefined))).toBe("");

        expect(eval(toStringExpression(null))).toBe("");
    });
});

describe("makeIsVisibleExpr", () => {
    test("falsy / 'False' / '0' modifiers map to the always-visible literal", () => {
        expect(makeIsVisibleExpr(undefined)).toBe("true");
        expect(makeIsVisibleExpr(null)).toBe("true");
        expect(makeIsVisibleExpr("")).toBe("true");
        expect(makeIsVisibleExpr("False")).toBe("true");
        expect(makeIsVisibleExpr("0")).toBe("true");
    });

    test("'True' / '1' modifiers map to the never-visible literal", () => {
        expect(makeIsVisibleExpr("True")).toBe("false");
        expect(makeIsVisibleExpr("1")).toBe("false");
    });

    test("a dynamic modifier compiles to a negated evaluateBooleanExpr call", () => {
        expect(makeIsVisibleExpr("display_name == 'take'")).toBe(
            `!__comp__.evaluateBooleanExpr("display_name == 'take'",__comp__.props.record.evalContextWithVirtualIds)`,
        );
    });

    test("a custom recordExpr is threaded into the dynamic expression", () => {
        expect(makeIsVisibleExpr("a == 1", "__comp__.someRecord")).toBe(
            `!__comp__.evaluateBooleanExpr("a == 1",__comp__.someRecord.evalContextWithVirtualIds)`,
        );
    });
});

describe("useViewCompiler — cache coherence after reset", () => {
    test("same arch returns the same OWL template name after resetViewCompilerCache", () => {
        resetViewCompilerCache();
        const templates = makeTemplates([["form", "form", { string: "Test" }]]);

        const name1 = useViewCompiler(TestCompiler, templates).form;
        resetViewCompilerCache();
        const name2 = useViewCompiler(TestCompiler, templates).form;

        expect(name1).toBe(name2);
    });

    test("template name equals the arch-content key", () => {
        resetViewCompilerCache();
        const arch = document.createElement("list");
        arch.setAttribute("string", "Lines");
        const templates = { list: arch };

        const result = useViewCompiler(TestCompiler, templates);

        expect(result.list).toMatch(/^TestCompiler#\d+\/\//);
        expect(result.list.endsWith(`/${arch.outerHTML}`)).toBe(true);
    });

    test("multiple resets do not change the registered template name", () => {
        resetViewCompilerCache();
        const templates = makeTemplates([["form", "form", { string: "Stable" }]]);

        const name1 = useViewCompiler(TestCompiler, templates).form;
        resetViewCompilerCache();
        const name2 = useViewCompiler(TestCompiler, templates).form;
        resetViewCompilerCache();
        const name3 = useViewCompiler(TestCompiler, templates).form;

        expect(name1).toBe(name2);
        expect(name2).toBe(name3);
    });
});

describe("useViewCompiler — template name uniqueness", () => {
    test("different arches produce different template names", () => {
        resetViewCompilerCache();
        const t1 = makeTemplates([["form", "form", { string: "Form1" }]]);
        const t2 = makeTemplates([["form", "form", { string: "Form2" }]]);

        const name1 = useViewCompiler(TestCompiler, t1).form;
        const name2 = useViewCompiler(TestCompiler, t2).form;

        expect(name1).not.toBe(name2);
    });

    test("same arch under different compiler classes produces different names", () => {
        resetViewCompilerCache();

        class CompilerA {
            constructor() {}
            compile() {
                return document.createElement("t");
            }
        }
        class CompilerB {
            constructor() {}
            compile() {
                return document.createElement("t");
            }
        }

        const templates = makeTemplates([["form", "form", {}]]);
        const nameA = useViewCompiler(CompilerA, templates).form;
        const nameB = useViewCompiler(CompilerB, templates).form;

        expect(nameA).not.toBe(nameB);
    });

    test("multiple templates in one call each get a distinct name", () => {
        resetViewCompilerCache();
        const templates = makeTemplates([
            ["form", "form", { string: "Main" }],
            ["buttons", "div", { class: "o_btn_box" }],
        ]);

        const result = useViewCompiler(TestCompiler, templates);

        expect(result.form.endsWith(`/${templates.form.outerHTML}`)).toBe(true);
        expect(result.buttons.endsWith(`/${templates.buttons.outerHTML}`)).toBe(true);
        expect(result.form).not.toBe(result.buttons);
    });
});

describe("useViewCompiler — cache hits", () => {
    test("calling twice with the same arch compiles only once", () => {
        resetViewCompilerCache();
        let compilations = 0;

        class CountingCompiler {
            constructor() {}
            compile() {
                compilations++;
                return document.createElement("t");
            }
        }

        const templates = makeTemplates([["form", "form", {}]]);
        useViewCompiler(CountingCompiler, templates);
        useViewCompiler(CountingCompiler, templates);

        expect(compilations).toBe(1);
    });

    test("calling after reset recompiles once", () => {
        resetViewCompilerCache();
        let compilations = 0;

        class CountingCompiler {
            constructor() {}
            compile() {
                compilations++;
                return document.createElement("t");
            }
        }

        const templates = makeTemplates([["form", "form", {}]]);
        useViewCompiler(CountingCompiler, templates);
        resetViewCompilerCache();
        useViewCompiler(CountingCompiler, templates);
        useViewCompiler(CountingCompiler, templates);

        expect(compilations).toBe(2);
    });
});

describe("ViewCompiler — codegen escaping", () => {
    /**
     * Compile a one-node arch through the real ViewCompiler.
     *
     * @param {string} raw
     * @returns {string} the compiled template's outerHTML
     */
    function compileArch(raw) {
        const el = new DOMParser().parseFromString(raw, "text/xml").documentElement;
        return new ViewCompiler({ root: el }).compile("root").outerHTML;
    }

    /**
     * Whether OWL can actually tokenize + compile the produced template. A
     * template that only *looks* right is worthless: the failure mode being
     * guarded here is a tokenizer error that kills the whole view.
     *
     * @param {string} compiled
     * @param {string} name
     * @returns {string | null} the error message, or null when it compiles
     */
    function owlCompileError(compiled, name) {
        try {
            App.registerTemplate(name, compiled);
            new App(Component, { templates: {} }).getTemplate(name);
            return null;
        } catch (error) {
            return String(error);
        }
    }

    test("a widget class holding a quote still produces a compilable template", () => {
        const compiled = compileArch(
            `<widget name="w" widget_id="w1" class="a'b"/>`,
        );
        expect(compiled).toInclude(toStringExpression("a'b"));
        expect(owlCompileError(compiled, "test.widget.quote")).toBe(null);
    });

    test("a widget class holding a backtick still produces a compilable template", () => {
        const compiled = compileArch(
            "<widget name=\"w\" widget_id=\"w2\" class=\"a`b\"/>",
        );
        expect(owlCompileError(compiled, "test.widget.backtick")).toBe(null);
    });

    test("a widget class holding ${} is not evaluated as an expression", () => {
        const compiled = compileArch(
            `<widget name="w" widget_id="w3" class="a\${boom}b"/>`,
        );
        expect(compiled).toInclude("\\${");
        expect(owlCompileError(compiled, "test.widget.interp")).toBe(null);
    });

    test("field ids and widget names go through toStringExpression", () => {
        const compiled = compileArch(
            `<field name="foo" field_id="foo_0" widget="badge"/>`,
        );
        expect(compiled).toInclude(toStringExpression("foo_0"));
        expect(compiled).toInclude(toStringExpression("foo"));
        expect(compiled).toInclude(toStringExpression("badge"));
        expect(owlCompileError(compiled, "test.field.escape")).toBe(null);
    });
});

describe("ViewCompiler — button disabled", () => {
    /**
     * @param {string} raw
     * @returns {string | null}
     */
    function compiledDisabled(raw) {
        const el = new DOMParser().parseFromString(raw, "text/xml").documentElement;
        const compiled = new ViewCompiler({ root: el }).compile("root");
        return compiled.firstElementChild.getAttribute("disabled");
    }

    test(`disabled="1" disables the button`, () => {
        expect(compiledDisabled(`<button type="object" name="x" disabled="1"/>`)).toBe(
            "true",
        );
    });

    test(`disabled="0" does NOT disable the button`, () => {
        expect(compiledDisabled(`<button type="object" name="x" disabled="0"/>`)).toBe(
            "false",
        );
    });

    test(`disabled="False" does NOT disable the button`, () => {
        expect(
            compiledDisabled(`<button type="object" name="x" disabled="False"/>`),
        ).toBe("false");
    });

    test(`disabled="" does NOT disable the button`, () => {
        expect(compiledDisabled(`<button type="object" name="x" disabled=""/>`)).toBe(
            "false",
        );
    });
});

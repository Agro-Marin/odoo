// @ts-check

/**
 * Cache coherence: useViewCompiler must register OWL templates under a
 * deterministic name (the arch-content key) so resetViewCompilerCache() +
 * recompiling the same arch overwrites the same globalTemplates slot instead
 * of accumulating entries (the leak from the original FIXME).
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    makeIsVisibleExpr,
    resetViewCompilerCache,
    useViewCompiler,
} from "@web/views/view_compiler";

// Helpers

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

// makeIsVisibleExpr — shared invisible->isVisible helper

describe("makeIsVisibleExpr", () => {
    test("falsy / 'False' / '0' modifiers map to the always-visible literal", () => {
        // These are the three literal forms that mean "always visible".
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

// Cache coherence — deterministic template names (the core fix)

describe("useViewCompiler — cache coherence after reset", () => {
    test("same arch returns the same OWL template name after resetViewCompilerCache", () => {
        resetViewCompilerCache();
        const templates = makeTemplates([["form", "form", { string: "Test" }]]);

        const name1 = useViewCompiler(TestCompiler, templates).form;
        resetViewCompilerCache();
        const name2 = useViewCompiler(TestCompiler, templates).form;

        // Before fix: name1 = "__template__N", name2 = "__template__N+1" — different,
        // causing an orphaned entry in OWL's globalTemplates on every reset.
        // After fix: both equal the arch-content key — identical, no accumulation.
        expect(name1).toBe(name2);
    });

    test("template name equals the arch-content key", () => {
        resetViewCompilerCache();
        const arch = document.createElement("list");
        arch.setAttribute("string", "Lines");
        const templates = { list: arch };

        const result = useViewCompiler(TestCompiler, templates);

        // The OWL template name is "ClassName#N/paramsKey/arch.outerHTML" —
        // deterministic and unique per (compiler class, params, arch) triple.
        // The #N class discriminator is a private monotonic counter (it keeps
        // same-named compiler classes apart), so assert the structure rather
        // than a literal.
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

// Template name uniqueness

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

        // CompilerA.name !== CompilerB.name, so the key differs
        expect(nameA).not.toBe(nameB);
    });

    test("multiple templates in one call each get a distinct name", () => {
        resetViewCompilerCache();
        const templates = makeTemplates([
            ["form", "form", { string: "Main" }],
            ["buttons", "div", { class: "o_btn_box" }],
        ]);

        const result = useViewCompiler(TestCompiler, templates);

        // Structural check (the #N class discriminator is private — see
        // "template name equals the arch-content key" above).
        expect(result.form.endsWith(`/${templates.form.outerHTML}`)).toBe(true);
        expect(result.buttons.endsWith(`/${templates.buttons.outerHTML}`)).toBe(true);
        expect(result.form).not.toBe(result.buttons);
    });
});

// Cache hit — no recompilation on repeated calls

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
        useViewCompiler(CountingCompiler, templates); // compile #1
        resetViewCompilerCache();
        useViewCompiler(CountingCompiler, templates); // compile #2
        useViewCompiler(CountingCompiler, templates); // cache hit — no #3

        expect(compilations).toBe(2);
    });
});

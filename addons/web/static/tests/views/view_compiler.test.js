// @ts-check

/**
 * Unit tests for views/view_compiler.js.
 *
 * Focuses on the cache coherence fix: useViewCompiler must register OWL
 * templates under a deterministic name (the arch-content key) so that
 * calling resetViewCompilerCache() and then re-compiling the same arch
 * overwrites the same globalTemplates slot instead of accumulating new
 * entries (the memory leak described in the original FIXME comment).
 *
 * These are pure unit tests — no OWL application lifecycle, no mock
 * environment, and no server calls are needed.
 */

import { describe, expect, test } from "@odoo/hoot";
import { useViewCompiler, resetViewCompilerCache } from "@web/views/view_compiler";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Cache coherence — deterministic template names (the core fix)
// ---------------------------------------------------------------------------

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

        // The OWL template name is "ClassName/arch.outerHTML" — deterministic
        // and unique per (compiler, arch) pair.
        expect(result.list).toBe(`TestCompiler/${arch.outerHTML}`);
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

// ---------------------------------------------------------------------------
// Template name uniqueness
// ---------------------------------------------------------------------------

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

        expect(result.form).toBe(`TestCompiler/${templates.form.outerHTML}`);
        expect(result.buttons).toBe(`TestCompiler/${templates.buttons.outerHTML}`);
        expect(result.form).not.toBe(result.buttons);
    });
});

// ---------------------------------------------------------------------------
// Cache hit — no recompilation on repeated calls
// ---------------------------------------------------------------------------

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

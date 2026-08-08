// @ts-check

/**
 * Cache coherence: useViewCompiler must register OWL templates under a name
 * derived deterministically from the arch, so resetViewCompilerCache() +
 * recompiling the same arch overwrites the same globalTemplates slot instead
 * of accumulating entries (the leak from the original FIXME).
 */

import { describe, expect, test } from "@odoo/hoot";
import { App, Component } from "@odoo/owl";
import { patchWithCleanup, serverState } from "@web/../tests/web_test_helpers";
import {
    DEFAULT_COMPILER_SEQUENCE,
    getShadowedCompilerReports,
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

    test("template name is a bounded digest of the arch, not the arch itself", () => {
        resetViewCompilerCache();
        const arch = document.createElement("list");
        arch.setAttribute("string", "Lines");
        const bigArch = document.createElement("list");
        bigArch.setAttribute("string", "L".repeat(5000));

        const name = useViewCompiler(TestCompiler, { list: arch }).list;
        const bigName = useViewCompiler(TestCompiler, { list: bigArch }).list;

        expect(name).toMatch(/^TestCompiler#\d+\/\/\d+\/\d+-\d+$/);
        expect(name).not.toInclude(arch.outerHTML);
        expect(bigName.length).toBeLessThan(bigArch.outerHTML.length);
        expect(bigName).not.toBe(name);
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

    test("the same arch under a different sibling set gets a different name", () => {
        resetViewCompilerCache();
        // `KanbanCompiler.compileTCall` reads the sibling names while compiling,
        // so an identical template compiles two ways depending on the set it
        // arrives in. Sharing a cache slot let whichever view compiled first
        // decide how the other rendered.
        const withSibling = makeTemplates([
            ["card", "div", { class: "c" }],
            ["sub", "div", {}],
        ]);
        const withoutSibling = makeTemplates([["card", "div", { class: "c" }]]);

        expect(withSibling.card.outerHTML).toBe(withoutSibling.card.outerHTML);
        expect(useViewCompiler(TestCompiler, withSibling).card).not.toBe(
            useViewCompiler(TestCompiler, withoutSibling).card,
        );
    });

    test("a renamed sibling changes the name too", () => {
        resetViewCompilerCache();
        const asSub = makeTemplates([
            ["card", "div", { class: "c" }],
            ["sub", "div", {}],
        ]);
        const asOther = makeTemplates([
            ["card", "div", { class: "c" }],
            ["other", "div", {}],
        ]);

        expect(useViewCompiler(TestCompiler, asSub).card).not.toBe(
            useViewCompiler(TestCompiler, asOther).card,
        );
    });

    test("sibling order does not change the name", () => {
        resetViewCompilerCache();
        const a = makeTemplates([
            ["card", "div", { class: "c" }],
            ["sub", "div", {}],
        ]);
        const b = {};
        b.sub = makeTemplates([["sub", "div", {}]]).sub;
        b.card = makeTemplates([["card", "div", { class: "c" }]]).card;

        expect(useViewCompiler(TestCompiler, a).card).toBe(
            useViewCompiler(TestCompiler, b).card,
        );
    });

    test("multiple templates in one call each get a distinct name", () => {
        resetViewCompilerCache();
        const templates = makeTemplates([
            ["form", "form", { string: "Main" }],
            ["buttons", "div", { class: "o_btn_box" }],
        ]);

        const result = useViewCompiler(TestCompiler, templates);

        expect(result.form).not.toBe(result.buttons);
        expect(result.form).toMatch(/\/\d+-\d+$/);
        expect(result.buttons).toMatch(/\/\d+-\d+$/);
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
        const compiled = compileArch(`<widget name="w" widget_id="w1" class="a'b"/>`);
        expect(compiled).toInclude(toStringExpression("a'b"));
        expect(owlCompileError(compiled, "test.widget.quote")).toBe(null);
    });

    test("a widget class holding a backtick still produces a compilable template", () => {
        const compiled = compileArch('<widget name="w" widget_id="w2" class="a`b"/>');
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

test("a <details>/<summary> block compiles through with its field intact", async () => {
    // `<details>` is how collapsible form arch is spelled now that Bootstrap's
    // collapse data-api is gone: it needs no whitelist entry server-side and no
    // JS client-side, but it must survive compileGenericNode with its children.
    const compiler = new ViewCompiler({});
    const arch = `
        <form>
            <details id="secret">
                <summary class="h3">Cannot scan it?</summary>
                <field name="secret"/>
            </details>
        </form>`;
    const doc = new DOMParser().parseFromString(arch, "text/xml").documentElement;
    const compiled = compiler.compileNode(doc, {});

    expect(compiled.querySelectorAll("details").length).toBe(1);
    expect(compiled.querySelector("details").getAttribute("id")).toBe("secret");
    expect(compiled.querySelectorAll("summary").length).toBe(1);
    expect(compiled.querySelector("summary").textContent).toInclude("Cannot scan it?");
});

test("a bootstrap dropdown container compiles into an OWL Dropdown", async () => {
    const compiler = new ViewCompiler({});
    const arch = `
        <form>
            <div class="dropdown dropdown-sm">
                <button class="btn border-0" type="button" data-bs-toggle="dropdown" aria-expanded="false">
                    <i class="fa-solid fa-ellipsis-v"/>
                </button>
                <div class="dropdown-menu extra-menu" role="menu">
                    <a class="dropdown-item" type="object" name="do_thing" string="Do it"/>
                </div>
            </div>
        </form>`;
    const doc = new DOMParser().parseFromString(arch, "text/xml").documentElement;
    const compiled = compiler.compileNode(doc, {});

    // The container survives; the toggle/menu pair becomes a Dropdown.
    const container = compiled.querySelector("div.dropdown");
    expect(container).not.toBe(null);
    expect(compiled.querySelectorAll("Dropdown").length).toBe(1);
    expect(compiled.querySelectorAll(".dropdown-menu").length).toBe(0);

    const dropdown = compiled.querySelector("Dropdown");
    expect(dropdown.getAttribute("menuClass")).toInclude("extra-menu");
    // The toggle is the default slot and is no longer a Bootstrap control.
    const toggle = dropdown.querySelector("button");
    expect(toggle.hasAttribute("data-bs-toggle")).toBe(false);
    expect(toggle.getAttribute("data-self-handled")).toBe("1");
    // The menu's action item still compiled into a ViewButton.
    const slot = dropdown.querySelector("t[t-set-slot='content']");
    expect(slot.querySelectorAll("ViewButton").length).toBe(1);
});

test("dropdown-menu-end becomes a Dropdown position instead of a class", async () => {
    const compiler = new ViewCompiler({});
    const arch = `
        <form>
            <div class="btn-group">
                <button type="button" data-bs-toggle="dropdown">Menu</button>
                <div class="dropdown-menu dropdown-menu-end"><span>x</span></div>
            </div>
        </form>`;
    const doc = new DOMParser().parseFromString(arch, "text/xml").documentElement;
    const dropdown = compiler.compileNode(doc, {}).querySelector("Dropdown");

    expect(dropdown.getAttribute("position")).toInclude("bottom-end");
    expect(dropdown.getAttribute("menuClass")).toBe(null);
});

test("a positioning class with no dropdown inside is left alone", async () => {
    const compiler = new ViewCompiler({});
    const arch = `
        <form>
            <div class="btn-group">
                <button type="object" name="a">A</button>
                <button type="object" name="b">B</button>
            </div>
        </form>`;
    const doc = new DOMParser().parseFromString(arch, "text/xml").documentElement;
    const compiled = compiler.compileNode(doc, {});

    expect(compiled.querySelectorAll("Dropdown").length).toBe(0);
    expect(compiled.querySelectorAll("ViewButton").length).toBe(2);
});

/**
 * The modal pairing runs in `compile()`, so these go through a real template
 * rather than calling `compileNode` directly.
 */
function compileArch(arch) {
    const doc = new DOMParser().parseFromString(arch, "text/xml").documentElement;
    return new ViewCompiler({ root: doc }).compile("root", {});
}

test("a bootstrap modal and its trigger compile into a Dialog driven by archDialogs", async () => {
    const compiled = compileArch(`
        <form>
            <a href="#" data-bs-toggle="modal" data-bs-target=".o_my_modal" class="opener">Open</a>
            <div class="modal o_my_modal">
                <div class="modal-dialog"><div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Hide Tips</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"/>
                    </div>
                    <div class="modal-body"><p>Are you sure?</p></div>
                    <div class="modal-footer">
                        <a class="btn btn-secondary cancel" data-bs-dismiss="modal">Cancel</a>
                    </div>
                </div></div>
            </div>
        </form>`);

    const dialog = compiled.querySelector("Dialog");
    expect(dialog).not.toBe(null);
    expect(dialog.getAttribute("title")).toInclude("Hide Tips");

    // Both halves address the same archDialogs entry.
    const openExpr = dialog.getAttribute("t-if");
    expect(openExpr).toInclude("__comp__.archDialogs");
    const key = openExpr.match(/\['(.+?)'\]/)[1];

    const opener = compiled.querySelector(".opener");
    expect(opener.getAttribute("t-on-click")).toInclude(`['${key}'] = true`);
    expect(opener.hasAttribute("data-bs-toggle")).toBe(false);

    // The footer's dismiss control closes that same entry.
    const footer = dialog.querySelector("t[t-set-slot='footer']");
    expect(footer.querySelector(".cancel").getAttribute("t-on-click")).toInclude(
        `['${key}'] = false`,
    );
});

test("a dismiss control that compiles to a component gets no DOM handler", async () => {
    // OWL does not bind `t-on-*` on a component node; emitting one would make
    // the compiled template fail to compile.
    const compiled = compileArch(`
        <form>
            <a href="#" data-bs-toggle="modal" data-bs-target=".m" class="opener">Open</a>
            <div class="modal m">
                <div class="modal-body">body</div>
                <div class="modal-footer">
                    <a type="action" name="42" data-bs-dismiss="modal">Act</a>
                </div>
            </div>
        </form>`);

    const footer = compiled.querySelector("t[t-set-slot='footer']");
    const action = footer.querySelector("ViewButton");
    expect(action).not.toBe(null);
    expect(action.hasAttribute("t-on-click")).toBe(false);
});

test("a modal nobody opens is left as ordinary markup", async () => {
    const compiled = compileArch(`
        <form>
            <div class="modal orphan"><div class="modal-body">nothing opens me</div></div>
        </form>`);

    expect(compiled.querySelectorAll("Dialog").length).toBe(0);
    expect(compiled.querySelectorAll(".modal").length).toBe(1);
});

test("a data-bs-target that is not valid CSS does not break compilation", async () => {
    const compiled = compileArch(`
        <form>
            <a data-bs-toggle="modal" data-bs-target="#not a selector((" class="opener">Open</a>
            <div class="modal real"><div class="modal-body">body</div></div>
        </form>`);

    expect(compiled.querySelectorAll("Dialog").length).toBe(0);
    expect(compiled.querySelectorAll(".opener").length).toBe(1);
});

test("the Odoo spelling drives the same dropdown construct as the Bootstrap one", async () => {
    const compiler = new ViewCompiler({});
    const arch = `
        <form>
            <div class="dropdown">
                <button type="button" data-self-handled="dropdown">Menu</button>
                <div class="dropdown-menu">
                    <a class="dropdown-item" type="object" name="go" string="Go"/>
                </div>
            </div>
        </form>`;
    const doc = new DOMParser().parseFromString(arch, "text/xml").documentElement;
    const compiled = compiler.compileNode(doc, {});

    expect(compiled.querySelectorAll("Dropdown").length).toBe(1);
    expect(compiled.querySelectorAll(".dropdown-menu").length).toBe(0);
    expect(compiled.querySelector("t[t-set-slot='content'] ViewButton")).not.toBe(null);
});

test("the Odoo spelling drives the same modal construct as the Bootstrap one", async () => {
    const compiled = compileArch(`
        <form>
            <a href="#" data-self-handled="modal" data-modal-target=".m" class="opener">Open</a>
            <div class="modal m">
                <div class="modal-body">body</div>
                <div class="modal-footer">
                    <a class="cancel" data-modal-dismiss="1">Cancel</a>
                </div>
            </div>
        </form>`);

    const dialog = compiled.querySelector("Dialog");
    expect(dialog).not.toBe(null);
    const key = dialog.getAttribute("t-if").match(/\['(.+?)'\]/)[1];
    expect(compiled.querySelector(".opener").getAttribute("t-on-click")).toInclude(
        `['${key}'] = true`,
    );
    expect(
        compiled
            .querySelector("t[t-set-slot='footer'] .cancel")
            .getAttribute("t-on-click"),
    ).toInclude(`['${key}'] = false`);
});

describe("ViewCompiler — shadowed compiler warning", () => {
    /** Build a bare ViewCompiler and drive its dispatch with a controlled set. */
    function compilerWith(base, appended) {
        const compiler = new ViewCompiler({});
        compiler.compilers = [...base];
        compiler.baseCompilerCount = compiler.compilers.length;
        compiler.compilers.push(...appended);
        return compiler;
    }

    test("warns once when a registered compiler is shadowed by an earlier one (debug)", () => {
        serverState.debug = "1";
        const compiler = compilerWith(
            [{ selector: "div", fn: () => document.createElement("span") }],
            [{ selector: "div.shadow_probe", fn: () => document.createElement("b") }],
        );
        /** @type {any[]} */
        const warnings = [];
        patchWithCleanup(console, { warn: (m) => warnings.push(m) });

        const node = document.createElement("div");
        node.classList.add("shadow_probe");
        compiler.compileNode(node, {}, false);

        expect(warnings).toHaveLength(1);
        expect(warnings[0]).toInclude(`The compiler for "div.shadow_probe" never runs`);
        expect(warnings[0]).toInclude(`"div"`);

        // Once per selector: a second matching node does not re-warn.
        const node2 = document.createElement("div");
        node2.classList.add("shadow_probe");
        compiler.compileNode(node2, {}, false);
        expect(warnings).toHaveLength(1);
    });

    test("does not warn without debug", () => {
        serverState.debug = "";
        const compiler = compilerWith(
            [{ selector: "div", fn: () => document.createElement("span") }],
            [{ selector: "div.no_warn_probe", fn: () => document.createElement("b") }],
        );
        /** @type {any[]} */
        const warnings = [];
        patchWithCleanup(console, { warn: (m) => warnings.push(m) });

        const node = document.createElement("div");
        node.classList.add("no_warn_probe");
        compiler.compileNode(node, {}, false);
        expect(warnings).toHaveLength(0);
    });

    test("does not warn for a built-in-vs-built-in overlap (deliberate ordering)", () => {
        serverState.debug = "1";
        const compiler = new ViewCompiler({});
        // Both overlapping entries are built-ins: the overlap is intended. A
        // third, non-built-in entry that matches nothing is appended so the
        // detection loop actually runs — without it the compiler carries no
        // extension at all and the assertion would hold vacuously.
        compiler.compilers = [
            {
                selector: "div",
                fn: () => document.createElement("span"),
                builtIn: true,
            },
            {
                selector: "div.builtin_probe",
                fn: () => document.createElement("i"),
                builtIn: true,
            },
        ];
        compiler.baseCompilerCount = compiler.compilers.length;
        compiler.compilers.push({
            selector: "section.never_matches",
            fn: () => document.createElement("b"),
        });
        /** @type {any[]} */
        const warnings = [];
        patchWithCleanup(console, { warn: (m) => warnings.push(m) });

        const node = document.createElement("div");
        node.classList.add("builtin_probe");
        compiler.compileNode(node, {}, false);
        expect(warnings).toHaveLength(0);
    });

    test("records the shadowing even with debug off", () => {
        // Detection used to be gated behind odoo.debug along with the warning,
        // which put the only signal that an extension never runs behind the flag
        // least likely to be set in production. The console stays quiet; the
        // record does not.
        serverState.debug = "";
        resetViewCompilerCache();
        const compiler = compilerWith(
            [
                {
                    selector: "div",
                    fn: () => document.createElement("span"),
                    builtIn: true,
                },
            ],
            [{ selector: "div.recorded_probe", fn: () => document.createElement("b") }],
        );
        /** @type {any[]} */
        const warnings = [];
        patchWithCleanup(console, { warn: (m) => warnings.push(m) });

        const node = document.createElement("div");
        node.classList.add("recorded_probe");
        compiler.compileNode(node, {}, false);

        expect(warnings).toHaveLength(0);
        const reports = getShadowedCompilerReports();
        expect(reports).toHaveLength(1);
        expect(reports[0].shadowed).toBe("div.recorded_probe");
        expect(reports[0].winner).toBe("div");
    });

    test("resetViewCompilerCache clears the recorded shadowings", () => {
        serverState.debug = "";
        resetViewCompilerCache();
        const compiler = compilerWith(
            [
                {
                    selector: "div",
                    fn: () => document.createElement("span"),
                    builtIn: true,
                },
            ],
            [{ selector: "div.cleared_probe", fn: () => document.createElement("b") }],
        );
        const node = document.createElement("div");
        node.classList.add("cleared_probe");
        compiler.compileNode(node, {}, false);
        expect(getShadowedCompilerReports()).toHaveLength(1);

        resetViewCompilerCache();
        expect(getShadowedCompilerReports()).toHaveLength(0);
    });
});

describe("ViewCompiler — dispatch sequence", () => {
    class SequencedCompiler extends ViewCompiler {
        setup() {
            this.compilers.push({
                selector: "field",
                fn: () => document.createElement("intercepted"),
                sequence: DEFAULT_COMPILER_SEQUENCE - 1,
            });
        }
    }

    class AppendedCompiler extends ViewCompiler {
        setup() {
            this.compilers.push({
                selector: "field",
                fn: () => document.createElement("appended"),
            });
        }
    }

    class UnshiftedCompiler extends ViewCompiler {
        setup() {
            this.compilers.unshift({
                selector: "field",
                fn: () => document.createElement("unshifted"),
            });
        }
    }

    test("a lower sequence intercepts a node the built-ins also match", () => {
        resetViewCompilerCache();
        const compiler = new SequencedCompiler({});
        const compiled = /** @type {Element} */ (
            compiler.compileNode(document.createElement("field"), {}, false)
        );
        expect(compiled.tagName.toLowerCase()).toBe("intercepted");
        // And nothing is reported as shadowed: the extension won.
        expect(getShadowedCompilerReports()).toHaveLength(0);
    });

    test("without a sequence, push still loses to the built-ins", () => {
        // The behaviour that made this gate necessary, kept as the control: the
        // default is unchanged, so `sequence` is opt-in rather than a silent
        // reordering of every existing compiler.
        resetViewCompilerCache();
        const compiler = new AppendedCompiler({});
        const compiled = /** @type {Element} */ (
            compiler.compileNode(document.createElement("field"), {}, false)
        );
        expect(compiled.tagName.toLowerCase()).not.toBe("appended");
        expect(getShadowedCompilerReports()).toHaveLength(1);
        expect(getShadowedCompilerReports()[0].shadowed).toBe("field");
    });

    test("without a sequence, unshift still beats the built-ins", () => {
        // The existing workaround (project_task_kanban_compiler) must keep
        // working: the sort is stable and every built-in carries the same
        // default, so an unshifted entry stays at index 0.
        resetViewCompilerCache();
        const compiler = new UnshiftedCompiler({});
        const compiled = /** @type {Element} */ (
            compiler.compileNode(document.createElement("field"), {}, false)
        );
        expect(compiled.tagName.toLowerCase()).toBe("unshifted");
    });

    test("built-ins keep their documented order relative to each other", () => {
        // The sort must be a no-op on a stock compiler. `.modal` is declared
        // after the arch-dialog control and before the dropdown container; if
        // the sort were unstable that order could change and dispatch with it.
        const stock = new ViewCompiler({});
        const selectors = stock.compilers.map((c) => c.selector);
        expect(selectors.at(-2)).toBe("field");
        expect(selectors.at(-1)).toBe("widget");
        expect(stock.compilers.every((c) => c.builtIn)).toBe(true);
    });
});

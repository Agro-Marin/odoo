// @ts-check

import { after, expect, test } from "@odoo/hoot";
import { Component, useRef, xml } from "@odoo/owl";
import { mountWithCleanup, patchTranslations } from "@web/../tests/web_test_helpers";
import {
    registerTemplate,
    registerTemplateExtension,
    setUrlFilters,
    TemplateRegistry,
    templates,
} from "@web/core/templates";

function makeTemplate({ name, content, inheritFrom }) {
    return `<t t-name="${name}" ${inheritFrom ? `t-inherit="${inheritFrom}"` : ``}>${content}</t>`;
}

function makeTemplateExtension({ content, inheritFrom }) {
    return `<t t-inherit="${inheritFrom}" t-inherit-mode="extension">${content}</t>`;
}

function visit(node, addon, terms) {
    for (const { value } of node.attributes) {
        terms[value] = `${value} (${addon})`;
    }
    for (const childNode of node.childNodes) {
        if (childNode.nodeType === Node.TEXT_NODE) {
            const text = childNode.data.trim();
            terms[text] = `${text} (${addon})`;
        } else {
            visit(childNode, addon, terms);
        }
    }
}

const parser = new DOMParser();
function extractTranslations(template, addon) {
    const doc = parser.parseFromString(template, "text/xml");
    const root = doc.firstChild;
    const terms = {};
    visit(root, addon, terms);
    return terms;
}

function registerTemplates(...templates) {
    const translations = {};

    for (const { name, content, inheritFrom, inheritMode } of templates) {
        // we should avoid do twice makeTemplate/makeTemplateExtension
        const template =
            inheritMode === "extension"
                ? makeTemplateExtension({ content, inheritFrom })
                : makeTemplate({ name, content, inheritFrom });
        const addon = `addon_${name}`;
        const terms = extractTranslations(template, addon);
        translations[addon] = terms;
        after(
            inheritMode === "extension"
                ? registerTemplateExtension(inheritFrom, `/${addon}`, template)
                : registerTemplate(name, `/${addon}`, template),
        );
    }
    patchTranslations(translations);
}

async function mountTestComponentWithTemplate(name) {
    class TestComponent extends Component {
        static props = ["*"];
        static template = xml`<div t-ref="root"><t t-call="${name}"/></div>`;
        setup() {
            this.rootRef = useRef("root");
        }
    }
    const component = await mountWithCleanup(TestComponent);
    return component.rootRef.el;
}

test("translation-context: single template", async () => {
    registerTemplates({
        name: "A",
        content: `
            <div class="o_test_component" title="title">
                text
            </div>
        `,
    });
    const el = await mountTestComponentWithTemplate("A");
    expect(el).toHaveInnerHTML(`
        <div class="o_test_component" title="title (addon_A)">
            text (addon_A)
        </div>
    `);
});

test("translation-context: xpath position replace (outer)", async () => {
    registerTemplates(
        {
            name: "A",
            content: `<div class="o_test_component" title="title"> text </div>`,
        },
        {
            name: "B",
            content: `
                <xpath expr="div" position="replace">
                    <div class="o_test_component" title="title"> text </div>
                </xpath>
            `,
            inheritFrom: "A",
        },
    );
    const el = await mountTestComponentWithTemplate("B");
    expect(el).toHaveInnerHTML(`
        <div class="o_test_component" title="title (addon_B)">
            text (addon_B)
        </div>
    `);
});

test("translation-context: xpath position replace (outer) with $0", async () => {
    registerTemplates(
        {
            name: "A",
            content: `<div class="o_test_component" title="title"> text </div>`,
        },
        {
            name: "B",
            content: `
                <xpath expr="div" position="replace">
                    <div class="o_test_component" title="title">
                        text
                        <div title="title2">$0</div>
                    </div>
                </xpath>
            `,
            inheritFrom: "A",
        },
    );
    const el = await mountTestComponentWithTemplate("B");
    expect(el).toHaveInnerHTML(`
        <div class="o_test_component" title="title (addon_B)">
            text (addon_B)
            <div title="title2 (addon_B)">
                <div class="o_test_component" title="title (addon_A)">
                    text (addon_A)
                </div>
            </div>
        </div>
    `);
});

test("translation-context: xpath position replace (inner)", async () => {
    registerTemplates(
        {
            name: "A",
            content: `
                <div class="o_test_component" title="title">
                    text
                    <span> text </span>
                </div>
            `,
        },
        {
            name: "B",
            content: `
                <xpath expr="div" position="replace" mode="inner">
                    <span>
                        text
                        <div title="title"> text </div>
                    </span>
                </xpath>
            `,
            inheritFrom: "A",
        },
    );
    const el = await mountTestComponentWithTemplate("B");
    expect(el).toHaveInnerHTML(`
        <div class="o_test_component" title="title (addon_A)">
            <span>
                text (addon_B)
                <div title="title (addon_B)">
                    text (addon_B)
                </div>
            </span>
        </div>
    `);
});

test("translation-context: xpath position attributes", async () => {
    registerTemplates(
        {
            name: "A",
            content: `<div class="o_test_component" title="title"> text </div>`,
        },
        {
            name: "B",
            content: `
                <xpath expr="div" position="attributes">
                    <attribute name="title">title</attribute>
                    <attribute name="label">label</attribute>
                </xpath>
            `,
            inheritFrom: "A",
        },
    );
    const el = await mountTestComponentWithTemplate("B");
    expect(el).toHaveInnerHTML(`
        <div class="o_test_component" title="title (addon_B)" label="label (addon_B)">
            text (addon_A)
        </div>
    `);
});

test("translation-context: xpath position inside", async () => {
    registerTemplates(
        {
            name: "A",
            content: `<div class="o_test_component" title="title"> text </div>`,
        },
        {
            name: "B",
            content: `
                <xpath expr="div" position="inside">
                    text
                    <span title="title"> text </span>
                    text
                </xpath>
            `,
            inheritFrom: "A",
        },
    );
    const el = await mountTestComponentWithTemplate("B");
    expect(el).toHaveInnerHTML(`
        <div class="o_test_component" title="title (addon_A)">
            text (addon_A) text (addon_B)
            <span title="title (addon_B)">
                text (addon_B)
            </span>
            text (addon_B)
        </div>
    `);
});

test("translation-context: xpath position inside: moved element", async () => {
    registerTemplates(
        {
            name: "A",
            content: `
                <div class="o_test_component">
                    <span>Hello</span>
                    <span>World</span>
                </div>
            `,
        },
        {
            name: "B",
            content: `
                <xpath expr="div/span" position="before">
                    <xpath expr="div/span[2]" position="move"/>
                </xpath>`,
            inheritFrom: "A",
        },
    );
    const el = await mountTestComponentWithTemplate("B");
    expect(el).toHaveInnerHTML(`
        <div class="o_test_component">
            <span>World (addon_A)</span>
            <span>Hello (addon_A)</span>
        </div>
    `);
});

test("translation-context: xpath position after with some text", async () => {
    registerTemplates(
        {
            name: "A",
            content: `
                <div class="o_test_component" title="title">
                    <span>text1</span>
                    <span>text2</span>
                </div>
            `,
        },
        {
            name: "B",
            content: `
                <xpath expr="div/span" position="after">
                    <div title="title">
                        text1
                    </div>
                    text2
                </xpath>
            `,
            inheritFrom: "A",
        },
    );
    const el = await mountTestComponentWithTemplate("B");
    expect(el).toHaveInnerHTML(`
        <div class="o_test_component" title="title (addon_A)">
            <span>
                text1 (addon_A)
            </span>
            <div title="title (addon_B)">
                text1 (addon_B)
            </div>
            text2 (addon_B)
            <span>
                text2 (addon_A)
            </span>
        </div>
    `);
});

test("translation-context: xpath position before with some text", async () => {
    registerTemplates(
        {
            name: "A",
            content: `
                <div class="o_test_component" title="title">
                    <span>text1</span>
                    <span>text2</span>
                </div>
            `,
        },
        {
            name: "B",
            content: `
                <xpath expr="div/span" position="before">
                    <div title="title">
                        text1
                    </div>
                    text2
                </xpath>
            `,
            inheritFrom: "A",
        },
    );
    const el = await mountTestComponentWithTemplate("B");
    expect(el).toHaveInnerHTML(`
        <div class="o_test_component" title="title (addon_A)">
            <div title="title (addon_B)">
                text1 (addon_B)
            </div>
            text2 (addon_B)
            <span>
                text1 (addon_A)
            </span>
            <span>
                text2 (addon_A)
            </span>
        </div>
    `);
});

test("translation-context: wrappers texts in t tags", async () => {
    registerTemplates(
        {
            name: "A",
            content: `
                <div class="o_test_component">
                    Hello
                </div>
            `,
        },
        {
            name: "B",
            content: `
                <xpath expr="div" position="inside">
                    World
                </xpath>`,
            inheritFrom: "A",
        },
    );
    const el = await mountTestComponentWithTemplate("B");
    expect(el).toHaveInnerHTML(`
        <div class="o_test_component">
            Hello (addon_A) World (addon_B)
        </div>
    `);
});

test("translation-context: wrappers texts in t tags (2)", async () => {
    after(setUrlFilters([]));
    registerTemplates(
        {
            name: "A",
            content: `
                <div class="o_test_component">
                    Hello
                </div>
            `,
        },
        {
            name: "B",
            content: `
                <xpath expr="div" position="inside">
                    World
                </xpath>`,
            inheritFrom: "A",
            inheritMode: "extension",
        },
    );
    const el = await mountTestComponentWithTemplate("A");
    expect(el).toHaveInnerHTML(`
        <div class="o_test_component">
            Hello (addon_A) World (addon_B)
        </div>
    `);
});

test("translation-context: wrappers texts in t tags (3)", async () => {
    after(setUrlFilters([]));
    registerTemplates(
        {
            name: "A",
            content: `
                <div class="o_test_component" title="title">
                    text
                </div>
            `,
        },
        {
            name: "B",
            content: `
                <xpath expr="div" position="inside">
                    text
                </xpath>`,
            inheritFrom: "A",
            inheritMode: "extension",
        },
        {
            name: "C",
            content: `
                <xpath expr="div" position="replace">
                    <div class="o_test_component" title="title">
                        text
                        <div title="title2">$0</div>
                    </div>
                </xpath>
            `,
            inheritFrom: "A",
        },
    );
    const el = await mountTestComponentWithTemplate("C");
    expect(el).toHaveInnerHTML(`
        <div class="o_test_component" title="title (addon_C)">
            text (addon_C)
            <div title="title2 (addon_C)">
                <div class="o_test_component" title="title (addon_A)">
                    text (addon_A) text (addon_B)
                </div>
            </div>
        </div>
    `);
});

test("translation-context: wrappers around texts do not affect xpaths (1)", async () => {
    registerTemplates(
        {
            name: "A",
            content: `
                <div class="o_test_component">
                    Hello
                    <t t-if="true">
                        Janet
                    </t>
                </div>
            `,
        },
        {
            name: "B",
            content: `
                <xpath expr="div/t" position="before">
                    World
                </xpath>`,
            inheritFrom: "A",
        },
        {
            name: "C",
            content: `
                <xpath expr="div/t" position="replace" mode="inner">
                    Jamie
                </xpath>`,
            inheritFrom: "B",
        },
    );
    const el = await mountTestComponentWithTemplate("C");
    expect(el).toHaveInnerHTML(`
        <div class="o_test_component">
            Hello (addon_A) World (addon_B)  Jamie (addon_C)
        </div>
    `);
});

// TemplateRegistry class — scoped-instance contract
//
// Module-level functions delegate to a singleton anchored on
// ``globalThis.__odooTemplates__`` (see templates.js). These tests verify the
// *class* contract: a fresh ``TemplateRegistry`` gives a fully isolated scope,
// for future embedded-app use cases that want their own registry.

test("TemplateRegistry: fresh instance has independent state from singleton", () => {
    const scoped = new TemplateRegistry();
    scoped.registerTemplate(
        "tr-iso-1",
        "/scoped_addon",
        `<t t-name="tr-iso-1"><div>scoped</div></t>`,
    );
    expect("tr-iso-1" in scoped.templates).toBe(true);
    expect("tr-iso-1" in templates.templates).toBe(false);
});

test("TemplateRegistry: module-level wrappers see the canonical singleton", () => {
    // ``templates`` IS the singleton the wrappers delegate to — load-bearing,
    // since boot/start.js passes ``getTemplate`` as a detached function
    // reference to OWL's App constructor, so it can't rely on `this`.
    const unreg = registerTemplate(
        "tr-canon-1",
        "/canon_addon",
        `<t t-name="tr-canon-1"/>`,
    );
    after(unreg);
    expect("tr-canon-1" in templates.templates).toBe(true);
});

test("TemplateRegistry: unregister callback removes scoped entry", () => {
    const scoped = new TemplateRegistry();
    const unreg = scoped.registerTemplate(
        "tr-unreg-1",
        "/scoped_addon",
        `<t t-name="tr-unreg-1"/>`,
    );
    expect("tr-unreg-1" in scoped.templates).toBe(true);
    expect(typeof unreg).toBe("function");
    unreg();
    expect("tr-unreg-1" in scoped.templates).toBe(false);
});

test("TemplateRegistry: primary unregister leaves other owners' extensions intact", () => {
    // The registry is a globalThis-shared singleton in production: the
    // unregister callback of a PRIMARY registration must only tear down the
    // state it created, not the raw extension registrations that other owners
    // added on the same template name (each has its own unregister callback).
    const scoped = new TemplateRegistry();
    const primary = `<t t-name="tr-shared"><div class="base"/></t>`;
    const makeExt = (attr) =>
        `<t t-inherit="tr-shared" t-inherit-mode="extension">` +
        `<xpath expr="div" position="attributes">` +
        `<attribute name="${attr}">1</attribute>` +
        `</xpath></t>`;
    const unregPrimary = scoped.registerTemplate("tr-shared", "/addon_a", primary);
    const unregExtB = scoped.registerTemplateExtension(
        "tr-shared",
        "/addon_b",
        makeExt("data-b"),
    );
    scoped.registerTemplateExtension("tr-shared", "/addon_c", makeExt("data-c"));
    // Populate the parse/compile caches so the unregister has to evict them.
    let div = scoped.getTemplate("tr-shared").querySelector("div");
    expect(div.hasAttribute("data-b")).toBe(true);
    expect(div.hasAttribute("data-c")).toBe(true);

    // Owner A tears down its primary registration (e.g. per-test cleanup),
    // then re-registers it: the other owners' extensions must still apply.
    unregPrimary();
    scoped.registerTemplate("tr-shared", "/addon_a", primary);
    div = scoped.getTemplate("tr-shared").querySelector("div");
    expect(div.hasAttribute("data-b")).toBe(true);
    expect(div.hasAttribute("data-c")).toBe(true);

    // And each extension's own unregister callback still works — scoped to
    // its own registration only.
    unregExtB();
    div = scoped.getTemplate("tr-shared").querySelector("div");
    expect(div.hasAttribute("data-b")).toBe(false);
    expect(div.hasAttribute("data-c")).toBe(true);
});

test("TemplateRegistry: re-registering a key with different content throws", () => {
    const scoped = new TemplateRegistry();
    scoped.registerTemplate(
        "tr-conflict",
        "/addon_a",
        `<t t-name="tr-conflict"><div/></t>`,
    );
    expect(() =>
        scoped.registerTemplate(
            "tr-conflict",
            "/addon_b",
            `<t t-name="tr-conflict"><span/></t>`,
        ),
    ).toThrow(/already exists/);
});

test("TemplateRegistry: re-registering the same key+content is idempotent", () => {
    const scoped = new TemplateRegistry();
    scoped.registerTemplate("tr-idem", "/addon_a", `<t t-name="tr-idem"/>`);
    const sizeBefore = scoped.registered.size;
    scoped.registerTemplate("tr-idem", "/addon_a", `<t t-name="tr-idem"/>`);
    expect(scoped.registered.size).toBe(sizeBefore);
});

test("TemplateRegistry: dedup hit returns a callable no-op unregister", () => {
    // `const un = registerTemplate(...); un()` must work regardless of
    // registration order in a test lifecycle: the second identical
    // registration used to return undefined, crashing the caller.
    const scoped = new TemplateRegistry();
    const first = scoped.registerTemplate(
        "tr-noop",
        "/addon_a",
        `<t t-name="tr-noop"/>`,
    );
    const second = scoped.registerTemplate(
        "tr-noop",
        "/addon_a",
        `<t t-name="tr-noop"/>`,
    );
    expect(typeof second).toBe("function");
    // The dedup no-op must not unregister the first registration.
    second();
    expect("tr-noop" in scoped.templates).toBe(true);
    first();
    expect("tr-noop" in scoped.templates).toBe(false);
});

test("TemplateRegistry: dedup hit is verified against the stored registration", () => {
    // The dedup keys are 53-bit hashes: a colliding key must not silently
    // skip a registration. Simulate a collision by pre-seeding the key that
    // a different triple hashes to.
    const scoped = new TemplateRegistry();
    const name = "tr-collision";
    const url = "/addon_a";
    const templateString = `<t t-name="tr-collision"/>`;
    // Compute this triple's dedup key by registering and reading it back.
    const probe = new TemplateRegistry();
    probe.registerTemplate(name, url, templateString);
    const [key] = [...probe.registered];
    // Seed the collision: key present, but no matching registration stored.
    scoped.registered.add(key);
    const unregister = scoped.registerTemplate(name, url, templateString);
    expect("tr-collision" in scoped.templates).toBe(true);
    expect(typeof unregister).toBe("function");
    unregister();
    expect("tr-collision" in scoped.templates).toBe(false);
});

test("TemplateRegistry: extension dedup hit returns a callable no-op unregister", () => {
    const scoped = new TemplateRegistry();
    scoped.registerTemplate("tr-ext-base", "/addon_a", `<t t-name="tr-ext-base"/>`);
    const ext = `<t t-inherit="tr-ext-base" t-inherit-mode="extension"/>`;
    const first = scoped.registerTemplateExtension("tr-ext-base", "/addon_b", ext);
    const second = scoped.registerTemplateExtension("tr-ext-base", "/addon_b", ext);
    expect(typeof first).toBe("function");
    expect(typeof second).toBe("function");
    second();
    // The extension registered by `first` must survive the no-op.
    const blocks = Object.values(scoped.templateExtensions["tr-ext-base"]);
    expect(blocks.some((block) => block.length > 0)).toBe(true);
});

test("TemplateRegistry: setUrlFilters returns a restore callback", () => {
    const scoped = new TemplateRegistry();
    const before = scoped.urlFilters;
    const restore = scoped.setUrlFilters([() => true]);
    expect(scoped.urlFilters).not.toBe(before);
    expect(scoped.urlFilters.length).toBe(1);
    expect(typeof restore).toBe("function");
    restore();
    expect(scoped.urlFilters).toBe(before);
});

test("TemplateRegistry: blockId cursor advances when register type alternates", () => {
    const scoped = new TemplateRegistry();
    scoped.registerTemplate("tr-cur-1", "/a", `<t t-name="tr-cur-1"/>`);
    const after1 = scoped.blockId;
    scoped.registerTemplateExtension("tr-cur-1", "/b", `<t/>`);
    const after2 = scoped.blockId;
    expect(after2).toBeGreaterThan(after1);
    scoped.registerTemplate("tr-cur-2", "/c", `<t t-name="tr-cur-2"/>`);
    expect(scoped.blockId).toBeGreaterThan(after2);
});

test("TemplateRegistry: registering after a negative-lookup probe serves the real template", () => {
    const scoped = new TemplateRegistry();
    // Probe an unknown name first. ``getTemplate`` memoises the ``null`` miss
    // behind a ``has()`` guard, so without eviction on registration the null
    // would be served forever.
    expect(scoped.getTemplate("tr-probe")).toBe(null);
    scoped.registerTemplate(
        "tr-probe",
        "/addon_probe",
        `<t t-name="tr-probe"><div class="real">real</div></t>`,
    );
    const tmpl = scoped.getTemplate("tr-probe");
    expect(tmpl).not.toBe(null);
    expect(tmpl.textContent).toMatch(/real/);
});

test("TemplateRegistry: an extension registered after the first get is applied on re-get", () => {
    const scoped = new TemplateRegistry();
    scoped.registerTemplate(
        "tr-late-ext",
        "/addon_base",
        `<t t-name="tr-late-ext"><div class="base">base</div></t>`,
    );
    // Eager render compiles and caches the pre-extension DOM.
    expect(scoped.getTemplate("tr-late-ext").textContent).toMatch(/base/);
    expect(scoped.getTemplate("tr-late-ext").textContent).not.toMatch(/ext/);

    // A lazily-loaded bundle registers an extension for the already-compiled
    // parent. Without cache eviction on registration, the stale pre-extension
    // DOM would be served forever.
    scoped.registerTemplateExtension(
        "tr-late-ext",
        "/addon_ext",
        `<t t-inherit="tr-late-ext" t-inherit-mode="extension"><xpath expr="div" position="inside"><span class="ext">ext</span></xpath></t>`,
    );
    expect(scoped.getTemplate("tr-late-ext").textContent).toMatch(/ext/);
});

test("TemplateRegistry: unregistering an extension does not re-apply it on re-get", () => {
    const scoped = new TemplateRegistry();
    scoped.registerTemplate(
        "tr-ext-base",
        "/addon_base",
        `<t t-name="tr-ext-base"><div class="base">base</div></t>`,
    );
    const unregExt = scoped.registerTemplateExtension(
        "tr-ext-base",
        "/addon_ext",
        `<t t-inherit="tr-ext-base" t-inherit-mode="extension"><xpath expr="div" position="inside"><span class="ext">ext</span></xpath></t>`,
    );
    // First build applies the extension.
    expect(scoped.getTemplate("tr-ext-base").textContent).toMatch(/ext/);
    // After unregistering, a re-get must NOT re-apply the removed extension
    // from the stale parsed/processed caches.
    unregExt();
    const rebuilt = scoped.getTemplate("tr-ext-base");
    expect(rebuilt.textContent).toMatch(/base/);
    expect(rebuilt.textContent).not.toMatch(/ext/);
});

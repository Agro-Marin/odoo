// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { TemplateRegistry } from "@web/core/templates";

describe.current.tags("headless");

const PARENT_V1 = `<t t-name="p"><div>V1</div></t>`;
const PARENT_V2 = `<t t-name="p"><div>V2</div></t>`;
const CHILD = `<t t-name="c" t-inherit="p" t-inherit-mode="primary">
    <xpath expr="//div" position="attributes"><attribute name="id">c</attribute></xpath>
</t>`;
const GRANDCHILD = `<t t-name="g" t-inherit="c" t-inherit-mode="primary">
    <xpath expr="//div" position="attributes"><attribute name="class">g</attribute></xpath>
</t>`;
const EXTENSION = `<t t-inherit="p" t-inherit-mode="extension">
    <xpath expr="//div" position="inside"><span>EXT</span></xpath>
</t>`;

/**
 * @param {TemplateRegistry} registry
 * @param {string} name
 */
function html(registry, name) {
    return /** @type {Element} */ (registry.getTemplate(name)).outerHTML;
}

describe("compiled-template invalidation", () => {
    test("the changed template itself is invalidated", () => {
        const r = new TemplateRegistry();
        const un = r.registerTemplate("p", "/a/a.xml", PARENT_V1);
        expect(html(r, "p")).toInclude("V1");
        un();
        r.registerTemplate("p", "/a/a.xml", PARENT_V2);
        expect(html(r, "p")).toInclude("V2");
    });

    test("a child is invalidated when its parent changes", () => {
        const r = new TemplateRegistry();
        const un = r.registerTemplate("p", "/a/a.xml", PARENT_V1);
        r.registerTemplate("c", "/a/b.xml", CHILD);
        expect(html(r, "c")).toInclude("V1");
        un();
        r.registerTemplate("p", "/a/a.xml", PARENT_V2);
        expect(html(r, "c")).toInclude("V2");
    });

    test("invalidation is transitive through the inheritance chain", () => {
        const r = new TemplateRegistry();
        const un = r.registerTemplate("p", "/a/a.xml", PARENT_V1);
        r.registerTemplate("c", "/a/b.xml", CHILD);
        r.registerTemplate("g", "/a/c.xml", GRANDCHILD);
        expect(html(r, "g")).toInclude("V1");
        un();
        r.registerTemplate("p", "/a/a.xml", PARENT_V2);
        expect(html(r, "g")).toInclude("V2");
    });

    test("an extension invalidates the template it targets", () => {
        const r = new TemplateRegistry();
        r.registerTemplate("p", "/a/a.xml", PARENT_V1);
        expect(html(r, "p")).not.toInclude("EXT");
        const un = r.registerTemplateExtension("p", "/a/d.xml", EXTENSION);
        expect(html(r, "p")).toInclude("EXT");
        un();
        expect(html(r, "p")).not.toInclude("EXT");
    });

    test("blockId still scopes an extension to the inheritors that follow it", () => {
        const before = new TemplateRegistry();
        before.registerTemplate("p", "/a/a.xml", PARENT_V1);
        before.registerTemplate("c", "/a/b.xml", CHILD);
        before.registerTemplateExtension("p", "/a/d.xml", EXTENSION);
        expect(html(before, "c")).not.toInclude("EXT");
        expect(html(before, "p")).toInclude("EXT");

        const after = new TemplateRegistry();
        after.registerTemplate("p", "/a/a.xml", PARENT_V1);
        after.registerTemplateExtension("p", "/a/d.xml", EXTENSION);
        after.registerTemplate("c", "/a/b.xml", CHILD);
        expect(html(after, "c")).toInclude("EXT");
    });

    test("an unrelated template keeps its cached result", () => {
        const r = new TemplateRegistry();
        const un = r.registerTemplate("p", "/a/a.xml", PARENT_V1);
        r.registerTemplate("other", "/a/o.xml", `<t t-name="other"><b>O</b></t>`);
        const before = r.getTemplate("other");
        un();
        r.registerTemplate("p", "/a/a.xml", PARENT_V2);
        expect(r.getTemplate("other")).toBe(before);
    });
});

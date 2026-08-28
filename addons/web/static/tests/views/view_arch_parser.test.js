// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { defineModels, fields, models } from "@web/../tests/web_test_helpers";
import { parseXML } from "@web/core/utils/dom/xml";
import { KanbanArchParser } from "@web/views/kanban/kanban_arch_parser";
import { ListArchParser } from "@web/views/list/list_arch_parser";
import { staticModifier, ViewArchParser } from "@web/views/view_arch_parser";

class Foo extends models.Model {
    name = fields.Char();
    _records = [{ id: 1, name: "a" }];
}
defineModels([Foo]);

const LIST_ARCH = `
    <list>
        <header>
            <button name="header_act" type="object" string="Header"/>
        </header>
        <field name="name"/>
        <control>
            <create string="Add a line" class="my-create-class"/>
            <button name="control_act" type="object" string="Control"/>
        </control>
    </list>`;

const KANBAN_ARCH = `
    <kanban>
        <header>
            <button name="header_act" type="object" string="Header"/>
        </header>
        <control>
            <create string="Add a line" class="my-create-class"/>
            <button name="control_act" type="object" string="Control"/>
        </control>
        <templates><t t-name="card"><field name="name"/></t></templates>
    </kanban>`;

/**
 * @param {typeof ListArchParser | typeof KanbanArchParser} ParserClass
 */
function stamping(ParserClass) {
    return class extends ParserClass {
        processButton(/** @type {any} */ node) {
            const parsed = super.processButton(node);
            parsed.stamped = true;
            return parsed;
        }
    };
}

function parse(/** @type {any} */ ParserClass, /** @type {any} */ arch) {
    return new ParserClass().parse(
        parseXML(arch),
        { foo: { fields: Foo._fields } },
        "foo",
    );
}

test("list: a processButton override reaches header AND control buttons", () => {
    const info = parse(stamping(ListArchParser), LIST_ARCH);
    expect(info.headerButtons[0].stamped).toBe(true);
    expect(
        info.controls.find((/** @type {any} */ c) => c.type === "button").stamped,
    ).toBe(true);
});

test("kanban: a processButton override reaches header AND control buttons", () => {
    const info = parse(stamping(KanbanArchParser), KANBAN_ARCH);
    expect(info.headerButtons[0].stamped).toBe(true);
    expect(
        info.controls.find((/** @type {any} */ c) => c.type === "button").stamped,
    ).toBe(true);
});

test("list and kanban parse <control> to the same shape", () => {
    const listControls = parse(ListArchParser, LIST_ARCH).controls;
    const kanbanControls = parse(KanbanArchParser, KANBAN_ARCH).controls;
    expect(listControls.find((/** @type {any} */ c) => c.type === "create")).toEqual(
        kanbanControls.find((/** @type {any} */ c) => c.type === "create"),
    );
    expect(listControls.find((/** @type {any} */ c) => c.type === "create").class).toBe(
        "my-create-class",
    );
});

test("header buttons keep the arch's button numbering", () => {
    const info = parse(ListArchParser, LIST_ARCH);
    expect(info.headerButtons.map((/** @type {any} */ b) => b.id)).toEqual([0]);
    expect(info.headerButtons[0].type).toBe("button");
});

describe("staticModifier", () => {
    test("reads all six literal spellings, not the three the parsers open-coded", () => {
        expect(staticModifier("1")).toBe(true);
        expect(staticModifier("True")).toBe(true);
        expect(staticModifier("true")).toBe(true);
        expect(staticModifier("0")).toBe(false);
        expect(staticModifier("False")).toBe(false);
        expect(staticModifier("false")).toBe(false);
    });

    test("an absent modifier is false, an expression is undefined", () => {
        expect(staticModifier(null)).toBe(false);
        expect(staticModifier(undefined)).toBe(false);
        expect(staticModifier("")).toBe(false);
        expect(staticModifier("context.get('default_project_id', False)")).toBe(
            undefined,
        );
        expect(staticModifier("record.foo")).toBe(undefined);
    });
});

describe("visitArch", () => {
    test("dispatches by tag, ignores unregistered tags, and calls handlers on this", () => {
        class Probe extends ViewArchParser {
            tag = "probe";
            parse(/** @type {any} */ arch) {
                return this.visitArch(
                    arch,
                    /** @type {{ roots: string[], fields: (string | null)[] }} */ ({
                        roots: [],
                        fields: [],
                    }),
                    {
                        probe: this.onRoot,
                        field: (node, info) =>
                            info.fields.push(node.getAttribute("name")),
                    },
                );
            }
            onRoot(/** @type {any} */ node, /** @type {any} */ info) {
                info.roots.push(this.tag);
            }
        }
        const info = new Probe().parse(
            parseXML(`<probe><field name="a"/><ignored/><field name="b"/></probe>`),
        );
        expect(info).toEqual({ roots: ["probe"], fields: ["a", "b"] });
    });
});
